from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from anthropic import NOT_GIVEN
from anthropic.types.text_block import TextBlock

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.message import Message
from grafi.tools.llms.impl.claude_tool import ClaudeTool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def claude_instance() -> ClaudeTool:
    return ClaudeTool(
        system_message="dummy system message",
        name="ClaudeTool",
        api_key="test_api_key",
        model="claude-3-5-haiku-20241022",
        max_tokens=2048,
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(claude_instance):
    assert claude_instance.api_key == "test_api_key"
    assert claude_instance.model == "claude-3-5-haiku-20241022"
    assert claude_instance.system_message == "dummy system message"
    assert claude_instance.max_tokens == 2048


# --------------------------------------------------------------------------- #
#  execute() – simple assistant response
# --------------------------------------------------------------------------- #
def test_execute_simple_response(monkeypatch, claude_instance, execution_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    # fake AnthropicMessage: .content is list of blocks that each have .text
    fake_block = Mock(TextBlock)
    fake_block.text = "Hello, world!"
    fake_block.role = "assistant"
    fake_response = Mock(content=[fake_block])

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=fake_response)

    # patch Anthropic constructor
    monkeypatch.setattr(cl_module, "Anthropic", MagicMock(return_value=mock_client))

    input_data = [Message(role="user", content="Say hello")]
    result = claude_instance.execute(execution_context, input_data)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # verify constructor args
    cl_module.Anthropic.assert_called_once_with(api_key="test_api_key")

    # verify create() called with right kwargs
    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["model"] == "claude-3-5-haiku-20241022"
    assert kwargs["max_tokens"] == 2048
    assert kwargs["messages"][0] == {
        "role": "system",
        "content": "dummy system message",
    }
    assert kwargs["messages"][1]["role"] == "user"
    assert kwargs["messages"][1]["content"] == "Say hello"
    # no tools in this call
    assert kwargs["tools"] == NOT_GIVEN


# --------------------------------------------------------------------------- #
#  execute() – function / tool call path
# --------------------------------------------------------------------------- #
def test_execute_function_call(monkeypatch, claude_instance, execution_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    fake_block = Mock()
    fake_block.text = ""  # content empty when tool chosen
    fake_response = Mock(content=[fake_block])

    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=fake_response)
    monkeypatch.setattr(cl_module, "Anthropic", MagicMock(return_value=mock_client))

    tools = [
        FunctionSpec(
            name="get_weather",
            description="Get weather",
            parameters=ParametersSchema(
                type="object",
                properties={"location": ParameterSchema(type="string")},
            ),
        ).to_openai_tool()  # same schema shape; Claude only needs .function
    ]

    msgs = [Message(role="user", content="Weather?", tools=tools)]

    claude_instance.execute(execution_context, msgs)

    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["tools"] is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
def test_execute_api_error(monkeypatch, claude_instance, execution_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Boom")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _raise
    monkeypatch.setattr(cl_module, "Anthropic", MagicMock(return_value=mock_client))

    with pytest.raises(RuntimeError, match="Anthropic API error: Boom"):
        claude_instance.execute(execution_context, [Message(role="user", content="Hi")])


# --------------------------------------------------------------------------- #
#  prepare_api_input helper
# --------------------------------------------------------------------------- #
def test_prepare_api_input(claude_instance):
    msgs = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi."),
    ]
    api_messages, api_tools = claude_instance.prepare_api_input(msgs)

    # first element must be dummy system instruction from instance
    assert api_messages[0]["content"] == "dummy system message"
    assert api_messages[-1]["role"] == "assistant"
    assert api_tools == NOT_GIVEN


# --------------------------------------------------------------------------- #
#  to_dict                                                                     #
# --------------------------------------------------------------------------- #
def test_to_dict(claude_instance):
    d = claude_instance.to_dict()
    assert d["name"] == "ClaudeTool"
    assert d["type"] == "ClaudeTool"
    assert d["api_key"] == "****************"
    assert d["model"] == "claude-3-5-haiku-20241022"
