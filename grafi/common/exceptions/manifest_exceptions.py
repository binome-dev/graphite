"""
Manifest exception classes: saving and loading components as data.
"""

from grafi.common.exceptions.base import GrafiError


class ManifestError(GrafiError):
    """A component cannot be saved as, or loaded from, a manifest.

    ``Component.to_manifest`` raises it as it is; ``model_dump`` raises
    pydantic's ``PydanticSerializationError`` instead, which holds its message.
    """


class UntrustedImportError(ManifestError, ImportError):
    """A manifest names a class or function outside the trusted modules."""


class CallableSerializationError(ManifestError):
    """A function cannot be saved without pickle, as a lambda or a nested
    function cannot, or a saved one cannot be loaded."""
