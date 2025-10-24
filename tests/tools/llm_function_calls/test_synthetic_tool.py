import json
import uuid
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.synthetic_tool import SyntheticTool


class WeatherInput(BaseModel):
    location: str
    units: str = "celsius"


class WeatherOutput(BaseModel):
    temperature: float
    conditions: str
    location: str


@pytest.fixture
def synthetic_tool() -> SyntheticTool:
    return (
        SyntheticTool.builder()
        .tool_name("get_weather")
        .description("Get the current weather for a location")
        .input_model(WeatherInput)
        .output_model(WeatherOutput)
        .model("gpt-4o-mini")
        .openai_api_key("test_api_key")
        .build()
    )


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_synthetic_tool_initialization(synthetic_tool):
    """Test that SyntheticTool initializes correctly with all properties."""
    assert synthetic_tool.name == "get_weather"
    assert synthetic_tool.type == "SyntheticTool"
    assert synthetic_tool.tool_name == "get_weather"
    assert synthetic_tool.description == "Get the current weather for a location"
    assert synthetic_tool.model == "gpt-4o-mini"
    assert synthetic_tool.openai_api_key == "test_api_key"
    assert synthetic_tool.input_model == WeatherInput
    assert synthetic_tool.output_model == WeatherOutput


def test_input_schema_property(synthetic_tool):
    """Test that input_schema property returns correct JSON schema."""
    schema = synthetic_tool.input_schema
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "location" in schema["properties"]
    assert "units" in schema["properties"]
    assert schema["properties"]["location"]["type"] == "string"


def test_output_schema_property(synthetic_tool):
    """Test that output_schema property returns correct JSON schema."""
    schema = synthetic_tool.output_schema
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "temperature" in schema["properties"]
    assert "conditions" in schema["properties"]
    assert "location" in schema["properties"]


def test_get_function_specs(synthetic_tool):
    """Test that function specs are correctly generated from input model."""
    specs = synthetic_tool.get_function_specs()
    assert len(specs) == 1
    assert specs[0].name == "get_weather"
    assert specs[0].description == "Get the current weather for a location"
    assert specs[0].parameters.type == "object"
    assert "location" in specs[0].parameters.properties
    assert "units" in specs[0].parameters.properties


def test_make_prompt(synthetic_tool):
    """Test that _make_prompt generates correct prompt structure."""
    user_input = {"location": "San Francisco", "units": "celsius"}
    prompt = synthetic_tool._make_prompt(user_input)

    assert "get_weather" in prompt
    assert "Get the current weather for a location" in prompt
    assert "INPUT SCHEMA:" in prompt
    assert "OUTPUT SCHEMA:" in prompt
    assert "San Francisco" in prompt
    assert "celsius" in prompt


@pytest.mark.asyncio
async def test_invoke_successful(synthetic_tool, invoke_context):
    """Test successful invocation with mocked LLM response."""
    mock_parsed_response = WeatherOutput(
        temperature=22.5, conditions="Sunny", location="San Francisco"
    )

    mock_message = Mock()
    mock_message.parsed = mock_parsed_response

    mock_choice = Mock()
    mock_choice.message = mock_message

    mock_completion = Mock()
    mock_completion.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)

    with patch(
        "grafi.tools.function_calls.impl.synthetic_tool.AsyncOpenAI",
        return_value=mock_client,
    ):
        input_data = [
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco", "units": "celsius"}',
                        },
                    }
                ],
            )
        ]

        result = []
        async for msg in synthetic_tool.invoke(invoke_context, input_data):
            result.extend(msg)

        assert len(result) == 1
        assert result[0].role == "tool"
        assert result[0].tool_call_id == "call_123"

        response_data = json.loads(result[0].content)
        assert response_data["temperature"] == 22.5
        assert response_data["conditions"] == "Sunny"
        assert response_data["location"] == "San Francisco"


@pytest.mark.asyncio
async def test_invoke_no_tool_calls(synthetic_tool, invoke_context):
    """Test that invoke raises ValueError when no tool_calls are present."""
    input_data = [Message(role="assistant", content="No tool calls here")]

    with pytest.raises(ValueError, match="No tool_calls found"):
        async for msg in synthetic_tool.invoke(invoke_context, input_data):
            pass


@pytest.mark.asyncio
async def test_invoke_invalud_function_name(synthetic_tool, invoke_context):
    """Test that invoke skips tool calls with non-matching function names."""
    input_data = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "wrong_function",
                        "arguments": '{"location": "San Francisco"}',
                    },
                }
            ],
        )
    ]

    result = []
    async for msg in synthetic_tool.invoke(invoke_context, input_data):
        result.extend(msg)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_invoke_multiple_tool_calls(synthetic_tool, invoke_context):
    """Test invoke with multiple tool calls."""
    mock_parsed_response = WeatherOutput(
        temperature=22.5, conditions="Sunny", location="San Francisco"
    )

    mock_message = Mock()
    mock_message.parsed = mock_parsed_response

    mock_choice = Mock()
    mock_choice.message = mock_message

    mock_completion = Mock()
    mock_completion.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_completion)

    with patch(
        "grafi.tools.function_calls.impl.synthetic_tool.AsyncOpenAI",
        return_value=mock_client,
    ):
        input_data = [
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco"}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "New York"}',
                        },
                    },
                ],
            )
        ]

        result = []
        async for msg in synthetic_tool.invoke(invoke_context, input_data):
            result.extend(msg)

        assert len(result) == 2
        assert result[0].tool_call_id == "call_1"
        assert result[1].tool_call_id == "call_2"


def test_to_messages(synthetic_tool):
    """Test to_messages creates proper Message objects."""
    response = '{"temperature": 22.5, "conditions": "Sunny", "location": "SF"}'
    result = synthetic_tool.to_messages(response=response, tool_call_id="call_123")

    assert len(result) == 1
    assert result[0].role == "tool"
    assert result[0].content == response
    assert result[0].tool_call_id == "call_123"


def test_to_dict(synthetic_tool):
    """Test serialization to dictionary."""
    result = synthetic_tool.to_dict()

    assert isinstance(result, dict)
    assert result["tool_name"] == "get_weather"
    assert result["description"] == "Get the current weather for a location"
    assert result["model"] == "gpt-4o-mini"
    assert "input_schema" in result
    assert "output_schema" in result
    assert isinstance(result["input_schema"], dict)
    assert isinstance(result["output_schema"], dict)


@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "SyntheticTool",
        "tool_id": "test-id",
        "name": "get_weather",
        "type": "SyntheticTool",
        "oi_span_type": "TOOL",
        "tool_name": "get_weather",
        "description": "Get weather data",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "model": "gpt-4o-mini",
        "openai_api_key": "test_key",
    }

    tool = await SyntheticTool.from_dict(data)

    assert isinstance(tool, SyntheticTool)
    assert tool.tool_name == "get_weather"
    assert tool.description == "Get weather data"
    assert tool.model == "gpt-4o-mini"
    # Note: the deserialized tool will have dict schemas, not Pydantic models
    # This means it can't actually invoke the LLM without re-setting the models


def test_field_validator_rejects_invalid_input_model():
    """Test that field validator rejects invalid input_model at initialization."""
    with pytest.raises(
        ValueError, match="input_model must be a Pydantic BaseModel class"
    ):
        SyntheticTool.builder().tool_name("test").input_model(123).build()


def test_field_validator_rejects_invalid_output_model():
    """Test that field validator rejects invalid output_model at initialization."""
    with pytest.raises(
        ValueError, match="output_model must be a Pydantic BaseModel class"
    ):
        SyntheticTool.builder().tool_name("test").output_model("invalid_string").build()


def test_field_validator_rejects_model_instance():
    """Test that field validator rejects Pydantic model instances (not classes)."""
    instance = WeatherInput(location="SF")

    with pytest.raises(
        ValueError, match="input_model must be a Pydantic BaseModel class"
    ):
        SyntheticTool.builder().tool_name("test").input_model(instance).build()


def test_field_validator_accepts_valid_pydantic_class():
    """Test that field validator accepts valid Pydantic model classes."""
    tool = (
        SyntheticTool.builder()
        .tool_name("test")
        .input_model(WeatherInput)
        .output_model(WeatherOutput)
        .model("gpt-4")
        .openai_api_key("key")
        .build()
    )

    assert tool.input_model == WeatherInput
    assert tool.output_model == WeatherOutput


def test_field_validator_accepts_dict_schema():
    """Test that field validator accepts dict schemas (for flexible schema definition)."""
    tool = (
        SyntheticTool.builder()
        .tool_name("test")
        .input_model({"type": "object", "properties": {}})
        .output_model({"type": "object", "properties": {}})
        .model("gpt-4")
        .openai_api_key("key")
        .build()
    )

    assert isinstance(tool.input_model, dict)
    assert isinstance(tool.output_model, dict)


@pytest.mark.asyncio
async def test_invoke_with_json_schema_output(invoke_context):
    """Test invocation with JSON schema output model (not Pydantic)."""
    json_output_schema = {
        "type": "object",
        "properties": {"result": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["result", "confidence"],
        "additionalProperties": False,
    }

    tool = (
        SyntheticTool.builder()
        .tool_name("test_json_tool")
        .description("Test tool with JSON schema")
        .input_model({"type": "object", "properties": {"query": {"type": "string"}}})
        .output_model(json_output_schema)
        .model("gpt-4o-mini")
        .openai_api_key("test_key")
        .build()
    )

    # Mock the OpenAI response for JSON schema mode
    mock_response = json.dumps({"result": "test result", "confidence": 0.95})

    mock_message = Mock()
    mock_message.content = mock_response

    mock_choice = Mock()
    mock_choice.message = mock_message

    mock_completion = Mock()
    mock_completion.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

    with patch(
        "grafi.tools.function_calls.impl.synthetic_tool.AsyncOpenAI",
        return_value=mock_client,
    ):
        input_data = [
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "test_json_tool",
                            "arguments": '{"query": "test"}',
                        },
                    }
                ],
            )
        ]

        result = []
        async for msg in tool.invoke(invoke_context, input_data):
            result.extend(msg)

        # Verify the tool was invoked
        assert len(result) == 1
        assert result[0].role == "tool"
        assert result[0].tool_call_id == "call_123"

        # Verify response content
        response_data = json.loads(result[0].content)
        assert response_data["result"] == "test result"
        assert response_data["confidence"] == 0.95

        # Verify OpenAI was called with JSON schema mode (not parse)
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]

        # Check that response_format uses json_schema mode
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["response_format"]["json_schema"]["strict"] is True
        assert (
            call_kwargs["response_format"]["json_schema"]["name"]
            == "test_json_tool_output"
        )
        assert (
            call_kwargs["response_format"]["json_schema"]["schema"]
            == json_output_schema
        )


def test_mixed_pydantic_and_json_schema():
    """Test tool with Pydantic input and JSON schema output."""
    json_output_schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    tool = (
        SyntheticTool.builder()
        .tool_name("mixed_tool")
        .description("Tool with mixed types")
        .input_model(WeatherInput)  # Pydantic
        .output_model(json_output_schema)  # JSON schema
        .model("gpt-4")
        .openai_api_key("key")
        .build()
    )

    assert tool.input_model == WeatherInput
    assert isinstance(tool.output_model, dict)
    assert tool.output_model == json_output_schema
