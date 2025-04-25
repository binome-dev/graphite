from typing import Dict
from typing import List
from typing import Optional

from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.shared_params.function_definition import FunctionDefinition
from pydantic import BaseModel
from pydantic import Field


class ParameterSchema(BaseModel):
    type: str
    description: Optional[str] = ""


class ParametersSchema(BaseModel):
    type: str = "object"
    properties: Dict[str, ParameterSchema]
    required: List[str] = Field(default_factory=list)


class FunctionSpec(BaseModel):
    name: str
    description: str
    parameters: ParametersSchema

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
