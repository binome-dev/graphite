"""Warnings for code written for grafi 0.0.36 and earlier."""

import inspect
import warnings
from typing import Callable
from typing import Mapping
from typing import Optional


def _owner(klass: type, name: str) -> Optional[type]:
    """The class in ``klass``'s MRO that defines ``name``, if any."""
    return next((k for k in klass.__mro__ if name in vars(k)), None)


def warn_never_called(
    cls: type, base: type, removed_of: Callable[[type], Mapping[str, str]]
) -> None:
    """Warn, where it is written, of each method ``removed_of(cls)`` names
    that ``cls`` gets from elsewhere than ``base`` (its own or a mixin's),
    unless a parent of ``cls`` deriving from ``base`` has it from the same
    class and was checked for it, so was warned of it then: grafi called it
    in 0.0.36 and earlier, and no longer does; the mapping gives what does
    its work now."""
    for name, instead in removed_of(cls).items():
        owner = _owner(cls, name)
        if owner is None or owner is base:
            continue
        if any(
            issubclass(parent, base)
            and _owner(parent, name) is owner
            and name in removed_of(parent)
            for parent in cls.__bases__
        ):
            continue
        try:
            code = getattr(inspect.unwrap(vars(owner)[name]), "__code__", None)
        except ValueError:  # Wrappers that wrap each other.
            code = None
        warnings.warn_explicit(
            f"{cls.__name__}.{name}() is never called by grafi, which called it "
            f"in 0.0.36 and earlier: {instead}",
            UserWarning,
            filename=code.co_filename if code else str(cls.__module__),
            lineno=code.co_firstlineno if code else 0,
            module=cls.__module__,
        )
