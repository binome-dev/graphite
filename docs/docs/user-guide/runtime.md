# Runtime & Services

Every invocation runs with three live services: an event store, a tracer and
an error reporter. You set them once at startup, as you set up tracing, and
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
service sets a durable one.

## `ExecutionServices`

A frozen dataclass of the three services. Each field has a default, so pass
only what you need:

| Field | Default | Notes |
|-------|---------|-------|
| `event_store` | `EventStoreInMemory()` | Lost on exit. Pass a durable store, such as `EventStorePostgres`, in production. |
| `tracer` | OpenTelemetry's global tracer | A no-op until a tracer provider is set, by [`setup_tracing`](../guide/configuring-integration-with-opentelemetry.md) or your application. |
| `error_reporter` | `ErrorReporter()` | Logs one concise line per failure via Loguru. |

Services are live infrastructure, kept apart from request metadata: the
serializable `InvokeContext` goes into every event, while `ExecutionServices`
has no serialization at all. Its `repr` hides the services, so a stray log
line cannot leak a database URL.

## Which services an invocation uses

Components read the services through `current_services()`, so no `invoke()`
signature carries them. It returns, in order:

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
the context, so it needs nothing.

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
