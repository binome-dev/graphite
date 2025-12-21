import dataclasses
import inspect
from dataclasses import dataclass
from typing import Annotated
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Mapping
from typing import MutableMapping
from typing import Optional
from typing import ParamSpec
from typing import Sequence
from typing import TypeVar
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from docstring_parser import parse as parse_docstring
from loguru import logger

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import JsonSchema
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema


P = ParamSpec("P")
R = TypeVar("R")


def _should_skip_param(name: str, param: inspect.Parameter) -> bool:
    """
    Decide whether a parameter is 'internal' and should be hidden from the schema.
    """
    if name in ("self", "cls"):
        return True
    if name.startswith("_"):
        return True
    # Common context parameter for MCP-like frameworks
    if name in ("ctx", "context"):
        return True
    return False


# --------- Type → JSON Schema conversion -----------------------------------


def _type_to_schema(tp: Any) -> JsonSchema:
    """
    Convert a Python type annotation to a JSON Schema fragment.
    This handles:
    - primitives (str, int, float, bool)
    - Optional / Union
    - Literal
    - Annotated[T, ...]
    - Sequence[T], list[T], tuple[T], set[T]
    - Mapping[str, T] / dict[str, T]
    - dataclasses
    - fallback to 'string' or 'object'
    """
    origin = get_origin(tp)
    args = get_args(tp)

    # Handle Annotated[T, *metadata] by peeling off T
    if origin is Annotated:
        inner, *meta = args
        schema = _type_to_schema(inner)
        # If metadata contains dict-like items, merge them
        for m in meta:
            if isinstance(m, Mapping):
                schema.update(m)
        return schema

    # NoneType and Any
    if tp is Any:
        return {}
    if tp is type(None):  # noqa: E721
        return {"type": "null"}

    # Primitives
    if tp is str:
        return {"type": "string"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is bool:
        return {"type": "boolean"}

    # Literal
    from typing import Literal  # local import to avoid py3.7 issues

    if origin is Literal:
        # derive type from first literal value
        values = list(args)
        if not values:
            return {}
        lit_type = type(values[0])
        base = _type_to_schema(lit_type) or {}
        base["enum"] = values
        return base

    # Union / Optional
    if origin is Union:
        # Optional[X] -> Union[X, NoneType]
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        has_none = len(non_none) != len(args)

        if len(non_none) == 1:
            # Optional[T] style
            schema = _type_to_schema(non_none[0])
            if has_none:
                schema = {"anyOf": [schema, {"type": "null"}]}
            return schema

        # General union
        return {
            "anyOf": [_type_to_schema(a) for a in args],
        }

    # Sequences / arrays
    from collections.abc import Mapping as ABCMapping
    from collections.abc import Sequence as ABCSequence

    if origin in (list, tuple, set, frozenset, Sequence, ABCSequence):
        if not args:
            return {"type": "array", "items": {}}
        # special case: tuple[T, T, ...] could be fixed-length, but we keep it simple
        items_schema = _type_to_schema(args[0])
        return {"type": "array", "items": items_schema}

    # Mappings / dict
    if origin in (dict, Mapping, MutableMapping, ABCMapping):
        # assume keys are strings, unless annotated otherwise
        value_type = args[1] if len(args) == 2 else Any
        return {
            "type": "object",
            "additionalProperties": _type_to_schema(value_type),
        }

    # Dataclasses → object with fields
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        inner_props: Dict[str, JsonSchema] = {}
        inner_required: List[str] = []
        hints = get_type_hints(tp, include_extras=True)
        for f in dataclasses.fields(tp):
            f_type = hints.get(f.name, Any)
            f_schema = _type_to_schema(f_type)
            if f.default is not dataclasses.MISSING:
                f_schema.setdefault("default", f.default)
            elif f.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
                # we can't serialize the factory, just mark as optional
                pass
            else:
                inner_required.append(f.name)
            inner_props[f.name] = f_schema
        obj: JsonSchema = {"type": "object", "properties": inner_props}
        if inner_required:
            obj["required"] = inner_required
        return obj

    # Enums
    import enum

    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        values = [m.value for m in tp]  # type: ignore[arg-type]
        # derive base type from first value
        base = _type_to_schema(type(values[0])) if values else {}
        base["enum"] = values
        return base

    # Fallbacks
    if isinstance(tp, type):
        # Unknown class type → treat as opaque object
        return {"type": "object"}

    # Very last resort
    return {}


@dataclass
class ParsedFunction:
    """
    A small, fastmcp-like helper that holds the introspected function info:

    - fn: the underlying callable (possibly unwrapped from staticmethod/callable class)
    - name: function name
    - description: from docstring
    - input_schema: JSON Schema for parameters
    - output_schema: JSON Schema for return value (or None)
    """

    fn: Callable[..., Any]
    name: str
    description: Optional[str]
    input_schema: JsonSchema
    output_schema: Optional[JsonSchema]

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        *,
        exclude_args: Optional[List[str]] = None,
        validate: bool = True,
    ) -> "ParsedFunction":
        """
        Build a ParsedFunction from a Python callable.

        - Validates that the function does not use *args/**kwargs (like fastmcp).
        - Optionally excludes specific arguments (`exclude_args`) which MUST have
          default values.
        - Uses type hints + docstring to construct schemas.
        """

        if validate:
            sig = inspect.signature(fn)
            for param in sig.parameters.values():
                if param.kind == inspect.Parameter.VAR_POSITIONAL:
                    raise ValueError("Functions with *args are not supported as tools")
                if param.kind == inspect.Parameter.VAR_KEYWORD:
                    raise ValueError(
                        "Functions with **kwargs are not supported as tools"
                    )

            if exclude_args:
                for arg_name in exclude_args:
                    if arg_name not in sig.parameters:
                        raise ValueError(
                            f"Parameter '{arg_name}' in exclude_args does not exist in function."
                        )
                    param = sig.parameters[arg_name]
                    if param.default is inspect.Parameter.empty:
                        raise ValueError(
                            f"Parameter '{arg_name}' in exclude_args must have a default value."
                        )

        # Capture name + docstring BEFORE possibly unwrapping
        fn_name = getattr(fn, "__name__", None) or fn.__class__.__name__
        fn_doc = inspect.getdoc(fn)

        # Unwrap callable classes: use __call__
        if not inspect.isroutine(fn) and hasattr(fn, "__call__"):
            fn = fn.__call__  # type: ignore[assignment]

        # Unwrap staticmethod
        if isinstance(fn, staticmethod):
            fn = fn.__func__  # type: ignore[assignment]

        sig = inspect.signature(fn)
        type_hints = get_type_hints(fn, include_extras=True)

        # Parse docstring
        parsed_doc = parse_docstring(fn_doc or "")
        short_desc = (parsed_doc.short_description or "").strip()
        long_desc = (parsed_doc.long_description or "").strip()
        if short_desc and long_desc:
            description = f"{short_desc}\n\n{long_desc}"
        else:
            description = short_desc or long_desc or None

        # Parameter docs mapping
        param_docs = {
            p.arg_name: (p.description or "").strip() for p in parsed_doc.params
        }

        # Build input_schema
        properties: Dict[str, JsonSchema] = {}
        required: List[str] = []

        prune_args = set(exclude_args or [])

        for name, param in sig.parameters.items():
            if _should_skip_param(name, param) or name in prune_args:
                continue

            ann = type_hints.get(name, Any)
            schema = _type_to_schema(ann)

            if param.name in param_docs and param_docs[param.name]:
                schema.setdefault("description", param_docs[param.name])

            if param.default is inspect.Parameter.empty:
                required.append(name)
            else:
                # You could also set a default here in the schema if you want:
                # schema.setdefault("default", param.default)
                pass

            properties[name] = schema

        input_schema: JsonSchema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            input_schema["required"] = required

        # Build output_schema from return type
        return_schema: Optional[JsonSchema] = None
        return_ann = type_hints.get("return", sig.return_annotation)

        if return_ann not in (inspect._empty, None, Any, ...):  # type: ignore[attr-defined]
            # Convert return type to schema
            return_schema = _type_to_schema(return_ann)

        return cls(
            fn=fn,
            name=fn_name,
            description=description,
            input_schema=input_schema,
            output_schema=return_schema,
        )


def llm_function(func: Callable[P, R]) -> Callable[P, R]:
    """
    Decorator to expose a method to the LLM (Language Learning Model) by capturing and storing its metadata.

    This decorator extracts function information including name, docstring, parameters, and type hints.
    It then constructs a FunctionSpec object for the function, which is stored as an attribute
    on the decorated function.

    Usage:
        @llm_function
        def my_function(param1: int, param2: str = "default") -> str:
            '''
            Function description.

            Args:
                param1 (int): Description of param1.
                param2 (str, optional): Description of param2. Defaults to "default".

            Returns:
                str: Description of the return value.
            '''
            # Function implementation

    The decorator will add a '_function_spec' attribute to the function, containing a FunctionSpec object with:
    - name: The function's name
    - description: The function's docstring summary
    - parameters: A ParametersSchema object describing the function's parameters

    Note:
    - The decorator relies on type hints and docstrings for generating the specification.
    - It automatically maps Python types to JSON Schema types.
    - Parameters without default values are marked as required.
    """

    parsed = ParsedFunction.from_function(func)

    # Convert ParsedFunction.input_schema into our ParametersSchema/ParameterSchema model
    raw_props = parsed.input_schema.get("properties", {}) or {}
    raw_required = parsed.input_schema.get("required", []) or []

    logger.info(f"Registering LLM function: {parsed}")

    properties: Dict[str, ParameterSchema] = {}
    for name, schema in raw_props.items():
        # Each `schema` is a JSON-schema fragment; ParameterSchema can hold it.
        logger.info(f"Parameter '{name}': schema={schema}")
        properties[name] = ParameterSchema(**schema)

    params_schema = ParametersSchema(
        type="object",
        properties=properties,
        required=list(raw_required),
    )

    spec = FunctionSpec(
        name=parsed.name,
        description=parsed.description,
        parameters=params_schema,
        output_schema=parsed.output_schema,
    )

    # Store the function spec as an attribute on the function
    setattr(func, "_function_spec", spec)
    return func
