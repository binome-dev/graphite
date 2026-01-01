import inspect
from copy import deepcopy
from typing import Any
from typing import Dict
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import Union

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Messages
from grafi.tools.command import use_command
from grafi.tools.llms.llm_command import LLMCommand
from grafi.tools.tool import Tool
from grafi.tools.tool import ToolBuilder


Json = Dict[str, Any]


def add_additional_properties(
    schema: Json,
    value: Union[bool, dict] = False,
    *,
    only_when_missing: bool = True,
    skip_when_unevaluated_present: bool = True,
) -> Json:
    """
    Return a new schema dict where every object schema has `additionalProperties`
    set to `value` (default False).

    - only_when_missing: if True, do not overwrite an existing `additionalProperties`.
    - skip_when_unevaluated_present: if True, do not add AP when `unevaluatedProperties`
      is present on the same schema node (common in Pydantic v2 when extra='forbid').
    """
    schema = deepcopy(schema)

    def _is_object_schema(node: Json) -> bool:
        # Treat as object if type explicitly "object" OR it has properties-like keys
        if node.get("type") == "object":
            return True
        return any(
            k in node
            for k in (
                "properties",
                "required",
                "patternProperties",
                "additionalProperties",
            )
        )

    # JSON Schema keywords that contain nested schema(s)
    SCHEMA_KEYS_SINGLE = ("contains", "propertyNames", "if", "then", "else", "not")
    SCHEMA_KEYS_ARRAY = ("allOf", "anyOf", "oneOf")

    # keys that can hold a schema or array of schemas
    def _recurse(node: Any):
        if isinstance(node, dict):
            # Dive into $defs/definitions first (Pydantic v2 uses $defs)
            for defs_key in ("$defs", "definitions"):
                if defs_key in node and isinstance(node[defs_key], dict):
                    for _, sub in node[defs_key].items():
                        _recurse(sub)

            # Recurse common composition keys
            for k in SCHEMA_KEYS_SINGLE:
                if k in node:
                    _recurse(node[k])
            for k in SCHEMA_KEYS_ARRAY:
                if k in node and isinstance(node[k], list):
                    for sub in node[k]:
                        _recurse(sub)

            # items can be schema or list of schemas (tuple validation)
            if "items" in node:
                items = node["items"]
                if isinstance(items, list):
                    for sub in items:
                        _recurse(sub)
                else:
                    _recurse(items)
            # prefixItems (2020-12)
            if "prefixItems" in node and isinstance(node["prefixItems"], list):
                for sub in node["prefixItems"]:
                    _recurse(sub)
            # properties / patternProperties values are schemas
            if "properties" in node and isinstance(node["properties"], dict):
                for sub in node["properties"].values():
                    _recurse(sub)
            if "patternProperties" in node and isinstance(
                node["patternProperties"], dict
            ):
                for sub in node["patternProperties"].values():
                    _recurse(sub)
            # additionalProperties itself can be a schema; recurse into it if dict
            if "additionalProperties" in node and isinstance(
                node["additionalProperties"], dict
            ):
                _recurse(node["additionalProperties"])

            # Now, possibly inject at this node if it's an object schema
            if _is_object_schema(node):
                has_ap = "additionalProperties" in node
                has_uneval = "unevaluatedProperties" in node
                if (not has_ap or not only_when_missing) and not (
                    skip_when_unevaluated_present and has_uneval
                ):
                    # Don’t overwrite explicitly set AP if only_when_missing=True
                    if not (has_ap and only_when_missing):
                        node["additionalProperties"] = value
        elif isinstance(node, list):
            for sub in node:
                _recurse(sub)

    _recurse(schema)
    return schema


@use_command(LLMCommand)
class LLM(Tool):
    system_message: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.LLM
    api_key: Optional[str] = Field(
        default=None, description="API key for the LLM service."
    )
    model: str = Field(
        default="",
        description="The name of the LLM model to use (e.g., 'gpt-4o-mini').",
    )
    chat_params: Dict[str, Any] = Field(default_factory=dict)

    is_streaming: bool = Field(default=False)

    structured_output: bool = Field(
        default=False,
        description="Whether the output is structured (e.g., JSON) or unstructured (e.g., plain text).",
    )

    _function_specs: FunctionSpecs = PrivateAttr(default_factory=list)

    def add_function_specs(self, function_spec: FunctionSpecs) -> None:
        """Add function specifications to the LLM."""
        if not function_spec:
            return
        self._function_specs.extend(function_spec)

    def get_function_specs(self) -> FunctionSpecs:
        """Return the function specifications for this LLM."""
        return self._function_specs.copy()

    def prepare_api_input(self, input_data: Messages) -> Any:
        """Prepare input data for API consumption."""
        raise NotImplementedError

    def _serialize_chat_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serialize chat_params to ensure JSON compatibility.

        Converts Pydantic v2 model instances and classes to their dict representation.
        """
        serialized_params = {}
        for key, value in params.items():
            if isinstance(value, BaseModel):
                # Use model_dump() for Pydantic v2 model instances
                serialized_params[key] = value.model_dump()
            elif inspect.isclass(value) and issubclass(value, BaseModel):
                # Handle Pydantic v2 model classes by getting their schema
                serialized_params[key] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": value.__name__,
                        "strict": True,
                        "schema": add_additional_properties(value.model_json_schema()),
                    },
                }
            elif isinstance(value, dict):
                # Recursively serialize nested dictionaries
                serialized_params[key] = self._serialize_chat_params(value)
            elif isinstance(value, list):
                # Handle lists that might contain Pydantic models or classes
                serialized_params[key] = [
                    (
                        item.model_dump()
                        if isinstance(item, BaseModel)
                        else (
                            {
                                "type": f"{item.__module__}.{item.__name__}",
                                "json_schema": add_additional_properties(
                                    item.model_json_schema()
                                ),
                            }
                            if (inspect.isclass(item) and issubclass(item, BaseModel))
                            else item
                        )
                    )
                    for item in value
                ]
            else:
                # Keep other types as-is (they should be JSON serializable)
                serialized_params[key] = value
        return serialized_params

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "base_class": "LLMTool",
            "system_message": self.system_message,
            "api_key": "****************",
            "model": self.model,
            "chat_params": self._serialize_chat_params(self.chat_params),
            "is_streaming": self.is_streaming,
            "structured_output": self.structured_output,
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "LLM":
        """
        Create an LLM instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the LLM.

        Returns:
            LLM: An LLM instance created from the dictionary.

        Note:
            The api_key is masked in to_dict() for security, so from_dict()
            will need to retrieve it from environment or other sources.
        """
        raise NotImplementedError("from_dict must be implemented in subclasses.")


T_L = TypeVar("T_L", bound=LLM)


class LLMBuilder(ToolBuilder[T_L]):
    """Builder for LLM instances."""

    def model(self, model: str) -> Self:
        """Set the LLM model identifier.

        Args:
            model: Model name (e.g., 'gpt-4', 'claude-3-opus').

        Returns:
            Self for method chaining.
        """
        self.kwargs["model"] = model
        return self

    def chat_params(self, params: Dict[str, Any]) -> Self:
        """Set additional chat completion parameters.

        Args:
            params: Dictionary of parameters (temperature, max_tokens, etc.).
                If 'response_format' is included, structured_output is enabled.

        Returns:
            Self for method chaining.
        """
        self.kwargs["chat_params"] = params
        if "response_format" in params:
            self.kwargs["structured_output"] = True
        return self

    def is_streaming(self, is_streaming: bool) -> Self:
        """Enable or disable streaming responses.

        Args:
            is_streaming: True to stream responses token-by-token.

        Returns:
            Self for method chaining.
        """
        self.kwargs["is_streaming"] = is_streaming
        return self

    def system_message(self, system_message: Optional[str]) -> Self:
        """Set the system message for the LLM.

        Args:
            system_message: Instructions that guide the LLM's behavior.

        Returns:
            Self for method chaining.
        """
        self.kwargs["system_message"] = system_message
        return self
