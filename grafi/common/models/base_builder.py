# grafi/builder_core.py
from __future__ import annotations

from typing import Generic
from typing import TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class BaseBuilder(Generic[T]):
    """Generic builder that can build *any* Pydantic model."""

    _obj: T

    def __init__(self, cls: type[T]) -> None:
        self._obj = cls.model_construct()

    # ── generic helpers ────────────────────────────────────────────

    def build(self) -> T:
        """Return the fully configured product."""
        return self._obj
