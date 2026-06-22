# Runtime & Dependency Injection

Graphite uses explicit, **request-scoped dependency injection** for the live
services an invocation needs — the event store, the tracer, and the error
reporter. The application constructs these once at startup, hands them to a
`GrafiRuntime`, and invokes assistants through it. There is no process-global
service locator.

> **Migration note.** Earlier versions used a global `container` singleton
> (`container.register_event_store(...)`, `container.event_store`). That has been
> removed. Construct a `GrafiRuntime` (or `GrafiRuntime()` for in-process
> defaults) and invoke through it. See [Migrating from the container](#migrating-from-the-container).

## Overview

| Concept | What it is |
|---------|------------|
| `ExecutionServices` | An immutable bundle of the three runtime dependencies (`event_store`, `tracer`, `error_reporter`). Not serializable. |
| `GrafiRuntime` | The composition root. Owns one `ExecutionServices` and exposes `invoke(...)`. |
| `current_services()` | Resolves the services bound for the current invocation (used inside the framework). |
| `bind_services(...)` | Context manager that binds an `ExecutionServices` to the current scope. |

The two halves are kept strictly separate:

- **Request metadata** (`InvokeContext`: conversation/invoke/assistant-request ids)
  is serializable and is persisted into every event.
- **Runtime services** (`ExecutionServices`) are live infrastructure and are
  **never** serialized into an event, a manifest, or an `InvokeContext`.

## `ExecutionServices`

`ExecutionServices` is a frozen dataclass. Every field has an in-process default,
so `ExecutionServices()` is a ready dev/test bundle, and any field can be
overridden with a normal keyword:

```python
from grafi.runtime import ExecutionServices
from grafi.common.event_stores.event_store_postgres import EventStorePostgres

# All in-process defaults (in-memory store, no-op tracer, Loguru error reporter).
services = ExecutionServices()

# Override only what you need; the rest keep their defaults.
services = ExecutionServices(event_store=EventStorePostgres(db_url="postgresql://..."))
```

| Field | Default | Notes |
|-------|---------|-------|
| `event_store` | `EventStoreInMemory()` | In-memory is lost on exit — pass a durable store in production. |
| `tracer` | `NoOpTracer()` | Spans are discarded — pass a real tracer for observability. |
| `error_reporter` | `ErrorReporter()` | Logs one concise line per failure via Loguru. |

It is immutable, exposes no `to_dict`/`model_dump`, and its `repr` hides the
dependencies so a stray log line can't leak a database URL.

## `GrafiRuntime`

`GrafiRuntime` owns an `ExecutionServices` and is the way to run an assistant.
`GrafiRuntime()` uses the defaults; production passes its own bundle:

```python
from grafi.runtime import GrafiRuntime, ExecutionServices
from grafi.common.event_stores.event_store_postgres import EventStorePostgres

# Local / tests
runtime = GrafiRuntime()

# Production: durable store + your tracer
runtime = GrafiRuntime(
    ExecutionServices(
        event_store=EventStorePostgres(db_url="postgresql://user:pass@host/db"),
        tracer=my_tracer,
    )
)
```

### Running an assistant

```python
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent

input_data = PublishToTopicEvent(invoke_context=invoke_context, data=messages)

async for event in runtime.invoke(assistant, input_data):
    print(event)
```

`runtime.invoke(...)` binds its services for the duration of the invocation;
components resolve them through `current_services()`. **No `invoke()` signature
carries a `services` parameter** — tools, nodes, and commands are unchanged.

Reuse one runtime across calls when you want shared conversation history (a
shared event store):

```python
runtime = GrafiRuntime(ExecutionServices(event_store=shared_store))
await consume(runtime.invoke(assistant, first_turn))
await consume(runtime.invoke(assistant, second_turn))   # sees the first turn's history
```

### Running an agent

`ReActAgent.run()` / `a_run()` run through a runtime too. By default they create
an in-process runtime; pass `runtime=` to share a store/tracer:

```python
agent = create_react_agent()

answer = await agent.run("What is Graphite?")                 # default runtime
answer = await agent.run("...", runtime=production_runtime)    # shared/durable
```

## Binding a scope directly

The public entry point is `runtime.invoke(...)`. If you call a component's
`invoke(...)` directly (tests, advanced use), wrap it in `bind_services(...)`
so `current_services()` resolves:

```python
from grafi.runtime import bind_services, ExecutionServices

with bind_services(ExecutionServices(event_store=store)):
    async for event in assistant.invoke(input_data):
        ...
```

Outside any bound scope, `current_services()` raises a clear `RuntimeError`
rather than silently constructing a default — so a forgotten runtime fails loudly.

### How propagation works

`bind_services` sets a `ContextVar` for the block. Because `asyncio` tasks copy
the current context when created, every node task, output listener, and streaming
producer spawned during the invocation inherits the binding automatically.
Concurrent invocations run as separate tasks, so each gets its own services with
no cross-talk — genuine per-invocation isolation. (This relies on `asyncio`
context propagation; Graphite uses no thread offloads. Code that hands work to a
thread — `run_in_executor`/`to_thread` — must re-bind the context explicitly.)

## Custom error reporting

`ErrorReporter` logs one concise, id-bearing line per failure (the full
structured record — cause chain, traceback, component fields — is persisted to
the event store, so the log only points at it). Subclass it to route errors
elsewhere; it must not raise:

```python
from grafi.runtime import ErrorReporter, ExecutionServices, GrafiRuntime

class SentryErrorReporter(ErrorReporter):
    def report(self, message: str, *, level: str = "error") -> None:
        super().report(message, level=level)  # keep the log line
        sentry_sdk.capture_message(message, level=level)

runtime = GrafiRuntime(ExecutionServices(error_reporter=SentryErrorReporter()))
```

## Migrating from the container

| Old (`container`) | New |
|-------------------|-----|
| `container.register_event_store(store)` | `GrafiRuntime(ExecutionServices(event_store=store))` |
| `container.register_tracer(tracer)` | `GrafiRuntime(ExecutionServices(tracer=tracer))` |
| `container.event_store` (inside the framework) | `current_services().event_store` |
| `assistant.invoke(input)` | `runtime.invoke(assistant, input)` |
| `AssistantBaseBuilder.event_store(...)` | removed — pass via `ExecutionServices` |

`SingletonMeta`, `Container`, the global `container`, `register_event_store`,
`register_tracer`, and the assistant builder's `event_store(...)` are all
removed.
