"""Components saved as data, and loaded back: manifests.

Every part of an agent -- assistant, workflow, node, tool, topic -- is a
:class:`Component`, a pydantic model. Its JSON form, ``model_dump(mode="json")``,
holds its fields and names its class by import path::

    {"class": "grafi.tools.llms.impl.openai_tool:OpenAITool",
     "name": "OpenAITool", "model": "gpt-4o-mini",
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
``model_dump()`` gives a component's values, as pydantic does, but a dump is
configuration: a secret read from a variable is ``{"env": "VAR"}`` in it, read
again when loaded. ``model_copy()`` copies a component in use, with its keys.

A manifest wraps a component's JSON in an envelope naming the format and the
component's kind, ``{"apiVersion": "grafi/v2", "kind": "Assistant", "spec":
{...}}``: see :meth:`Component.to_manifest` and :meth:`Component.from_manifest`,
which also reads a manifest saved before this format. ``from_manifest``
loads data you did not write yourself, under a :class:`ManifestPolicy`: every
component in it names its class, gives no secret as a value, and reads only
each secret field's own environment variable, or one ``allow_env`` names.
``model_validate`` and the constructors trust what they are given, as code: a
component built from data that way reads what it names. A manifest still
chooses what its components call -- an LLM's ``base_url``, an MCP server's URL
or command -- and they get the secrets the components use: load manifests from
sources you trust with those.
"""

import functools
import inspect
import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import TYPE_CHECKING
from typing import Annotated
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Collection
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import Literal
from typing import Mapping
from typing import Optional
from typing import Self
from typing import Set
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union
from typing import get_args
from typing import get_origin
from typing import overload

from pydantic import AliasChoices
from pydantic import AliasPath
from pydantic import BaseModel
from pydantic import BeforeValidator
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ModelWrapValidatorHandler
from pydantic import PlainSerializer
from pydantic import PrivateAttr
from pydantic import SerializationInfo
from pydantic import SerializerFunctionWrapHandler
from pydantic import ValidationError
from pydantic import ValidationInfo
from pydantic import model_serializer
from pydantic import model_validator
from pydantic.fields import FieldInfo
from pydantic_core import PydanticSerializationError

from grafi.common.exceptions.base import GrafiError
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
    "ModelRef",
    "SecretInput",
    "env_secret",
    "import_path",
]

API_VERSION = "grafi/v2"

# A secret as a builder takes it: its value, or the variable to read it from,
# {"env": "VAR"}, as Component.secret_reference() gives it.
SecretInput = Union[str, Dict[str, str], None]

# The validation context key of the policy from_manifest() loads under.
_POLICY = "grafi_manifest_policy"

C = TypeVar("C", bound="Component")
E = TypeVar("E", bound=Exception)
T = TypeVar("T")


# The class being loaded, and the variables its secret fields read, by field,
# while it is set up (as an assistant builds its workflow), before they are
# recorded on it.
_loading_secrets: ContextVar[Optional[Tuple[type, Dict[str, str]]]] = ContextVar(
    "grafi_loading_secrets", default=None
)

# The errors raised while to_manifest() saves a component, in this context:
# pydantic reports one raised by a nested component or field only as text.
_save_errors: ContextVar[Optional[List[Exception]]] = ContextVar(
    "grafi_manifest_save_errors", default=None
)


def save_refused(error: E) -> E:
    """``error``, refusing to save a component, recorded so that
    :meth:`Component.to_manifest` raises it as it is: pydantic would report
    only its text."""
    errors = _save_errors.get()
    if errors is not None:
        errors.append(error)
    return error


@dataclass(frozen=True)
class ManifestPolicy:
    """What :meth:`Component.from_manifest` allows a manifest: the environment
    variables it may read, besides each secret field's own. A load has one in
    its validation context when it is of a manifest."""

    env: FrozenSet[str] = frozenset()

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
                f"with from_manifest(..., allow_env=[{var!r}])."
            )


class _EnvSecret:
    """Field metadata: the field holds a secret, read from ``var``."""

    def __init__(self, var: Optional[str]) -> None:
        self.var = var


class ChecksOwnSecrets:
    """Field metadata: the field's type checks the secrets its values hold
    itself, when saved and when loaded from a manifest, as ``MCPConfig`` does;
    the component holding it does not check them again."""


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
def _self_checked(cls: Type[BaseModel]) -> FrozenSet[str]:
    """The class's fields whose values check their own secrets: components,
    which check theirs, and fields marked :class:`ChecksOwnSecrets`."""
    types = {name: field.annotation for name, field in cls.model_fields.items()}
    types.update(
        {name: field.return_type for name, field in cls.model_computed_fields.items()}
    )
    marked = {
        name
        for name, field in cls.model_fields.items()
        if any(_checks_own(marker) for marker in field.metadata)
    }
    return frozenset(marked | {name for name, t in types.items() if _checks_own(t)})


def _checks_own(annotation: Any) -> bool:
    """Whether every value of a type, such as ``Optional[MCPConfig]`` or
    ``Dict[str, Tool]``, checks its own secrets: a component, or a type
    marked :class:`ChecksOwnSecrets`."""
    if isinstance(annotation, ChecksOwnSecrets):
        return True
    if inspect.isclass(annotation) and issubclass(annotation, Component):
        return True
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return any(isinstance(m, ChecksOwnSecrets) for m in args[1:]) or (
            _checks_own(args[0])
        )
    if inspect.isclass(origin) and issubclass(origin, Mapping):
        args = args[1:]  # Its values; its keys are names.
    values = [arg for arg in args if arg is not type(None) and arg is not Ellipsis]
    return bool(values) and all(_checks_own(arg) for arg in values)


def _refuse_held_secrets(cls: Type[BaseModel], data: Mapping[str, Any]) -> None:
    """Raise :class:`ManifestError` for a secret a component's ``data`` holds
    as a value, outside its secret fields and the fields checking their own."""
    skipped = _secret_vars(cls).keys() | _self_checked(cls)
    for name in data:
        if name in skipped:
            continue
        held = held_secret(name, data[name])
        if held is not None:
            text = json.dumps(data[name], default=str)
            notes = [
                getattr(cls, "secret_hint", ""),
                'only an MCP configuration expands "${VAR}"' if "${" in text else "",
                'only a secret field reads {"env": ...}' if '"env"' in text else "",
            ]
            raise save_refused(
                ManifestError(
                    f"{cls.__name__}.{name} holds a secret, at '{held}', and a "
                    "manifest never holds one: read it from an environment "
                    "variable, in a field declared with "
                    "grafi.common.manifest.env_secret()"
                    + "".join(f"; {note}" for note in notes if note)
                    + "."
                )
            )


def _dumped(name: str, info: SerializationInfo, cls: Type[BaseModel]) -> bool:
    """Whether a dump with ``info``'s options includes the field ``name``, but
    for the values it leaves out."""
    return (
        not cls.model_fields[name].exclude
        and (info.include is None or name in info.include)
        and (info.exclude is None or name not in info.exclude)
    )


def _named(annotation: Any) -> str:
    """A type as it is written: ``str``, ``Optional[int]``."""
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _holds_text(annotation: Any) -> bool:
    """Whether a field of ``annotation`` holds text or none, as read from a
    variable: ``str``, optionally ``None`` (a constraint, or a subclass, would
    apply on loading but not to the value read by default, nor when used)."""
    if get_origin(annotation) in (Union, UnionType):
        return all(arg in (str, type(None)) for arg in get_args(annotation))
    return annotation is str


def _not_default(model: BaseModel, name: str) -> bool:
    """Whether ``model``'s field ``name`` holds other than its default (a
    required field has none)."""
    field = type(model).model_fields[name]
    if field.is_required():
        return True
    value = getattr(model, name)
    default = field.get_default(
        call_default_factory=True, validated_data=dict(model.__dict__)
    )
    try:
        return not (value is default or bool(value == default))
    except Exception:  # Its __eq__ cannot tell: not shown to be its default.
        return True


def _keys_of(name: str, field: FieldInfo) -> Set[str]:
    """The keys data may give the field ``name`` by: its name and aliases (an
    alias path's first)."""
    keys = {name}
    for alias in (field.alias, field.validation_alias):
        choices = alias.choices if isinstance(alias, AliasChoices) else [alias]
        for choice in choices:
            first = choice.path[0] if isinstance(choice, AliasPath) else choice
            if isinstance(first, str):
                keys.add(first)
    return keys


@functools.cache
def _excluded_if(cls: Type[BaseModel]) -> Tuple[Tuple[str, Callable[[Any], bool]], ...]:
    """The class's fields saving leaves out by their value, with the test."""
    return tuple(
        (name, field.exclude_if)
        for name, field in cls.model_fields.items()
        if field.exclude_if is not None
    )


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
    """What a manifest calls a component of class ``cls``: its
    ``manifest_kind``, else its name."""
    return str(getattr(cls, "manifest_kind", None) or cls.__name__)


def _load_class(path: Any, base: Type[C]) -> Type[C]:
    """The subclass of ``base`` that ``path`` names: an import path, as JSON
    holds it, or the class itself, as ``model_dump()`` holds it."""
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
        # Saved by their names, so loaded by them too, as by an alias.
        validate_by_name=True,
        polymorphic_serialization=True,
        # A secret read into the data being validated is not shown in errors.
        hide_input_in_errors=True,
    )

    # What a manifest calls this kind of component, for a class whose
    # subclasses are one; see to_manifest().
    manifest_kind: ClassVar[Optional[str]] = None

    # More advice for a field of this kind of component refused for holding a
    # secret, as an assistant's on its build parameters.
    secret_hint: ClassVar[str] = ""

    # The computed fields saved as its state, merged with its bases': the
    # class loads each back itself, taking it out of the data, as a
    # workflow's validator does its topics. Any other computed field follows
    # from its fields, and is left out of a dump.
    loads_computed: ClassVar[FrozenSet[str]] = frozenset()

    # Secret fields read from a variable other than their own, by field.
    _secret_env: Dict[str, str] = PrivateAttr(default_factory=dict)
    # The values secret fields were read as from their variables, by field:
    # one holding that is saved as its variable, though it changed since (one
    # given to another component by secret_reference() is the value then).
    _secrets_read: Dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls.loads_computed = frozenset().union(
            *(vars(klass).get("loads_computed", ()) for klass in cls.__mro__)
        )
        if cls.loads_computed - cls.model_computed_fields.keys():
            raise TypeError(
                f"{cls.__name__}.loads_computed names "
                f"{sorted(cls.loads_computed - cls.model_computed_fields.keys())}, "
                "which are not computed fields of it."
            )
        for name in _secret_vars(cls):
            field = cls.model_fields[name]
            constraints = [
                item for item in field.metadata if not isinstance(item, _EnvSecret)
            ]
            if constraints or not _holds_text(field.annotation):
                raise TypeError(
                    f"{cls.__name__}.{name} is a secret, which holds the text "
                    "its variable holds: type it Optional[str] (or str), with no "
                    f"constraint or other annotation, not {_named(field.annotation)}"
                    + (f" with {constraints}." if constraints else ".")
                )
        if _secret_vars(cls) and cls.model_config.get("alias_generator"):
            raise TypeError(
                f"{cls.__name__} has secret fields, which are saved by their "
                "names: it takes no alias_generator."
            )
        for base in cls.__mro__[1:]:
            if isinstance(base, type) and issubclass(base, BaseModel):
                for name in _secret_vars(base).keys() - _secret_vars(cls).keys():
                    if name in cls.model_fields:
                        raise TypeError(
                            f"{cls.__name__}.{name} is a secret, as "
                            f"{base.__name__} declares it: declare it with "
                            'env_secret("VAR") too, so it is read and saved as '
                            "one."
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

    if not TYPE_CHECKING:  # Type checkers keep checking attribute names.

        def __setattr__(self, name: str, value: Any) -> None:
            if (
                value is not None
                and not isinstance(value, str)
                and name in _secret_vars(type(self))
            ):
                raise TypeError(
                    f"{type(self).__name__}.{name} holds text, not "
                    f"{type(value).__name__}: assign the key, or give a "
                    'reference, {"env": "VAR"}, when the component is made.'
                )
            super().__setattr__(name, value)

    def __deepcopy__(self, memo: Optional[Dict[int, Any]] = None) -> Self:
        # model_copy(deep=True) gives no memo, and pydantic then copies the
        # fields and the private attributes apart: a private attribute would
        # hold other copies of the objects the fields hold.
        return super().__deepcopy__({} if memo is None else memo)

    def secret_reference(self, field: str) -> SecretInput:
        """The secret ``field``, as another component is to be given it: a
        reference to its variable, ``{"env": "VAR"}``, while it holds none
        (the variable may be set later) or that variable's value now, so the
        other reads the same key and saves as this one does; else the value,
        so the other uses the key this one does, though the variable changed
        since. An assistant builds its tools so, as ReActAgent does."""
        var, value = self.secret_variable(field), getattr(self, field)
        if var is not None and (not value or value == os.getenv(var)):
            return {"env": var}
        return value

    @overload
    def secret_value(self, field: str, *, required: Literal[True] = True) -> str: ...

    @overload
    def secret_value(self, field: str, *, required: bool) -> Optional[str]: ...

    def secret_value(self, field: str, *, required: bool = True) -> Optional[str]:
        """The secret ``field``'s value, to give a client: the one it holds,
        read from its variable when the component was made, or given in code;
        else, holding none, its variable's, read now, as it may be set after
        the component was made.

        A client given none reads its SDK's own variable, perhaps another
        account's key, so none raises, unless not ``required`` and ``field``
        reads its own variable: for a client that works without one too, as
        with Vertex AI's credentials or a local Ollama.

        Raises:
            ValueError: If it has none, naming the variable to set.
            TypeError: If it holds what is not a key, such as a reference
                assigned to it (a reference is given when the component is
                made).
        """
        if field not in _secret_vars(type(self)):
            raise ValueError(
                f"{type(self).__name__} has no field {field!r}."
                if field not in type(self).model_fields
                else f"{type(self).__name__}.{field} is not a secret field: "
                'declare it with grafi.common.manifest.env_secret("VAR").'
            )
        var, value = self.secret_variable(field), getattr(self, field)
        if value is not None and not isinstance(value, str):
            raise TypeError(
                f"{type(self).__name__}.{field} holds a {type(value).__name__}, "
                'not a key: give {"env": "VAR"} when the component is made.'
            )
        value = value or (os.getenv(var) if var else None) or None
        if value is None and (required or var != _secret_vars(type(self)).get(field)):
            where = f": set {var}" if var else ""
            raise ValueError(f"{type(self).__name__}.{field} has no value{where}.")
        return value

    def secret_variable(self, field: str) -> Optional[str]:
        """The environment variable the secret ``field`` is read from: the one
        a manifest named for it, else its own."""
        loading = _loading_secrets.get()
        if not self._secret_env and loading is not None and loading[0] is type(self):
            return loading[1].get(field, _secret_vars(type(self)).get(field))
        return self._secret_env.get(field, _secret_vars(type(self)).get(field))

    @model_serializer(mode="wrap")
    def _save(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> Dict[str, Any]:
        data = handler(self)
        cls = type(self)
        for name in cls.model_computed_fields.keys() - cls.loads_computed:
            data.pop(name, None)  # It follows from the fields dumped.
        if info.exclude_none or info.exclude_defaults:
            # A tenant's variable, read as none or the default, stays named.
            for name, var in self._secret_env.items():
                if name not in data and _dumped(name, info, cls):
                    data[name] = {"env": var}
        if not info.mode_is_json():
            # A dump is configuration: a secret read from a variable is a
            # reference to it, which loading reads again (copy a component in
            # use with model_copy(), which keeps its keys).
            for name in _secret_vars(cls).keys() & data.keys():
                data[name] = self._saved_secret(name)
            return {"class": cls, **data}
        for name in _secret_vars(cls).keys() & data.keys():
            data[name] = self._manifest_secret(name)
        _refuse_held_secrets(cls, data)
        for name in sorted(_unsaved(cls)):
            if cls.model_fields[name].is_required():
                raise save_refused(
                    ManifestError(
                        f"{cls.__name__}.{name} is never saved, but required, so "
                        "what is saved could not be loaded: give it a default."
                    )
                )
        for name, exclude_if in _excluded_if(cls):
            if exclude_if(getattr(self, name)) and _not_default(self, name):
                raise save_refused(
                    ManifestError(
                        f"{cls.__name__}.{name} is left out by its exclude_if, "
                        "holding other than its default, which loading would "
                        "give it: leave out only its default."
                    )
                )
        return {"class": import_path(cls), **data}

    def _saved_secret(self, name: str) -> Any:
        """The secret field ``name`` as a dump holds it: a reference to its
        variable while it holds none, the value it was read as (though the
        variable changed since), or the variable's value; else the value."""
        var, value = self.secret_variable(name), getattr(self, name)
        if not value:
            return {"env": var} if var is not None else None
        if var is not None and value in (self._secrets_read.get(name), os.getenv(var)):
            return {"env": var}
        return value

    def _manifest_secret(self, name: str) -> Any:
        """The secret field ``name`` as saved: a reference to its variable."""
        value = getattr(self, name)
        if env_reference(value) is not None:
            raise save_refused(
                ManifestError(
                    f"{type(self).__name__}.{name} holds a reference, {value}, "
                    "given after it was made: a reference is read when the "
                    "component is made, so give it then."
                )
            )
        saved, var = self._saved_secret(name), self.secret_variable(name)
        if saved is None or (var is not None and saved == {"env": var}):
            return saved
        source = f"the environment variable {var}" if var else "an environment variable"
        raise save_refused(
            ManifestError(
                f"{type(self).__name__}.{name} is set to a value that is not "
                f"{source}'s, and a manifest never holds a secret: give it as "
                '{"env": "VAR"}'
                + (f", or leave it unset to read {var}" if var else "")
                + (f"; {self.secret_hint}" if self.secret_hint else "")
                + " (a key passed on by secret_reference() after its variable "
                "changed is its value: build it again while the variable holds "
                "the key)."
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
        # The variables' values now, before what is built reads them, though
        # one changes meanwhile: a field holding one is read from it (a value
        # given in code equal to it counts so too).
        read: Dict[str, Optional[str]] = {}
        for name, own in _secret_vars(cls).items():
            var = env_reference(data.get(name))
            if var is None:
                if own is not None:
                    read[name] = os.getenv(own)
                continue
            if policy is not None:
                policy.check_env(var, own)
            data[name] = read[name] = os.getenv(var)
            if var != own:
                secret_env[name] = var
        token = _loading_secrets.set((cls, secret_env))
        try:
            component = handler(data)
        finally:
            _loading_secrets.reset(token)
        component._secret_env.update(secret_env)
        for name, value in read.items():
            if value is not None and getattr(component, name, None) == value:
                component._secrets_read[name] = value
        return component

    @classmethod
    def _check_manifest_rules(cls, data: Mapping[str, Any]) -> None:
        """Refuse what a manifest never holds, as saving never writes it: a
        component with an ``__init__`` of its own, a field saving leaves out,
        a secret given as a value, or a secret field given one."""
        if cls.__init__ is not Component.__init__:
            # Pydantic validates such a class by calling its __init__, which
            # would load what it holds without the manifest's rules.
            raise ManifestError(
                f"{cls.__name__} has an __init__ of its own, so it cannot be "
                "loaded from a manifest: set it up in model_post_init()."
            )
        for name in sorted(_unsaved(cls)):
            if data.keys() & _keys_of(name, cls.model_fields[name]):
                raise ManifestError(
                    f"{cls.__name__}.{name} is never saved, so a manifest does "
                    "not hold it."
                )
        _refuse_held_secrets(cls, data)
        for name, own in _secret_vars(cls).items():
            if name in data and env_reference(data[name]) is None:
                if data[name] is not None or own is not None:  # Nor null for one.
                    raise ManifestError(
                        f"{cls.__name__}.{name} is given a value, and a manifest "
                        'never holds a secret: refer to its variable, {"env": "VAR"}.'
                    )

    def to_manifest(self) -> Dict[str, Any]:
        """This component as a manifest: its JSON, in the envelope naming the
        format and its kind.

        Raises:
            ManifestError: If it cannot be saved, as when it holds a secret, or
                a value JSON cannot hold, such as a client.
        """
        try:
            spec = _dump_json(self)
        except PydanticSerializationError as error:
            raise ManifestError(
                f"{self._unsaveable()} cannot be saved: {error}. A field "
                "holding what is made at run time, such as a client, is not "
                "saved: declare it Field(exclude=True), or a PrivateAttr; make a "
                "computed field holding one a plain @property; one holding a "
                "function is typed CallableRef."
            ) from error
        return {"apiVersion": API_VERSION, "kind": kind_of(type(self)), "spec": spec}

    def _unsaveable(self, seen: FrozenSet[int] = frozenset()) -> str:
        """The innermost field that cannot be saved, as ``Class.field``, in
        this component or one it holds, not ``seen``; or its class's name, if
        none alone cannot.

        Raises:
            ManifestError: The refusal a dump of one field met, saving's own
                (such as a secret held, or a class no import reaches), which
                the dump of them all did not reach.
        """
        cls, seen = type(self), seen | {id(self)}
        for name in [*cls.model_fields, *cls.model_computed_fields]:
            if not _saves(self, include={name}):
                # One seen already is a cycle, which pydantic names.
                for inner in _components_in(getattr(self, name)):
                    if id(inner) not in seen and not _saves(inner):
                        return inner._unsaveable(seen)
                return f"{cls.__name__}.{name}"
        return cls.__name__

    @classmethod
    def from_manifest(
        cls,
        manifest: Union[Mapping[str, Any], str, bytes, "os.PathLike[str]"],
        *,
        allow_env: Collection[str] = (),
        legacy_classes: Optional[Mapping[str, Union[str, type]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Self:
        """Load the component a manifest holds, which must be one of this
        class: a dict, JSON as text or bytes, or the file a path names (a
        :class:`pathlib.Path`; a ``str`` is JSON, never a path). A component's
        JSON, ``model_dump(mode="json")``, loads too; save one to keep with
        ``to_manifest()``, which names the format's version.

        Every component in it must name its class, hold only what saving
        writes, and refer to its secrets by environment variable: each to its
        field's own, or to one ``allow_env`` names.
        ``context`` is the validation context, such as the topics a node's
        manifest names, by name: ``{"topics": {...}}``; a workflow's manifest
        holds its topics.

        A manifest saved before ``grafi/v2`` (an assistant's ``to_dict()``) is
        upgraded first. It names tool classes by their bare names: grafi's own
        are known, and ``legacy_classes`` maps others to their classes, or
        import paths, such as ``{"WeatherTool": "my_app.tools:WeatherTool"}``.

        Raises:
            ManifestError: If the manifest is not JSON of one of this class's,
                or breaks a rule above.
            OSError: If its file cannot be read.
            UntrustedImportError: If it names a class or function outside the
                trusted modules (see grafi.common.import_ref.trust_modules).
            pydantic.ValidationError: If a component's fields are invalid.
        """
        if isinstance(allow_env, (str, Mapping)):
            raise TypeError(
                "allow_env is the names of the variables the manifest may read, "
                "besides its secret fields' own: allow_env=['GITHUB_TOKEN']"
            )
        policy = ManifestPolicy(env=frozenset(allow_env))
        try:
            spec, target = cls._spec_of(manifest, legacy_classes)
            return target.model_validate(
                spec, context={**(context or {}), _POLICY: policy}
            )
        except (ManifestError, ValidationError, OSError):
            raise
        except (
            GrafiError,
            AttributeError,
            LookupError,
            TypeError,
            ValueError,
            RecursionError,
        ) as e:
            # What the data holds, malformed past what the checks name.
            raise ManifestError(f"The manifest cannot be loaded: {e!r}") from e

    @classmethod
    def _spec_of(
        cls,
        manifest: Union[Mapping[str, Any], str, bytes, "os.PathLike[str]"],
        legacy_classes: Optional[Mapping[str, Union[str, type]]],
    ) -> "tuple[Dict[str, Any], Type[Self]]":
        """A manifest's spec, and the class it is of, checked against the
        envelope before anything is built."""
        if isinstance(manifest, (str, bytes, os.PathLike)):
            manifest = _read_json(manifest)
        if not isinstance(manifest, Mapping):
            raise ManifestError(
                f"A manifest is a JSON object, not {type(manifest).__name__}."
            )
        try:  # As JSON holds it: no value of another kind.
            manifest = json.loads(json.dumps(manifest))
        except (TypeError, ValueError) as error:
            raise ManifestError(f"A manifest holds only JSON: {error}") from error
        if "apiVersion" not in manifest and is_import_path(
            str(manifest.get("class", ""))
        ):  # A component's JSON, as model_dump(mode="json") gives it.
            return dict(manifest), _load_class(manifest["class"], cls)
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


def _read_json(source: Union[str, bytes, "os.PathLike[str]"]) -> Any:
    """What JSON, as text or bytes, or the file a path names, holds."""
    path: Optional[Path] = None
    if isinstance(source, os.PathLike):
        path = Path(source)
        data: Union[str, bytes] = path.read_bytes()  # Any UTF encoding, BOM or not.
    else:
        data = source
    if isinstance(data, str):
        data = data.removeprefix("\ufeff")
    try:
        return json.loads(data)
    except ValueError as error:  # As JSONDecodeError and UnicodeDecodeError are.
        where = (
            f"The manifest file {path} is not JSON"
            if path is not None
            else "A manifest is JSON (a path is given as a pathlib.Path)"
        )
        raise ManifestError(f"{where}: {error}") from error


def _dump_json(component: "Component", **options: Any) -> Dict[str, Any]:
    """``component``'s JSON dump, with ``options``.

    Raises:
        Exception: The refusal of saving's own that the dump met, as it is.
        PydanticSerializationError: For a value JSON cannot hold.
    """
    errors: List[Exception] = []
    token = _save_errors.set(errors)
    try:
        return component.model_dump(mode="json", **options)
    except PydanticSerializationError:
        if errors:
            raise errors[0] from None
        raise
    finally:
        _save_errors.reset(token)


def _saves(component: "Component", **options: Any) -> bool:
    """Whether ``component`` dumps as JSON, with ``options``; a refusal of
    saving's own that the dump met is raised (see ``_dump_json``)."""
    try:
        _dump_json(component, **options)
        return True
    except PydanticSerializationError:
        return False


def _components_in(value: Any, seen: FrozenSet[int] = frozenset()) -> List["Component"]:
    """The components ``value`` is, or holds within it, outermost first, in
    containers not ``seen`` (a container may hold itself)."""
    if isinstance(value, Component):
        return [value]
    if not isinstance(value, (Mapping, list, tuple)) or id(value) in seen:
        return []
    items = value.values() if isinstance(value, Mapping) else value
    seen |= {id(value)}
    return [component for item in items for component in _components_in(item, seen)]


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
