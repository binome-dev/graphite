"""Shared helpers for reading boolean configuration from the environment."""

import os

# Canonical spellings for boolean env values.
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off", ""})


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment.

    Unset -> ``default``; a recognised truthy/falsy spelling -> that value;
    anything unrecognised -> ``default`` (so a typo never silently flips intent).
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default
