import inspect
from typing import Any
from typing import Callable
from typing import ParamSpec
from typing import TypeVar
from typing import get_type_hints

from docstring_parser import parse

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema


P = ParamSpec("P")
R = TypeVar("R")

JsonType = str


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

    type_hints = get_type_hints(func)
    
    # Extract function name and docstring
    func_name = func.__name__
    docstring = inspect.getdoc(func) or ""
    parsed_doc = parse(docstring)

    # Extract parameters and type hints
    signature = inspect.signature(func)
    parameters = signature.parameters

    # Extract parameter descriptions from docstring
    param_docs = {p.arg_name: p.description for p in parsed_doc.params}

    # Build the function specification
    func_spec = FunctionSpec(
        name=func_name,
        description=parsed_doc.short_description or docstring,
        parameters=ParametersSchema(
            properties={
                param_name: ParameterSchema(
                    type=_py2json(type_hints.get(param_name, Any)),
                    description=param_docs.get(param_name, ""),
                )
                for param_name, param in parameters.items()
                if param_name != "self"
            },
            required=[
                param_name
                for param_name, param in parameters.items()
                if param_name != "self" and param.default == inspect.Parameter.empty
            ],
        ),
    )

    # Store the function spec as an attribute on the function
    setattr(func, "_function_spec", func_spec)
    return func  


def _py2json(t: type) -> JsonType:
    return {
        str:  "string",
        int:  "integer",
        float:"number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }.get(t, "string")