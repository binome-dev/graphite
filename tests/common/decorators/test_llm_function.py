"""Tests for @llm_function: the FunctionSpec it builds from a signature, type
hints and docstring."""

import dataclasses
import enum
from typing import Annotated
from typing import Any
from typing import Callable
from typing import DefaultDict
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Literal
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeVar
from typing import Union

import pytest

from grafi.common.decorators.llm_function import _type_to_schema
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.invoke_context import InvokeContext


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


@dataclasses.dataclass
class Point:
    x: int
    y: float = 0.0
    tags: List[str] = dataclasses.field(default_factory=list)


class Opaque:
    pass


@pytest.mark.parametrize(
    ("annotation", "schema"),
    [
        (str, {"type": "string"}),
        (int, {"type": "integer"}),
        (float, {"type": "number"}),
        (bool, {"type": "boolean"}),
        (type(None), {"type": "null"}),
        (Any, {}),
        (Optional[int], {"anyOf": [{"type": "integer"}, {"type": "null"}]}),
        (Union[int, str], {"anyOf": [{"type": "integer"}, {"type": "string"}]}),
        (int | None, {"anyOf": [{"type": "integer"}, {"type": "null"}]}),
        (
            Union[int, str, None],
            {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]},
        ),
        (Literal["a", "b"], {"type": "string", "enum": ["a", "b"]}),
        (Literal[1, 2], {"type": "integer", "enum": [1, 2]}),
        (Annotated[int, {"minimum": 0}], {"type": "integer", "minimum": 0}),
        (List[int], {"type": "array", "items": {"type": "integer"}}),
        (list, {"type": "array", "items": {}}),
        (set, {"type": "array", "items": {}}),
        (Sequence[str], {"type": "array", "items": {"type": "string"}}),
        (Tuple[int, ...], {"type": "array", "items": {"type": "integer"}}),
        (Iterable[int], {"type": "array", "items": {"type": "integer"}}),
        (
            Dict[str, int],
            {"type": "object", "additionalProperties": {"type": "integer"}},
        ),
        (dict, {"type": "object"}),
        (
            DefaultDict[str, int],
            {"type": "object", "additionalProperties": {"type": "integer"}},
        ),
        (
            Mapping[str, float],
            {"type": "object", "additionalProperties": {"type": "number"}},
        ),
        (
            Point,
            {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "number", "default": 0.0},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["x"],
            },
        ),
        (Color, {"type": "string", "enum": ["red", "blue"]}),
        (Opaque, {"type": "object"}),
        (bytes, {"type": "string"}),
        (type("Name", (str,), {}), {"type": "string"}),
        (Iterator[int], {}),
        (Callable[[int], str], {}),
        (TypeVar("T"), {}),
    ],
)
def test_type_to_schema(annotation: Any, schema: Dict[str, Any]) -> None:
    assert _type_to_schema(annotation) == schema


def test_llm_function_builds_a_spec_from_signature_and_docstring() -> None:
    @llm_function
    def forecast(
        city: str,
        days: int = 3,
        unit: Optional[Literal["c", "f"]] = None,
        _secret: str = "",
        context: InvokeContext = None,  # type: ignore[assignment]
    ) -> Dict[str, float]:
        """Get the forecast.

        Longer text here.

        Args:
            city: The city name.
            days (int): How many days.
        """
        return {}

    spec = forecast._function_spec  # type: ignore[attr-defined]
    assert isinstance(spec, FunctionSpec)
    assert spec.name == "forecast"
    assert spec.description == "Get the forecast.\n\nLonger text here."
    assert spec.parameters.required == ["city"]
    assert spec.parameters.model_dump(exclude_none=True)["properties"] == {
        "city": {"type": "string", "description": "The city name."},
        "days": {"type": "integer", "description": "How many days."},
        "unit": {
            "description": "",
            "anyOf": [{"type": "string", "enum": ["c", "f"]}, {"type": "null"}],
        },
    }
    assert spec.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }


def test_llm_function_leaves_the_function_itself_unchanged() -> None:
    def add(x: int, y: int) -> int:
        """Add two numbers."""
        return x + y

    assert llm_function(add) is add
    assert add(1, 2) == 3


def test_a_method_hides_self() -> None:
    class Tools:
        @llm_function
        def lookup(self, key: str) -> str:
            """Look a key up."""
            return key

    spec = Tools.lookup._function_spec  # type: ignore[attr-defined]
    assert list(spec.parameters.properties) == ["key"]
    assert Tools().lookup("k") == "k"


def test_without_a_return_annotation_there_is_no_output_schema() -> None:
    @llm_function
    def ping(host: str):  # type: ignore[no-untyped-def]
        """Ping a host."""

    assert ping._function_spec.output_schema is None  # type: ignore[attr-defined]


def _star(*args: int) -> None:
    """Star."""


def _double_star(**kwargs: int) -> None:
    """Double star."""


@pytest.mark.parametrize(
    ("function", "message"), [(_star, r"\*args"), (_double_star, r"\*\*kwargs")]
)
def test_variadic_parameters_are_rejected(function: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        llm_function(function)
