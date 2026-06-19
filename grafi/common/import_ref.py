"""Resolve an object from a ``"module:qualname"`` import reference.

Shared by the manifest (de)serialization paths -- callable references in
:mod:`grafi.common.callable_ref` and tool classes in
:mod:`grafi.tools.tool_factory` -- so the import logic lives in exactly one place.
"""

import importlib
from typing import Any


def resolve_import_ref(ref: str) -> Any:
    """Import and return the object named by ``"module:qualname"``.

    Walks a dotted ``qualname`` so attributes nested on a class resolve too
    (e.g. ``"pkg.mod:Outer.method"``).

    Raises:
        ValueError: If *ref* is not of the form ``"module:qualname"``.
    """
    module_path, sep, qualname = ref.partition(":")
    if not sep or not module_path or not qualname:
        raise ValueError(f"Malformed import reference: {ref!r}")
    obj: Any = importlib.import_module(module_path)
    for attr in qualname.split("."):
        obj = getattr(obj, attr)
    return obj
