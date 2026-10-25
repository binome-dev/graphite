"""A command passes its tool's output on only as the tool's messages."""

from typing import Any

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.command import Command
from grafi.tools.tool import Tool


class ReturnsOneMessage(Tool):
    """A tool, not recorded, returning a message, not a list of them."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Any:
        return Message(role="assistant", content="hi")


@pytest.mark.asyncio
async def test_a_tools_output_that_is_not_its_messages_is_refused(
    invoke_context: InvokeContext,
) -> None:
    command = Command.for_tool(ReturnsOneMessage())

    with pytest.raises(TypeError, match="returns its output as a list of messages"):
        await command.invoke(invoke_context, [])
