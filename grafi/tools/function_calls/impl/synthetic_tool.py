import inspect
import json
from typing import Any, AsyncGenerator, Dict, List

from openai import OpenAIError
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel, field_validator

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.models.function_spec import FunctionSpec, ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message, Messages
from grafi.tools.function_calls.function_call_tool import (
    FunctionCallTool,
    FunctionCallToolBuilder,
)

try:
    from openai import AsyncOpenAI
except ImportError:
    raise ImportError(
        "`openai` not installed. Please install using `pip install openai`"
    )

class SyntheticTool(FunctionCallTool):
    name: str = "SyntheticTool"
    type: str = "SyntheticTool"
    tool_name: str = ""
    description: str = ""
    input_model: Any = ""
    output_model: Any = ""
    model: str = ""
    openai_api_key: str = ""
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    @field_validator("input_model", "output_model")
    @classmethod
    def validate_pydantic_model_or_schema(cls, v: Any, info) -> Any:
        """
        Validate that input_model and output_model are either:
        - A Pydantic BaseModel class (not instance) - for type-safe Python usage
        - A JSON schema dict - for flexible schema definition
        - An empty string (for optional models)

        Both Pydantic models and JSON schemas are fully supported for LLM invocation
        with strict validation enabled.

        Args:
            v: The value to validate
            info: Pydantic validation info containing field name

        Returns:
            The validated value

        Raises:
            ValueError: If the value is not a valid type (e.g., int, str, instances)
        """
        if v == "":
            return v

        if isinstance(v, dict):
            return v

        if inspect.isclass(v) and issubclass(v, BaseModel):
            return v

        field_name = info.field_name
        raise ValueError(
            f"{field_name} must be a Pydantic BaseModel class, "
            f"a dict schema, or an empty string. "
            f"Got: {type(v).__name__}"
        )

    def model_post_init(self, _context: Any) -> None:
        if self.input_model:
            # Handle both dict schemas and Pydantic models
            if isinstance(self.input_model, dict):
                input_schema = self.input_model
            else:
                input_schema = self.input_model.model_json_schema()

            self.function_specs.append(
                FunctionSpec(
                    name=self.tool_name,
                    description=self.description,
                    parameters=ParametersSchema(**input_schema),
                )
            )

    @property
    def input_schema(self) -> Dict[str, Any]:
        """Get input schema from Pydantic model."""
        if self.input_model:
            if isinstance(self.input_model, dict):
                return self.input_model
            return self.input_model.model_json_schema()
        return {}

    @property
    def output_schema(self) -> Dict[str, Any]:
        """Get output schema from Pydantic model."""
        if self.output_model:
            if isinstance(self.output_model, dict):
                return self.output_model
            return self.output_model.model_json_schema()
        return {}

    @classmethod
    def builder(cls) -> "SyntheticToolBuilder":
        """
        Return a builder for SyntheticTool.
        This method allows for the construction of an SyntheticTool instance with specified parameters.
        """
        return SyntheticToolBuilder(cls)

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages,
    ) -> AsyncGenerator[Messages, None]:
        """
        Invokes the synthetic tool by processing incoming tool calls and generating
        LLM-based responses for each matching invocation.

        Args:
            invoke_context (InvokeContext): The context for this invocation.
            input_data (Messages): A list of incoming messages that may contain tool calls.

        Yields:
            AsyncGenerator[Messages, None]: A stream of messages representing the
            responses from the LLM for each valid tool call.

        Raises:
            ValueError: If no tool_calls are found in the input data.
        """
        input_msg = input_data[0]
        if input_msg.tool_calls is None:
            raise ValueError("No tool_calls found for SyntheticTool invocation.")

        messages: List[Message] = []

        for tool_call in input_msg.tool_calls:
            if tool_call.function.name != self.tool_name:
                continue

            args = json.loads(tool_call.function.arguments)
            prompt = self._make_prompt(args)
            response = await self._call_llm(prompt)
            messages.extend(
                self.to_messages(response=response, tool_call_id=tool_call.id)
            )

        yield messages

    def _make_prompt(self, user_input: Dict[str, Any]) -> str:
        """Builds the synthetic execution prompt."""
        return f"""
            You are a synthetic tool named "{self.tool_name}".
            Description: {self.description}

            INPUT SCHEMA:
            {json.dumps(self.input_schema, indent=2)}

            OUTPUT SCHEMA:
            {json.dumps(self.output_schema, indent=2)}

            USER INPUT:
            {json.dumps(user_input, indent=2)}

            Return ONLY a JSON object that strictly conforms to the OUTPUT schema.
        """
    
    @staticmethod
    def ensure_strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively ensure schema is compatible with OpenAI strict mode.

        Adds 'additionalProperties': false to all objects, which is required
        for OpenAI's structured outputs strict mode.

        Args:
            schema: JSON schema dict

        Returns:
            Modified schema with strict mode requirements
        """
        schema = schema.copy()

        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            if "properties" in schema:
                schema["properties"] = {
                    k: SyntheticTool.ensure_strict_schema(v)
                    for k, v in schema["properties"].items()
                }
        elif schema.get("type") == "array":
            if "items" in schema:
                schema["items"] = SyntheticTool.ensure_strict_schema(schema["items"])

        return schema

    async def _call_llm(self, prompt: str) -> str:
        """
        Calls OpenAI with structured output.
        Supports both Pydantic models and JSON schemas.
        """
        try:
            if not self.output_model:
                raise ValueError("output_model must be set to call LLM")

            client = AsyncOpenAI(api_key=self.openai_api_key)

            # If output model is json (dict)
            if isinstance(self.output_model, dict):
                # Ensure schema is compatible with strict mode
                strict_schema = self.ensure_strict_schema(self.output_model)

                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"{self.tool_name}_output",
                        "schema": strict_schema,
                        "strict": True
                    }
                }

                # Use standard chat completion (not parse)
                completion = await client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=response_format,
                )

                content = completion.choices[0].message.content
                if not content:
                    return json.dumps({"error": "Empty response"})

                return content 
            
            # If output model is pydantic model
            else:
                # Use Pydantic mode with parse
                completion = await client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=self.output_model,
                )

                parsed_response = completion.choices[0].message.parsed

                if not parsed_response:
                    return json.dumps({"error": "Empty response"})

                # Return as JSON string
                return parsed_response.model_dump_json()

        except OpenAIError as exc:
            return json.dumps({"error": f"OpenAI API error: {str(exc)}"})

        except Exception as e:
            return json.dumps({"error": f"LLM call failed: {str(e)}"})

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            **super().to_dict(),
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "model": self.model,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "SyntheticTool":
        """
        Create a SyntheticTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the SyntheticTool.

        Returns:
            SyntheticTool: A SyntheticTool instance created from the dictionary.

        Note:
            The client needs to be recreated with an API key from environment
            or other secure source as API keys are masked in serialization.
        """
        return (
            cls.builder()
            .tool_name(data.get("tool_name", "synthetic_tool"))
            .description(data.get("description", ""))
            .input_model(data.get("input_schema", {}))
            .output_model(data.get("output_schema", {}))
            .model(data.get("model", "gpt-5-mini"))
            .openai_api_key(data.get("openai_api_key", ""))
            .oi_span_type(OpenInferenceSpanKindValues(data.get("oi_span_type", "TOOL")))
            .build()
        )

class SyntheticToolBuilder(FunctionCallToolBuilder[SyntheticTool]):
    """Builder for SyntheticTool instances."""

    def tool_name(self, name: str) -> "SyntheticToolBuilder":
        self.kwargs["tool_name"] = name
        self.kwargs["name"] = name
        return self

    def description(self, desc: str) -> "SyntheticToolBuilder":
        self.kwargs["description"] = desc
        return self

    def input_model(self, model: type[BaseModel]) -> "SyntheticToolBuilder":
        self.kwargs["input_model"] = model
        return self

    def output_model(self, model: type[BaseModel]) -> "SyntheticToolBuilder":
        self.kwargs["output_model"] = model
        return self

    def model(self, model: str) -> "SyntheticToolBuilder":
        self.kwargs["model"] = model
        return self

    def openai_api_key(self, openai_api_key: str) -> "SyntheticToolBuilder":
        self.kwargs["openai_api_key"] = openai_api_key
        return self
