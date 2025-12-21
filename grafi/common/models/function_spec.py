from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.shared_params.function_definition import FunctionDefinition
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


JsonSchema = Dict[str, Any]


class ParameterSchema(BaseModel):
    """
    A wrapper over a JSON Schema fragment for a single parameter.

    - `type` and `description` are first-class.
    - Additional JSON Schema keywords (items, enum, format, etc.) are allowed
      and preserved when dumped to dict.
    """

    # type: Optional[object] = None , can also be anyOf
    description: Optional[str] = ""

    model_config = ConfigDict(extra="allow")


class ParametersSchema(BaseModel):
    """
    Top-level JSON Schema for function parameters, matching the shape expected
    by OpenAI function tools.

    Example (after model_dump):

    {
      "type": "object",
      "properties": {
        "user_id": {
          "type": "integer",
          "description": "The user id"
        },
        ...
      },
      "required": ["user_id"]
    }
    """

    type: str = "object"
    properties: Dict[str, ParameterSchema] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class FunctionSpec(BaseModel):
    """
    Internal representation of a function tool.

    - `parameters` is the input JSON Schema (same as OpenAI `parameters`)
    - `output_schema` is an optional JSON Schema for the return value
      (useful for your own plumbing, not used by OpenAI's tools API).
    """

    name: str
    description: Optional[str]
    parameters: ParametersSchema
    output_schema: Optional[JsonSchema] = None

    def to_openai_tool(self) -> ChatCompletionToolParam:
        return ChatCompletionToolParam(
            type="function",
            function=FunctionDefinition(
                name=self.name,
                description=self.description,
                parameters=self.parameters.model_dump(),
            ),
        )


FunctionSpecs = List[FunctionSpec]
