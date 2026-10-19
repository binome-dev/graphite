# Invoke Decorators

Graphite's decorators live in `grafi.common.decorators`:

- **`@llm_function`** exposes a function to an LLM, with a specification built
  from its signature, type hints and docstring.
- **The record decorators** (`@record_assistant_invoke`,
  `@record_workflow_invoke`, `@record_node_invoke`, `@record_tool_invoke`)
  record a component's events and trace each invocation. Graphite's own
  components already use them; apply one when you write a component's
  `invoke()` from scratch.

## @llm_function

```python
from grafi.common.decorators.llm_function import llm_function

@llm_function
def calculate_sum(x: int, y: int, precision: float = 0.1) -> float:
    """
    Calculate the sum of two numbers with optional precision.

    Args:
        x: The first number to add.
        y: The second number to add.
        precision: Precision level.
    """
    return float(x + y)
```

The decorator attaches a `FunctionSpec` as `calculate_sum._function_spec` and
returns the function unchanged. A `FunctionCallTool` collects the specs of its
decorated methods and offers them to the LLM.

- The description is the docstring's summary (and longer text); each
  parameter's description comes from its `Args` entry.
- Parameters without a default are required. `self`, `cls`, parameters
  starting with `_`, and parameters typed `InvokeContext` are hidden from the
  LLM; a `FunctionCallTool` passes the last ones the request's context. `*args`
  and `**kwargs` are rejected.
- The return annotation, unless missing or `Any`, becomes the spec's
  `output_schema`.

Type hints map to JSON Schema as follows:

| Python type | JSON Schema |
|-------------|-------------|
| `str`, `int`, `float`, `bool`, `None` | `string`, `integer`, `number`, `boolean`, `null` |
| `list[T]`, `tuple[T, ...]`, `set[T]`, `Iterable[T]`, any other collection | `array` of `T` (but `bytes` is a `string`) |
| `dict[str, T]`, `Mapping[str, T]`, any other mapping | `object` whose values are `T` |
| `Optional[T]`, `Union[...]`, `T \| None` | `anyOf` |
| `Literal[...]`, an `Enum` | the values as `enum` |
| A dataclass | `object` with its fields, required unless they have a default |
| `Annotated[T, {...}]` | `T`, with the mapping's keys added (for example `{"minimum": 0}`) |
| Another class | `object` |
| `Any`, a `TypeVar`, another generic such as `Callable[...]` | any value (`{}`) |

## Record decorators

Each record decorator wraps an `invoke()` that returns an async generator:

```python
from grafi.common.decorators.record_decorators import record_tool_invoke

class MyTool(Tool):
    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        yield [Message(role="assistant", content="done")]
```

A tool's or node's `invoke()` takes `(invoke_context, input_data)`; an
assistant's or workflow's takes the input event, which carries the invoke
context.

For each invocation the decorator:

1. Records the invoke event (`ToolInvokeEvent`, `NodeInvokeEvent`, ...).
2. Runs the stream in a span named `{name}.invoke` (`{name}.run` for an
   assistant), passing every item through as it is yielded.
3. Records the respond event with the output. A tool records its messages,
   and a node its last publication, or `None` when it published nothing. An
   assistant or a workflow records its output events. Deltas passing through a
   streamed assistant or workflow are never recorded.
4. On failure, records the failed event instead, then raises the failure
   again. The failed event carries structured `error_details`: the error and
   its cause chain, the failing component, the request's ids, the root cause
   and an `error_id`. Every layer a failure passes through (tool, node,
   workflow, assistant) records the same `error_id`. Only the layer closest to
   the failure logs it, as one line with the ids to look it up.

A failure to store the invoke or respond event raises an
`EventPersistenceError`. A failure to describe or store the failed event is
reported and noted on the original failure, which is still the one raised. Closing the
stream early records neither a respond nor a failed event, unless closing it
fails.

The span is current only while the component's own code runs, so a caller's
code between reads is never traced as part of it. [Tracing](../guide/configuring-integration-with-opentelemetry.md) lists
its attributes, the settings that shape them, and how to export spans.

Set `GRAFI_ERROR_INCLUDE_TRACEBACK` to false for failed events to carry no
traceback.
