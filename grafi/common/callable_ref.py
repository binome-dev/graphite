"""Pickle-free (de)serialization of the callables embedded in a manifest.

Grafi manifests are JSON. Every component except the user's callables -- a
:class:`FunctionTool`'s ``function``, a topic's routing ``condition``, an
:class:`AgentCallingTool`'s ``agent_call`` -- round-trips as plain data. This
module makes the callables round-trip as data too, with **no pickle** (pickle
embeds opaque, version-fragile bytecode and executes arbitrary code on load).

A callable is serialized in one of two JSON-native forms, chosen by what it is:

* **reference** -- ``{"ref": "module:qualname"}`` for an importable, module-level
  function (e.g. a named topic predicate). Re-imported on load. Lightest option.
* **component** -- ``{"component": "module:Class", "config": {...}}`` for a
  :class:`~grafi.common.callable_component.CallableComponent` subclass. The class
  is re-imported and re-instantiated from its (validated) config. Pure data; no
  code in the manifest.

A callable that fits neither -- a lambda, an arbitrary closure, a nested
``def`` -- raises :class:`CallableSerializationError` rather than falling back to
pickle. The fix is to make it an importable function or a component.
"""

from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Union

from grafi.common.callable_component import CallableComponent
from grafi.common.import_ref import resolve_import_ref


class CallableSerializationError(ValueError):
    """Raised when a callable cannot be represented without pickle, or when a
    manifest's serialized callable cannot be reconstructed."""


def _resolve_reference(ref: str) -> Any:
    """Import the object named by ``"module:qualname"`` (see
    :func:`~grafi.common.import_ref.resolve_import_ref`), translating a malformed
    reference into this module's error type."""
    try:
        return resolve_import_ref(ref)
    except ValueError as e:
        raise CallableSerializationError(str(e)) from e


def _reference_for(fn: Callable[..., Any]) -> Optional[str]:
    """Return ``"module:qualname"`` if *fn* can be re-imported, else ``None``.

    Only stable, module-level callables qualify. Lambdas/locals (``<lambda>`` /
    ``<locals>`` in the qualname) and objects in ``__main__`` (not importable from
    a fresh process) are rejected. The candidate is resolved and compared by
    identity, so a name that no longer points at *fn* is never emitted.
    """
    module = getattr(fn, "__module__", None)
    qualname = getattr(fn, "__qualname__", None)
    if not module or not qualname or module == "__main__" or "<" in qualname:
        return None
    ref = f"{module}:{qualname}"
    try:
        return ref if _resolve_reference(ref) is fn else None
    except Exception:
        return None


def serialize_callable(fn: Callable[..., Any]) -> Dict[str, Any]:
    """Serialize a callable to a JSON-safe dict, without pickle.

    Tries, in order: a :class:`CallableComponent` (``component``), then an
    importable reference (``ref``).

    Raises:
        CallableSerializationError: If *fn* is neither -- a lambda, a closure, or
            a nested ``def``.
    """
    if isinstance(fn, CallableComponent):
        cls = type(fn)
        return {
            "component": f"{cls.__module__}:{cls.__qualname__}",
            "config": fn.model_dump(mode="json"),
        }

    ref = _reference_for(fn)
    if ref is not None:
        return {"ref": ref}

    raise CallableSerializationError(
        f"Cannot serialize callable {fn!r} without pickle. Make it an importable "
        "module-level function (serialized as a reference) or a CallableComponent "
        "subclass (serialized as config)."
    )


def deserialize_callable(
    value: Union[str, Dict[str, Any]], *, context: str = ""
) -> Callable[..., Any]:
    """Reconstruct a callable serialized by :func:`serialize_callable`.

    Args:
        value: ``{"ref": ...}`` or ``{"component": ..., "config": {...}}``.
        context: Description surfaced in error messages.

    Raises:
        CallableSerializationError: On an unknown shape, a failed reconstruction,
            or a legacy pickle payload (no longer supported -- regenerate the
            manifest).
    """
    where = f" for {context}" if context else ""

    # Legacy pickle formats: a bare base64 string, or a {"base64": ...} dict.
    if isinstance(value, str) or (isinstance(value, dict) and "base64" in value):
        raise CallableSerializationError(
            f"The manifest stores a pickle payload{where}, which is no longer "
            "supported. Regenerate the manifest with the current version "
            "(e.g. assistant.generate_manifest())."
        )

    if not isinstance(value, dict):
        raise CallableSerializationError(
            f"Cannot deserialize callable{where}: expected a dict, got "
            f"{type(value).__name__}."
        )

    if "component" in value:
        return _deserialize_component(value, where)
    if "ref" in value:
        resolved = _resolve_reference(value["ref"])
        if not callable(resolved):
            raise CallableSerializationError(
                f"Reference {value['ref']!r}{where} resolved to a non-callable "
                f"{type(resolved).__name__}."
            )
        return resolved

    raise CallableSerializationError(
        f"Cannot deserialize callable{where}: dict must contain 'ref' or "
        f"'component'; got keys {sorted(value)}."
    )


def _deserialize_component(value: Dict[str, Any], where: str) -> CallableComponent:
    cls = _resolve_reference(value["component"])
    if not (isinstance(cls, type) and issubclass(cls, CallableComponent)):
        raise CallableSerializationError(
            f"Component {value['component']!r}{where} is not a CallableComponent "
            "subclass."
        )
    try:
        return cls(**value.get("config", {}))
    except Exception as e:
        # Surface invalid/incompatible config as this module's error type rather
        # than leaking a raw pydantic ValidationError.
        raise CallableSerializationError(
            f"Failed to build component {value['component']!r}{where} from its "
            f"config: {e}"
        ) from e
