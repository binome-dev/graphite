"""Resolve an object from a ``"module:qualname"`` import reference, from trusted
modules only.

Manifests name classes and functions by import path, and loading one imports
them. A manifest is data, which may come from anywhere, so only modules you
trust are imported: grafi's own, and those you add with :func:`trust_modules`.
Nothing is imported before that check, so an untrusted module's import-time code
never runs. A name reaches only a class, or a function, of a trusted module,
through classes only, so it cannot reach what a trusted module imported (``os``
in ``"grafi.x:os.system"``), nor any value, such as a setting.
"""

import importlib
import inspect
import re
import sys
import threading
from typing import Any
from typing import FrozenSet
from typing import Optional

from grafi.common.exceptions.manifest_exceptions import ManifestError
from grafi.common.exceptions.manifest_exceptions import UntrustedImportError

__all__ = [
    "UntrustedImportError",
    "is_import_path",
    "is_trusted",
    "reference_to",
    "resolve_import_ref",
    "trust_modules",
]

# An import path, "module:Qualname".
_IMPORT_PATH = re.compile(r"[A-Za-z_][\w.]*:[A-Za-z_][\w.]*")


def is_import_path(text: str) -> bool:
    """Whether ``text`` has the form of an import path, ``"module:Qualname"``."""
    return bool(_IMPORT_PATH.fullmatch(text))


# Replaced whole, never changed, so it is read without the lock.
_trusted: FrozenSet[str] = frozenset({"grafi"})
_lock = threading.Lock()


def trust_modules(*modules: str) -> None:
    """Let manifests load classes and functions from ``modules`` and their
    submodules, such as ``trust_modules("my_app")`` for your own tools. Call it
    at startup, before loading a manifest."""
    global _trusted
    with _lock:
        _trusted = _trusted | frozenset(modules)


def is_trusted(module: str) -> bool:
    """Whether manifests may import ``module``."""
    return any(module == name or module.startswith(f"{name}.") for name in _trusted)


def reference_to(obj: Any) -> Optional[str]:
    """``"module:qualname"`` for ``obj`` if that imports it back from a fresh
    process, else None: a lambda or a local, or what ``__main__`` defines, has
    none. It is looked up in its module, already imported, and compared by
    identity. Saving needs no trust: loading checks it."""
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if not module or not qualname or module == "__main__" or "<" in qualname:
        return None
    if not (inspect.isclass(obj) or inspect.isfunction(obj)):
        return None  # Loading names only these (see resolve_import_ref).
    found: Any = sys.modules.get(module)
    for attr in qualname.split("."):
        found = getattr(found, attr, None)
    return f"{module}:{qualname}" if found is obj else None


def resolve_import_ref(ref: str) -> Any:
    """Import and return the object named by ``"module:qualname"``, from a
    trusted module. A dotted ``qualname`` resolves attributes nested on a class
    too (e.g. ``"pkg.mod:Outer.method"``).

    Raises:
        ManifestError: If *ref* is not of the form ``"module:qualname"``, or
            names nothing that can be imported.
        UntrustedImportError: If it names something outside the trusted modules
            (see trust_modules()).
    """
    module_path, sep, qualname = ref.partition(":")
    if not sep or not module_path or not qualname:
        raise ManifestError(
            f'{ref!r} is not an import path, which is "module:Qualname".'
        )
    if any(part.startswith("__") for part in module_path.split(".")):
        raise UntrustedImportError(
            f"{ref!r} names a special module, such as a package's __main__."
        )
    if not is_trusted(module_path):
        package = module_path.split(".")[0]
        hint = (
            "do not trust the standard library: a manifest must not name it"
            if package in sys.stdlib_module_names
            else "if it is your code, trust it before loading, with "
            f"grafi.common.import_ref.trust_modules({package!r})"
        )
        raise UntrustedImportError(f"{ref!r} is outside the trusted modules: {hint}.")
    attrs = qualname.split(".")
    for attr in attrs:
        if attr.startswith("__") and attr.endswith("__"):
            raise UntrustedImportError(f"{ref!r} names a special attribute, {attr}")
    try:
        obj: Any = importlib.import_module(module_path)
    except ImportError as error:
        raise ManifestError(f"Cannot import {ref!r}: {error}") from error
    for at, attr in enumerate(attrs, start=1):
        try:
            obj = inspect.getattr_static(obj, attr)  # Runs no property.
        except AttributeError as error:
            raise ManifestError(f"Cannot import {ref!r}: {error}") from error
        if isinstance(obj, classmethod):
            raise UntrustedImportError(
                f"{ref!r} names a classmethod; name a function, or a staticmethod."
            )
        if isinstance(obj, staticmethod):
            obj = obj.__func__
        # Named by its type only, never its text, which may hold a secret.
        if not (inspect.isclass(obj) or (at == len(attrs) and inspect.isfunction(obj))):
            raise UntrustedImportError(
                f"{ref!r} reaches {type(obj).__qualname__!r} at {attr!r}: a name "
                "reaches a class or a function, through classes only."
            )
        owner = getattr(obj, "__module__", None)
        if not (isinstance(owner, str) and is_trusted(owner)):
            raise UntrustedImportError(
                f"{ref!r} names what {owner!r} defines, which is not trusted."
            )
    return obj
