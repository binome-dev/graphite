"""Callables saved as data in a manifest, without pickle.

A component's field holding a function -- a :class:`FunctionTool`'s
``function``, a route's ``when``, an :class:`AgentCallingTool`'s
``agent_call`` -- is typed :data:`CallableRef`, which saves it as data, in one
of two forms, chosen by what it is:

* **reference** -- ``{"ref": "module:qualname"}`` for an importable, module-level
  function (e.g. a named route predicate). Re-imported on load.
* **component** -- a :class:`~grafi.common.callable_component.CallableComponent`
  is saved as any component is, ``{"class": "module:Class", ...its fields}``,
  and loaded back from its validated fields. Pure data; no code in the manifest.

A callable that fits neither -- a lambda, an arbitrary closure, a nested
``def`` -- raises :class:`CallableSerializationError` rather than falling back to
pickle. The fix is to make it an importable function or a component.

Loading imports only from trusted modules (see
:func:`grafi.common.import_ref.trust_modules`). Of grafi's own functions, a
manifest names only its route predicates, in ``grafi.nodes.conditions``: grafi
has other functions, which no manifest should call.
"""

from typing import Annotated
from typing import Any
from typing import Callable
from typing import Dict
from typing import Mapping
from typing import Optional

from pydantic import PlainSerializer
from pydantic import ValidationInfo
from pydantic import ValidatorFunctionWrapHandler
from pydantic import WrapValidator

from grafi.common.callable_component import CallableComponent
from grafi.common.import_ref import UntrustedImportError
from grafi.common.import_ref import reference_to
from grafi.common.import_ref import resolve_import_ref
from grafi.common.manifest import ManifestError
from grafi.common.manifest import save_refused

__all__ = [
    "CallableRef",
    "CallableSerializationError",
    "deserialize_callable",
    "serialize_callable",
]

# grafi's modules whose functions a manifest may name.
_GRAFI_FUNCTIONS = frozenset({"grafi.nodes.conditions"})


class CallableSerializationError(ManifestError):
    """Raised when a callable cannot be represented without pickle, or when a
    manifest's serialized callable cannot be reconstructed."""


def _resolve_reference(ref: str) -> Any:
    """The function ``"module:qualname"`` names (see
    :func:`~grafi.common.import_ref.resolve_import_ref`), unless it is a grafi
    function a manifest may not name."""
    _refuse_grafi(ref, ref.partition(":")[0])  # Before importing anything.
    resolved = resolve_import_ref(ref)
    _refuse_grafi(ref, getattr(resolved, "__module__", ""))  # Wherever named.
    return resolved


def _refuse_grafi(ref: str, module: str) -> None:
    """Refuse a function of grafi's ``module`` a manifest may not name."""
    if module.split(".")[0] == "grafi" and module not in _GRAFI_FUNCTIONS:
        raise UntrustedImportError(
            f"{ref!r} is a grafi function a manifest may not name; it names "
            f"those in {', '.join(sorted(_GRAFI_FUNCTIONS))}."
        )


def serialize_callable(fn: Callable[..., Any]) -> Dict[str, Any]:
    """A callable as data, without pickle: a :class:`CallableComponent` as its
    JSON, anything else as a reference to it.

    Raises:
        CallableSerializationError: If *fn* is neither -- a lambda, a closure, or
            a nested ``def``.
    """
    if isinstance(fn, CallableComponent):
        return fn.model_dump(mode="json")
    ref = reference_to(fn)
    if ref is not None:
        return {"ref": ref}
    raise save_refused(
        CallableSerializationError(
            f"Cannot serialize callable {_name(fn)} without pickle. Make it an "
            "importable module-level function (serialized as a reference) or a "
            "CallableComponent subclass (serialized as its fields)."
        )
    )


def _name(fn: Callable[..., Any]) -> str:
    """What to call ``fn`` in a message: never its repr, which may show
    arguments bound to it, such as a key."""
    return str(getattr(fn, "__qualname__", type(fn).__qualname__))


def deserialize_callable(
    value: Any, context: Optional[Dict[str, Any]] = None
) -> Callable[..., Any]:
    """Reconstruct a callable serialized by :func:`serialize_callable`, in the
    validation ``context``.

    Raises:
        CallableSerializationError: On a value of another shape, such as one a
            grafi before v2 saved (regenerate the manifest).
        UntrustedImportError: If it names a function outside the trusted
            modules.
    """
    if isinstance(value, Mapping) and "class" in value:
        return CallableComponent.model_validate(value, context=context)
    if isinstance(value, Mapping) and set(value) == {"ref"}:
        return _resolve_reference(str(value["ref"]))  # A class or a function.
    if isinstance(value, str) and ":" in value:
        raise CallableSerializationError(
            f'A function is saved as {{"ref": {value!r}}}, not as {value!r}.'
        )
    raise CallableSerializationError(
        f'Cannot load a callable from {value!r}: expected {{"ref": ...}} or a '
        "CallableComponent. A manifest saved by a grafi before v2 is loaded with "
        "Component.from_manifest(), which upgrades it."
    )


def _load_callable(
    value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
) -> Any:
    if not callable(value):
        value = deserialize_callable(value, info.context)
    return handler(value)


# A field holding a function, saved as its reference or as the component it is
# (see serialize_callable) and loaded back from it.
CallableRef = Annotated[
    Callable[..., Any],
    PlainSerializer(serialize_callable, return_type=Dict[str, Any], when_used="json"),
    WrapValidator(_load_callable),
]
