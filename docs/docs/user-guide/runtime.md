# Runtime & Services

Every invocation runs with live services: an event store, a tracer, an error
reporter, and the executor its sync tool code runs in. You set them once at
startup, as you set up tracing, and
then build and run assistants like any other object:

```python
from grafi.runtime import ExecutionServices, set_default_services
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.instrumentations.tracing import setup_tracing

# At startup: a durable event store, and spans exported over OTLP.
set_default_services(
    ExecutionServices(event_store=EventStorePostgres(db_url="postgresql://user:pass@host/db"))
)
setup_tracing(project_name="my-agent")

# Anywhere after: run an assistant.
async for event in assistant.invoke(input_event):
    print(event)
```

During development, skip the setup: the first invocation creates in-process
services, with an in-memory event store, and logs once that its events are
lost on exit. That store keeps every event until then, so a long-running
service sets a durable one. To make sure production never falls back to it,
set `GRAFI_STRICT_SERVICES=true`: an invocation with no services set or bound
then raises instead.

At shutdown, close the services: `await services.aclose()` releases what they
hold, such as the event store's connection pool. Or use them as a context:

```python
async with ExecutionServices(event_store=EventStorePostgres(db_url=...)) as services:
    set_default_services(services)
    await serve()  # The application's lifetime.
```

Spans need nothing at shutdown: the tracer provider flushes them when the
process exits normally.

## `ExecutionServices`

A frozen dataclass of the services. Each field has a default, so pass only what
you need:

| Field | Default | Notes |
|-------|---------|-------|
| `event_store` | `EventStoreInMemory()` | Lost on exit. Pass a durable store, such as `EventStorePostgres`, in production. |
| `tracer` | OpenTelemetry's global tracer | A no-op until a tracer provider is set, by [`setup_tracing`](../guide/configuring-integration-with-opentelemetry.md) or your application. |
| `error_reporter` | `ErrorReporter()` | Logs one concise line per failure via Loguru. |
| `executor` | `None` | Where tools run sync code: a `ThreadPoolExecutor`, as the code runs in this process. `None` is grafi's own, one for each event loop, as asyncio's default executor is, but never that one, which also resolves host names for every connection the process opens. Its owner shuts it down. |

grafi's own pool has `ThreadPoolExecutor`'s default size, `min(32, cpu + 4)`
workers. A sync function holds a worker until it returns, and a sync generator
for its whole run, so many slow or long-streaming sync functions at once wait
for workers, as every other sync function then does: give them a pool sized for
them with `ExecutionServices(executor=ThreadPoolExecutor(max_workers=...))`.
A forked process starts with fresh pools. A sync function needing an
invocation of its own should be async instead, as the application runs in one
event loop (below).

Services are live infrastructure, kept apart from request metadata: the
serializable `InvokeContext` goes into every event, while `ExecutionServices`
has no serialization at all. Its `repr` hides the services, so a stray log
line cannot leak a database URL.

## Which services an invocation uses

Components read the services through `current_services()`, so no `invoke()`
signature carries them. Each layer reads them when it is invoked, so an
invocation runs with the services current where `invoke()` was called, wherever
its stream is then read. They are, in order:

1. The services bound for the invocation, by `bind_services(...)` or a
   `GrafiRuntime` with services of its own.
2. Otherwise, the process default: the services given to
   `set_default_services(...)`, else in-process ones created on first use.

Most applications only ever set the default. Bind other services where one
process serves several stores, such as one per tenant:

```python
from grafi.runtime import ExecutionServices, GrafiRuntime, bind_services

tenant = ExecutionServices(event_store=tenant_store)

async for event in GrafiRuntime(tenant).invoke(assistant, input_event):
    ...

with bind_services(tenant):  # The same, for any component called inside.
    ...
```

`GrafiRuntime()` without services runs with the current ones. That is how
`ReActAgent.run()` runs by default, so successive turns share one event store
and see each other's history. Without an invoke context, each agent continues
a conversation of its own; a server passes an `InvokeContext` per user or
session.

A binding holds in the context that made it, and in the `asyncio` tasks
started there, which copy their context: an invocation's coordinator and step
tasks inherit it. Work handed to a thread with `run_in_executor()` or
`threading.Thread` must bind the services again; `asyncio.to_thread()` copies
the context, so it needs nothing. A server that binds services per tenant
should leave the process default unset and set `GRAFI_STRICT_SERVICES=true`:
a binding lost on the way then raises, rather than writing to a default store.

Run the application in one event loop (one `asyncio.run(...)`): a durable
store's pooled connections belong to the loop that opened them.

## Streaming

A caller that streams an invocation also gets the deltas its tools emit, such
as an LLM's tokens, as they are emitted, between its outputs:

```python
from grafi.runtime import Delta

async for item in assistant.invoke(input_event, stream=True):
    if isinstance(item, Delta):
        print(item.content, end="", flush=True)  # The text, as it comes.
    else:
        ...  # An output event, once its step is stored.
```

`GrafiRuntime(...).invoke(...)` and `workflow.invoke(...)` take `stream=True`
too. Without it, an invocation yields its outputs only, and LLMs do not ask
their providers for a stream (but Claude, whose SDK refuses a long request
otherwise, and which then emits no deltas).

A `Delta` holds `content`, the text; `node_name`, the node whose step emitted
it; `step`, that step's number in the run, counted from 1 as steps start, so a
node's next turn (an agent's answer after its tool calls) starts a new one; and
`tool_call_id`, the tool call whose function emitted it, if one did. Every LLM
streams by default (see `is_streaming` in [LLM](tools/llm.md)), so filter by
`node_name` to show one node's text, such as the final answer's.

Deltas are a side channel: they are never published to a topic or stored, so
routing and the event log only ever see whole messages, which follow as the
step's output. An output reaches the caller only once its step is stored. A
step that fails or is stopped commits no consumption or publication (a
failed step's invoke and failed events are stored, a stopped step's invoke
events only), and when its request resumes it
runs, and streams, again. A workflow that a tool runs inside a step, to call
another agent, streams only to its own caller.

A tool emits text with `emit_delta(text)`, from its step's tasks, from the
worker threads running its sync functions, or from a thread run by
`asyncio.to_thread` (a thread started otherwise does not inherit the step's
context, and its deltas reach no one); `streaming()` says whether
anyone receives them, so a tool can skip work that only serves a stream. A
function streams by yielding strings (see [FunctionTool](tools/function.md)
and [FunctionCallTool](tools/function-call.md)); the deltas a function emits
while answering a tool call carry the call's id. Outside a workflow, such as in a test that invokes a tool
directly, collect the deltas with `deltas_to`:

```python
from grafi.runtime import deltas_to

received = []
with deltas_to(received.append):
    messages = await tool.invoke(invoke_context, input_messages)
```

## Testing

Give each test services of its own, so tests never share a store through the
process default:

```python
import pytest
from grafi.runtime import ExecutionServices, bind_services

@pytest.fixture(autouse=True)
def services():
    with bind_services(ExecutionServices()) as services:
        yield services
```

## Custom error reporting

`ErrorReporter` logs one concise, id-bearing line per failure. The full record
(cause chain, traceback, component fields) is in the event store, and the log
line points to it. Subclass it to route errors elsewhere; `report` must not
raise:

```python
from grafi.runtime import ErrorReporter, ExecutionServices, set_default_services

class SentryErrorReporter(ErrorReporter):
    def report(self, message: str, *, level: str = "error") -> None:
        super().report(message, level=level)  # Keep the log line.
        sentry_sdk.capture_message(message, level=level)

set_default_services(ExecutionServices(error_reporter=SentryErrorReporter()))
```

## Migrating

| Before | Now |
|--------|-----|
| `container.register_event_store(store)` | `set_default_services(ExecutionServices(event_store=store))` |
| `container.register_tracer(tracer)` | `setup_tracing(...)`, or `ExecutionServices(tracer=tracer)` |
| `container.event_store` | `current_services().event_store` |
| `with bind_services(runtime.services):` around a whole program | Nothing: the process default applies |
