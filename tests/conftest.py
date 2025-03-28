import pytest

from grafi.common.models.execution_context import ExecutionContext


@pytest.fixture
def execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )
