"""Components saved as data, and loaded back: manifests.

Every part of an agent -- assistant, workflow, node, tool, topic -- is a
:class:`Component`, a pydantic model. Its JSON form, ``model_dump(mode="json")``,
holds its fields and names its class by import path::

    {"class": "grafi.tools.llms.impl.openai_tool:OpenAITool",
     "name": "OpenAITool", "model": "gpt-4.1-nano",
     "api_key": {"env": "OPENAI_API_KEY"}, ...}

and ``model_validate`` builds that class back, so a subclass loads as itself,
with its own fields. A field holding a function is typed
:data:`~grafi.common.callable_ref.CallableRef`, and one holding a pydantic model
class :data:`ModelRef`; both are saved as ``{"ref": "module:qualname"}``.
Loading imports classes and functions from trusted modules only: grafi's, and
those named with :func:`~grafi.common.import_ref.trust_modules`.

Secrets are saved as references to environment variables, never as values. A
field declared with :func:`env_secret` is saved as ``{"env": "VAR"}``, and
saving one set to a value that is not its variable's raises
:class:`ManifestError`, as does saving a value recognized as a secret anywhere
else (see :mod:`grafi.common.secrets`). These rules apply to the JSON form:
``model_dump()`` gives a component's values, as pydantic does.

A manifest wraps a component's JSON in an envelope naming the format and the
component's kind, ``{"apiVersion": "grafi/v2", "kind": "Assistant", "spec":
{...}}``: see :meth:`Component.to_manifest` and :meth:`Component.from_manifest`,
which also reads a manifest saved before this format. ``from_manifest`` loads a
manifest you did not write with care, under a :class:`ManifestPolicy`: every
component in it names its class, no secret is given as a value, and a secret is
read only from its own environment variable, or one you name. A manifest still
chooses what its components call -- an LLM's ``base_url``, an MCP server's URL
or command -- and they get the secrets the components use: load manifests from
sources you trust with those.
"""

import functools
import inspect
import json
import os
from contextlib import AbstractContextManager
from contextlib import nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import FrozenSet
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Self
from typing import Type
from typing import TypeVar
from typing import Union

from pydantic import BaseModel
from pydantic import BeforeValidator
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ModelWrapValidatorHandler
from pydantic import PlainSerializer
from pydantic import PrivateAttr
from pydantic import SerializationInfo
from pydantic import SerializerFunctionWrapHandler
from pydantic import ValidationInfo
from pydantic import model_serializer
from pydantic import model_validator
from pydantic_core import PydanticSerializationError

from grafi.common.exceptions.manifest_exceptions import ManifestError
from grafi.common.import_ref import is_import_path
from grafi.common.import_ref import reference_to
from grafi.common.import_ref import resolve_import_ref
from grafi.common.secrets import env_reference
from grafi.common.secrets import held_secret

__all__ = [
    "API_VERSION",
    "Component",
    "ManifestError",
    "ManifestPolicy",
    "ModelRef",
    "env_secret",
    "import_path",
    "kind_of",
    "save_refused",
]

API_VERSION = "grafi/v2"

# The validation context key of the policy from_manifest() loads under.
_POLICY = "grafi_manifest_policy"

C = TypeVar("C", bound="Component")
E = TypeVar("E", bound=Exception)
T = TypeVar("T")


# The errors raised while to_manifest() saves a component, in this context:
# pydantic reports one raised by a nested component or field only as text.
_save_errors: ContextVar[Optional[List[Exception]]] = ContextVar(
    "grafi_manifest_save_errors", default=None
)


def save_refused(error: E) -> E:
    """``error``, which refuses to save a component, as it is to be raised:
    recorded, so that :meth:`Component.to_manifest` raises it as it is, where
    ``model_dump`` would report only its text."""
    errors = _save_errors.get()
    if errors is not None:
        errors.append(error)
    return error


@dataclass(frozen=True)
class ManifestPolicy:
    """What :meth:`Component.from_manifest` allows a manifest: the environment
    variables it may read, besides each secret field's own. A load has one in
    its validation context when it is of a manifest."""

    env: FrozenSet[str]

    @classmethod
    def of(cls, context: Any) -> Optional["ManifestPolicy"]:
        """The policy of the load with this validation ``context``, if it is a
        load of a manifest."""
        policy = context.get(_POLICY) if isinstance(context, Mapping) else None
        return policy if isinstance(policy, ManifestPolicy) else None

    def check_env(self, var: str, own: Optional[str] = None) -> None:
        """Refuse reading the environment variable ``var``, unless it is
        ``own``, a secret field's own, or allowed."""
        if var != own and var not in self.env:
            raise ManifestError(
                f"The manifest reads the environment variable {var!r}; allow it "
                f"with from_manifest(..., env=[{var!r}])."
            )


class _EnvSecret:
    """Field metadata: the field holds a secret, read from ``var``."""

    def __init__(self, var: Optional[str]) -> None:
        self.var = var


def env_secret(var: Optional[str] = None, **kwargs: Any) -> Any:
    """A field holding a secret, such as an API key, read by default from the
    environment variable ``var`` (None without one).

    It is saved as a reference to its variable, ``{"env": "VAR"}``, never as
    its value, and is left out of the component's repr. The field holds text:
    type it ``Optional[str]``, not ``SecretStr``. A manifest can name
    another variable, which the component then reads and saves again. A value
    set in code must be that variable's: saving any other raises
    :class:`ManifestError`, as the manifest would load a different one.
    """
    if kwargs.keys() & {"alias", "serialization_alias", "validation_alias"}:
        raise TypeError("A secret field is saved by its name: it takes no alias.")
    if var is None:
        kwargs.setdefault("default", None)
    else:
        kwargs.setdefault("default_factory", lambda: os.getenv(var))
    field = Field(repr=False, **kwargs)
    field.metadata.append(_EnvSecret(var))
    return field


@functools.cache
def _secret_vars(cls: Type[BaseModel]) -> Dict[str, Optional[str]]:
    """The class's secret fields, and the variable each is read from."""
    return {
        name: marker.var
        for name, field in cls.model_fields.items()
        for marker in field.metadata
        if isinstance(marker, _EnvSecret)
    }


@functools.cache
def _unsaved(cls: Type[BaseModel]) -> FrozenSet[str]:
    """The class's fields saving leaves out, such as what follows from others."""
    return frozenset(name for name, field in cls.model_fields.items() if field.exclude)


def import_path(obj: Any) -> str:
    """``"module:qualname"``, the reference that imports ``obj`` back.

    Raises:
        ManifestError: If nothing imports it back from a fresh process, as for
            what a script (``__main__``) or a function defines.
    """
    ref = reference_to(obj)
    if ref is None:
        raise save_refused(
            ManifestError(
                f"{obj!r} cannot be saved by reference: define it at the top "
                "level of a module that can be imported, not in a script or a "
                "function."
            )
        )
    return ref


def kind_of(cls: type) -> str:
    """What a manifest calls a component of class ``cls``: its nearest
    ``manifest_kind``, else its name."""
    for klass in cls.__mro__:
        kind = vars(klass).get("manifest_kind")
        if kind:
            return str(kind)
    return cls.__name__


def _load_class(path: Any, base: Type[C]) -> Type[C]:
    """The class ``path`` names, a subclass of ``base``: by its import path,
    or itself, as a python-mode dump holds it."""
    if inspect.isclass(path):
        cls = path
    elif isinstance(path, str):
        cls = resolve_import_ref(path)
    else:
        raise ManifestError(f"A class must be named by its import path: {path!r}")
    if not (inspect.isclass(cls) and issubclass(cls, base)):
        raise ManifestError(f"{path!r} is not a subclass of {base.__name__}")
    return cls


class Component(BaseModel):
    """A part of an agent, saved as data and loaded back; see this module.

    A component is always saved as its own class, with all its fields, even
    where a field declares one of its bases; and loading one refuses a field
    it does not have, so a misspelt one is not ignored.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        polymorphic_serialization=True,
        # A secret read into the data being validated is not shown in errors.
        hide_input_in_errors=True,
    )

    # What a manifest calls this kind of component, for a class whose
    # subclasses are one; see to_manifest().
    manifest_kind: ClassVar[Optional[str]] = None

    # Secret fields read from a variable other than their own, by field.
    _secret_env: Dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if _secret_vars(cls) and cls.model_config.get("alias_generator"):
            raise TypeError(
                f"{cls.__name__} has secret fields, which are saved by their "
                "names: it takes no alias_generator."
            )

    def __init__(self, /, **data: Any) -> None:
        named = data.pop("class", None)
        if named is not None and _load_class(named, Component) is not type(self):
            raise ManifestError(
                f"The data is a {named}; load it with "
                f"{type(self).__name__}.model_validate(data)."
            )
        super().__init__(**data)

    # It validates as BaseModel's does, so pydantic validates without calling
    # it, keeping the validation context (as pydantic's RootModel marks its own).
    __init__.__pydantic_base_init__ = True  # type: ignore[attr-defined]

    def secret_variable(self, field: str) -> Optional[str]:
        """The environment variable the secret ``field`` is read from: the one
        a manifest named for it, else its own."""
        return self._secret_env.get(field, _secret_vars(type(self)).get(field))

    @model_serializer(mode="wrap")
    def _save(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> Dict[str, Any]:
        data = handler(self)
        cls = type(self)
        if not info.mode_is_json():
            return {"class": cls, **data}
        secrets = _secret_vars(cls)
        for name in secrets.keys() & data.keys():
            data[name] = self._secret_reference(name)
        for name in data.keys() - secrets.keys():
            held = held_secret(name, data[name])
            if held is not None:
                raise save_refused(
                    ManifestError(
                        f"{cls.__name__}.{name} holds a secret, at '{held}', and "
                        "a manifest never holds one: declare a secret field with "
                        "grafi.common.manifest.env_secret(), to save it as a "
                        "reference to an environment variable."
                    )
                )
        return {"class": import_path(cls), **data}

    def _secret_reference(self, name: str) -> Any:
        """The secret field ``name`` as saved: a reference to its variable."""
        var, value = self.secret_variable(name), getattr(self, name)
        if var is None and value is None:
            return None
        if var is not None and (value is None or value == os.getenv(var)):
            return {"env": var}
        source = f"the environment variable {var}" if var else "an environment variable"
        raise save_refused(
            ManifestError(
                f"{type(self).__name__}.{name} is set to a value that is not "
                f"{source}'s, and a manifest never holds a secret: read it "
                "from an environment variable."
            )
        )

    @model_validator(mode="wrap")
    @classmethod
    def _load(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self], info: ValidationInfo
    ) -> Self:
        if not isinstance(data, Mapping):
            return handler(data)
        policy = ManifestPolicy.of(info.context)
        if "class" in data:
            target = _load_class(data["class"], cls)
            if target is not cls:
                return target.model_validate(data, context=info.context)
            data = {key: value for key, value in data.items() if key != "class"}
        elif policy is not None:
            raise ManifestError(
                'Every component in a manifest names its class, as "class"; '
                f"this {cls.__name__} does not."
            )
        if policy is not None:
            cls._check_manifest_rules(data)
        data = dict(data)
        secret_env: Dict[str, str] = {}
        for name, own in _secret_vars(cls).items():
            var = env_reference(data.get(name))
            if var is None:
                continue
            if policy is not None:
                policy.check_env(var, own)
            data[name] = os.getenv(var)
            if var != own:
                secret_env[name] = var
        with cls._load_scope(data, info.context):
            component = handler(data)
        component._secret_env.update(secret_env)
        return component

    @classmethod
    def _check_manifest_rules(cls, data: Mapping[str, Any]) -> None:
        """Refuse what a manifest never holds, as saving never writes it: a
        component with an ``__init__`` of its own, a field saving leaves out,
        a secret given as a value."""
        if cls.__init__ is not Component.__init__:
            # Pydantic validates such a class by calling its __init__, which
            # would load what it holds without the manifest's rules.
            raise ManifestError(
                f"{cls.__name__} has an __init__ of its own, so it cannot be "
                "loaded from a manifest: set it up in model_post_init()."
            )
        for name in data.keys() & _unsaved(cls):
            raise ManifestError(
                f"{cls.__name__}.{name} is never saved, so a manifest does not "
                "hold it."
            )
        secrets = _secret_vars(cls)
        for name in data.keys() - secrets.keys():
            held = held_secret(name, data[name])
            if held is not None:
                raise ManifestError(
                    f"{cls.__name__}.{name} holds a secret, at '{held}', and a "
                    "manifest never holds one."
                )
        for name, own in secrets.items():
            if name in data and env_reference(data[name]) is None:
                if data[name] is not None or own is not None:  # Nor null for one.
                    raise ManifestError(
                        f"{cls.__name__}.{name} is given a value, and a manifest "
                        'never holds a secret: refer to its variable, {"env": "VAR"}.'
                    )

    @classmethod
    def _load_scope(
        cls, data: Dict[str, Any], context: Any
    ) -> AbstractContextManager[object]:
        """What loading ``data`` needs in scope, taken out of it: a workflow
        puts its topics in scope here, which its nodes name."""
        return nullcontext()

    def to_manifest(self) -> Dict[str, Any]:
        """This component as a manifest: its JSON, in the envelope naming the
        format and its kind.

        Raises:
            ManifestError: If it cannot be saved, as when it holds a secret.
        """
        errors: List[Exception] = []
        token = _save_errors.set(errors)
        try:
            spec = self.model_dump(mode="json")
        except PydanticSerializationError:
            if errors:
                raise errors[0] from None
            raise
        finally:
            _save_errors.reset(token)
        return {"apiVersion": API_VERSION, "kind": kind_of(type(self)), "spec": spec}

    @classmethod
    def from_manifest(
        cls,
        manifest: Union[Mapping[str, Any], str, Path],
        *,
        env: Iterable[str] = (),
        legacy_classes: Optional[Mapping[str, Union[str, type]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Self:
        """Load the component a manifest holds, a dict or the path of a JSON
        file, which must be one of this class.

        Every component in it must name its class, hold only what saving
        writes, and refer to its secrets by environment variable: each to its
        field's own, or to one of ``env``.
        ``context`` is the validation context, such as the topics a node's
        manifest names, by name: ``{"topics": {...}}``; a workflow's manifest
        holds its topics.

        A manifest saved before ``grafi/v2`` (an assistant's ``to_dict()``) is
        upgraded first. It names tool classes by their bare names: grafi's own
        are known, and ``legacy_classes`` maps others to their classes, or
        import paths, such as ``{"WeatherTool": "my_app.tools:WeatherTool"}``.

        Raises:
            ManifestError: If the manifest is not one of this class's, or
                breaks a rule above.
            UntrustedImportError: If it names a class or function outside the
                trusted modules (see grafi.common.import_ref.trust_modules).
            pydantic.ValidationError: If a component's fields are invalid.
        """
        if isinstance(env, str):
            raise TypeError(f"env is the variables' names: env=[{env!r}]")
        spec, target = cls._spec_of(manifest, legacy_classes)
        policy = ManifestPolicy(env=frozenset(env))
        return target.model_validate(spec, context={**(context or {}), _POLICY: policy})

    @classmethod
    def _spec_of(
        cls,
        manifest: Union[Mapping[str, Any], str, Path],
        legacy_classes: Optional[Mapping[str, Union[str, type]]],
    ) -> "tuple[Dict[str, Any], Type[Self]]":
        """A manifest's spec, and the class it is of, checked against the
        envelope before anything is built."""
        if isinstance(manifest, (str, Path)):
            manifest = json.loads(Path(manifest).read_text())
        if not isinstance(manifest, Mapping):
            raise ManifestError(f"A manifest is a JSON object, not {type(manifest)}")
        try:  # As JSON holds it: no value of another kind.
            manifest = json.loads(json.dumps(manifest))
        except (TypeError, ValueError) as error:
            raise ManifestError(f"A manifest holds only JSON: {error}") from error
        if "apiVersion" not in manifest:
            from grafi.common.manifest_v1 import upgrade_manifest

            manifest = upgrade_manifest(manifest, legacy_classes or {}, cls)
        if manifest.get("apiVersion") != API_VERSION:
            raise ManifestError(
                f"Unsupported manifest version {manifest.get('apiVersion')!r}; "
                f"this grafi reads {API_VERSION!r}."
            )
        spec = manifest.get("spec")
        if not isinstance(spec, Mapping) or "class" not in spec:
            raise ManifestError("A manifest's spec is a component, with its class.")
        target = _load_class(spec["class"], cls)
        kind = manifest.get("kind")
        if kind != kind_of(target):
            raise ManifestError(
                f"The manifest's kind is {kind!r}, but its spec is of kind "
                f"{kind_of(target)!r}."
            )
        return dict(spec), target


def _model_class(value: Any) -> bool:
    return inspect.isclass(value) and issubclass(value, BaseModel)


def _save_model_refs(value: Any) -> Any:
    """``value`` with each pydantic model class in it, in dicts and lists too,
    replaced by a reference to it, ``{"ref": "module:Qualname"}``."""
    if _model_class(value):
        return {"ref": import_path(value)}
    if isinstance(value, Mapping):
        return {key: _save_model_refs(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_save_model_refs(item) for item in value]
    return value


def _load_model_refs(value: Any) -> Any:
    """``value`` with each reference written by :func:`_save_model_refs`
    replaced by the model class it names."""
    if isinstance(value, Mapping):
        if set(value) == {"ref"} and is_import_path(str(value["ref"])):
            return _load_class(value["ref"], BaseModel)
        return {key: _load_model_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_load_model_refs(item) for item in value]
    return value


# A field holding pydantic model classes, as its value or within dicts and
# lists (such as an LLM's ``response_format``), saved as their import paths:
# ``ModelRef[Dict[str, Any]]``.
ModelRef = Annotated[
    T,
    PlainSerializer(_save_model_refs, when_used="json"),
    BeforeValidator(_load_model_refs),
]
