"""``@llm_function``: expose a function to an LLM as a FunctionSpec built from
its signature, type hints and docstring."""

import dataclasses
import enum
import inspect
import types
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Mapping
from typing import Annotated
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Literal
from typing import ParamSpec
from typing import TypeVar
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from docstring_parser import parse as parse_docstring

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import JsonSchema
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext

P = ParamSpec("P")
R = TypeVar("R")

_PRIMITIVES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}
# Parameters the caller supplies, never the LLM.
_HIDDEN_PARAMETERS = {"self", "cls"}
# Return annotations that describe no output.
_NO_OUTPUT = (inspect.Signature.empty, Any)


def llm_function(func: Callable[P, R]) -> Callable[P, R]:
    """Expose ``func`` to an LLM: attach the FunctionSpec built from it as
    ``func._function_spec`` and return ``func`` unchanged.

    Parameters named ``self`` or ``cls``, starting with ``_``, or typed
    ``InvokeContext`` (which the request's context is passed to) are hidden
    from the LLM; those without a default are required; ``*args`` and
    ``**kwargs`` are rejected. Descriptions come from the docstring: its
    summary for the function, its ``Args`` for parameters.
    """
    setattr(func, "_function_spec", _function_spec(func))
    return func


def _function_spec(func: Callable[..., Any]) -> FunctionSpec:
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    docstring = parse_docstring(inspect.getdoc(func) or "")
    described = {
        param.arg_name: (param.description or "").strip() for param in docstring.params
    }

    properties: Dict[str, ParameterSchema] = {}
    required: List[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            raise ValueError("Functions with *args are not supported as tools")
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            raise ValueError("Functions with **kwargs are not supported as tools")
        if (
            name in _HIDDEN_PARAMETERS
            or name.startswith("_")
            or is_invoke_context(hints.get(name))
        ):
            continue
        schema = _type_to_schema(hints.get(name, Any))
        if description := described.get(name):
            schema.setdefault("description", description)
        properties[name] = ParameterSchema(**schema)
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    summary = (docstring.short_description or "").strip()
    details = (docstring.long_description or "").strip()
    returns = hints.get("return", signature.return_annotation)
    return FunctionSpec(
        name=func.__name__,
        description="\n\n".join(text for text in (summary, details) if text) or None,
        parameters=ParametersSchema(
            type="object", properties=properties, required=required
        ),
        output_schema=None if returns in _NO_OUTPUT else _type_to_schema(returns),
    )


def is_invoke_context(annotation: Any) -> bool:
    """Whether a parameter so annotated takes the request's ``InvokeContext``:
    ``InvokeContext``, or ``Optional[InvokeContext]``."""
    if get_origin(annotation) in (Union, types.UnionType):
        return InvokeContext in get_args(annotation)
    return annotation is InvokeContext


def _type_to_schema(annotation: Any) -> JsonSchema:
    """A JSON Schema for a type annotation: ``{}`` (any value) when it cannot be
    described, and ``{"type": "object"}`` for a class it does not know."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        schema = _type_to_schema(args[0])
        for extra in args[1:]:
            if isinstance(extra, Mapping):
                schema.update(extra)
        return schema
    if origin is Literal:
        return _enum_schema(list(args))
    if origin in (Union, types.UnionType):
        return {"anyOf": [_type_to_schema(arg) for arg in args]}
    container = origin or annotation
    if annotation is Any or not isinstance(container, type):
        return {}  # Any, a TypeVar, a NewType and the like.
    if container in _PRIMITIVES:
        return {"type": _PRIMITIVES[container]}
    if dataclasses.is_dataclass(container):
        return _dataclass_schema(container)
    if issubclass(container, enum.Enum):
        return _enum_schema([member.value for member in container])
    if issubclass(container, (str, bytes, bytearray)):
        return {"type": "string"}
    if issubclass(container, Mapping):
        if len(args) == 2:
            return {"type": "object", "additionalProperties": _type_to_schema(args[1])}
        return {"type": "object"}
    if issubclass(container, Collection) or container is Iterable:
        return {"type": "array", "items": _type_to_schema(args[0]) if args else {}}
    # Another generic, such as a Callable, says nothing JSON can carry.
    return {} if origin else {"type": "object"}


def _enum_schema(values: List[Any]) -> JsonSchema:
    """Exactly ``values``, typed by the first of them."""
    if not values:
        return {}
    return {**_type_to_schema(type(values[0])), "enum": values}


def _dataclass_schema(cls: type) -> JsonSchema:
    hints = get_type_hints(cls, include_extras=True)
    properties: Dict[str, JsonSchema] = {}
    required: List[str] = []
    for field in dataclasses.fields(cls):
        field_schema = _type_to_schema(hints.get(field.name, Any))
        if field.default is not dataclasses.MISSING:
            field_schema.setdefault("default", field.default)
        elif field.default_factory is dataclasses.MISSING:
            required.append(field.name)
        properties[field.name] = field_schema
    schema: JsonSchema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
