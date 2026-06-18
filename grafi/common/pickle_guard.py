"""Safe-by-default guard around pickle/cloudpickle deserialization.

Deserializing a pickle/cloudpickle payload executes whatever code is embedded in
it, so loading a workflow / topic / tool manifest that originated from an
untrusted source is a remote-code-execution vector. Grafi serializes topic
conditions and user-supplied functions with cloudpickle, so this module makes
*loading* them an explicit, opt-in trust decision instead of a silent default.

Deserialization is permitted when ANY of the following is true:

* the ``GRAFI_ALLOW_PICKLE_DESERIALIZATION`` environment variable is truthy
  (``1`` / ``true`` / ``yes`` / ``on``), or
* :func:`set_pickle_deserialization_allowed` has been called with ``True``, or
* the individual call passes ``trusted=True``.

Otherwise an :class:`~grafi.common.exceptions.UnsafeDeserializationError` is
raised. This is intentionally fail-closed: a tampered manifest cannot run code
on a default deployment.
"""

import base64
from typing import Any
from typing import Optional

import cloudpickle

from grafi.common.env import env_bool
from grafi.common.exceptions import UnsafeDeserializationError

ENV_FLAG = "GRAFI_ALLOW_PICKLE_DESERIALIZATION"

# Process-wide override. ``None`` means "defer to the environment".
_override: Optional[bool] = None


def set_pickle_deserialization_allowed(allowed: Optional[bool]) -> None:
    """Set a process-wide override for pickle deserialization.

    Pass ``True``/``False`` to force the decision, or ``None`` to clear the
    override and fall back to the environment variable.
    """
    global _override
    _override = allowed


def is_pickle_deserialization_allowed() -> bool:
    """Return whether pickle deserialization is currently permitted."""
    if _override is not None:
        return _override
    return env_bool(ENV_FLAG, default=False)


def safe_pickle_loads(
    payload: bytes, *, trusted: bool = False, context: str = ""
) -> Any:
    """Deserialize a pickle/cloudpickle payload, gated by the trust policy.

    Args:
        payload: The raw pickled bytes.
        trusted: When ``True``, bypass the policy because the caller has already
            established that the data source is trusted.
        context: Optional description of what is being deserialized, surfaced in
            the error message when deserialization is refused.

    Raises:
        UnsafeDeserializationError: When deserialization is not permitted.
    """
    if not (trusted or is_pickle_deserialization_allowed()):
        where = f" while deserializing {context}" if context else ""
        raise UnsafeDeserializationError(
            message=(
                f"Refusing to deserialize pickled data{where}. Pickle/cloudpickle "
                "payloads can execute arbitrary code, so deserialization is disabled "
                "by default. Only enable it for data from a TRUSTED source: set the "
                f"{ENV_FLAG} environment variable to a truthy value, call "
                "grafi.common.pickle_guard.set_pickle_deserialization_allowed(True), "
                "or pass trusted=True at the call site."
            ),
            severity="CRITICAL",
        )
    return cloudpickle.loads(payload)


def safe_b64_pickle_loads(
    encoded: str, *, trusted: bool = False, context: str = ""
) -> Any:
    """Base64-decode then :func:`safe_pickle_loads` the result."""
    return safe_pickle_loads(
        base64.b64decode(encoded.encode("utf-8")), trusted=trusted, context=context
    )
