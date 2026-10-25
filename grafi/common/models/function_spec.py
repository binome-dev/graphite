from typing import Annotated
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import AfterValidator
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

    # A JSON Schema type, or several; absent from the schema when None.
    type: Optional[Union[str, List[str]]] = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
    # Provider conversion (e.g. to OpenAI tool params) lives in provider
    # adapters such as grafi.tools.llms.impl.openai_adapter, keeping this core
    # model free of any vendor SDK.


FunctionSpecs = List[FunctionSpec]


def once_each(specs: FunctionSpecs) -> FunctionSpecs:
    """The first spec of each name in ``specs``, in order."""
    first: Dict[str, FunctionSpec] = {}
    for spec in specs:
        first.setdefault(spec.name, spec)
    return list(first.values())


# The specs a tool is given, the first of each name kept, as they are checked.
GivenSpecs = Annotated[FunctionSpecs, AfterValidator(once_each)]
