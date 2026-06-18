import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.pickle_guard import set_pickle_deserialization_allowed

# The unit-test suite deserializes topics/tools it created itself (a trusted
# source), so enable pickle-based deserialization process-wide for tests.
# Production code is fail-closed by default; see grafi.common.pickle_guard.
set_pickle_deserialization_allowed(True)


@pytest.fixture
def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )
