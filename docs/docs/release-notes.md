# Release notes

## Unreleased

Streaming is the caller's choice, on a side channel:
- A caller streams with `invoke(..., stream=True)`, on an assistant, a
  workflow or `GrafiRuntime`, and gets `grafi.runtime.Delta`s (the text, the
  node, the step's number in the run and, from a function call, the call's id)
  between the outputs. An overridden `invoke`, of an assistant or a workflow,
  takes the keyword-only `stream: bool = False` and passes it on; one that does
  not fails with `TypeError: invoke() got an unexpected keyword argument
  'stream'`.
- Deltas are never published or stored. A stream's chunks are no longer
  events, so a streamed answer is one stored message rather than two records
  per token, and routing only sees whole messages. Every output reaches the
  caller once its step is stored. A step that fails mid-stream stores nothing,
  and streams again when its request resumes.
- `Message.is_streaming`, `get_async_output_events()` and the workflow's
  streamed output topics are gone. A tool that yielded `is_streaming` chunks
  calls `emit_delta(text)` for each piece instead, then yields its whole
  output; `streaming()` says whether anyone receives them. Where a tool is
  invoked directly, as in a test, `deltas_to(...)` collects its deltas.
- Histories stored before hold a stream's chunks as outputs: resuming such a
  request delivers the unacknowledged ones as they are, one chunk each.
- `LLM.is_streaming` defaults to `True`, and means: stream to a caller that
  streams. The provider is asked for a stream only then, and every LLM yields
  its answer as one message, its text, refusal and tool calls together
  (OpenAI-compatible tools, Claude, Gemini, Ollama). Structured output from a
  parse endpoint is never streamed. `to_stream_messages` is gone; a provider
  of your own checks `should_stream()`. A manifest saved before stores
  `"is_streaming": false`, the old default: remove it, or set it to `true`, for
  that LLM to stream.

Tools run plain functions, and answer every tool call:
- A function given to `FunctionTool` or `FunctionCallTool` may be sync or
  async, or a generator. Sync code runs in a worker thread (a `FunctionTool`'s
  ran on the event loop), so a tool's sync functions, which run concurrently,
  must be thread-safe, and code using the loop, such as `asyncio.Event.set()`,
  must be async; a sync generator runs in one thread of its own. Sync code
  cannot be stopped midway: a stop or a cancellation drops a call not yet
  started, and waits for one running to return, so sync code must not wait
  for the loop. Each string a generator yields streams as a delta, and its
  result is that text, joined; if it also yields other values, those are its
  results.
- `FunctionTool`: messages a function returns pass as they are (they were
  encoded as JSON); `None` outputs nothing (it was `"null"`); an async
  generator's strings make one message (each item was a publication).
  `to_messages` is gone; `grafi.tools.results.as_messages` converts values.
- A function-call tool answers each call it is given with exactly one
  `role="tool"` message, its content text: a string as it is, anything else as
  JSON. Calls run concurrently. Arguments are validated and coerced against
  the function's signature, and a parameter typed `InvokeContext` is passed
  the request's context; parameters named `ctx` or `context` are no longer
  hidden from the LLM.
- A failed call (an unknown function, malformed or invalid arguments, an
  exception) is answered with `Error: <type>: <message>`, so the LLM can
  recover. Before, it failed the run, or, for an unknown function, went
  unanswered and could end the run without output. `on_error="raise"`
  (`.on_error("raise")` on the builder) fails the node with
  `FunctionCallException` instead.
- In a workflow, a function-call node passes its tool the unanswered calls to
  its functions; on each topic carrying calls, the first function-call node
  reading it (one answering errors, if any does) also answers the calls there
  naming a function no LLM calling there was offered.
  `FunctionCallCommand` passes every call not yet answered, not only a
  message's first.
- A subclass registers the `@llm_function` methods of its base classes, and an
  override, decorated or not, is the one called. `.function(...)` on a
  subclass's builder keeps the class's own methods, and replaces a function of
  the same name. A plain function is called with the LLM's arguments alone;
  one whose first parameter is `self` is passed the tool.
- `MCPTool`, `AgentCallingTool` and `SyntheticTool` override only
  `async def call_function(invoke_context, name, arguments)`; `to_messages` is
  gone from function-call tools. `MCPFunctionTool.invoke_mcp_function` returns
  its text.
- A tool class's command, set with `@use_command`, is inherited by its
  subclasses; `TOOL_COMMAND_REGISTRY` is gone.

`has_text_response` is true only for a final answer: text with no tool call.
Text that came with tool calls was also routed to the output.

Components are saved as data with pydantic, in manifests (see
[Manifests](user-guide/manifests.md)):
- Assistants, workflows, nodes, tools and topics are saved with
  `model_dump(mode="json")`, which names the class by import path as `"class"`,
  and loaded with `model_validate`, as that class, synchronously. Every
  `to_dict()` and `from_dict()` of theirs (and of routes, expressions and
  commands) is gone, as are `ToolFactory`, `TopicFactory`,
  `add_additional_properties` and `Assistant.from_dict`. A tool of your own
  saves its fields without a `to_dict()`; one holding a client or an index
  leaves it out with `Field(exclude=True)`. A field a component does not have
  is refused, and a class defined in a script or a function cannot be saved.
- A manifest is `{"apiVersion": "grafi/v2", "kind": ..., "spec": ...}`:
  `to_manifest()`, `generate_manifest()`, and `from_manifest(path)`, which also
  upgrades a manifest saved before (`legacy_classes` names its own classes),
  and requires that every component name its class. An assistant loaded from
  one keeps the workflow it holds; `ReActAgent` saves only its workflow. A
  `FunctionCallTool`'s specs are not saved: they come from its functions.
- Loading imports classes and functions only from trusted modules: grafi's,
  and those named with `grafi.common.import_ref.trust_modules("my_app")`;
  others raise `UntrustedImportError`, an `ImportError`. Functions are saved by
  reference (`CallableRef`), and so are pydantic model classes, such as a
  `response_format` (`ModelRef`), as `{"ref": ...}`; of grafi's functions,
  only the route predicates in `grafi.nodes.conditions` can be named. A name
  reaches a class or a function of a trusted module, through classes only. A
  `CallableComponent` is a component, saved as its class and fields. `grafi`
  is a regular package (`grafi/__init__.py`), so a `grafi/` directory
  elsewhere on the path adds no module to it.
- A manifest never holds a secret's value. An LLM's `api_key`,
  `TavilyTool.api_key` and others declared with `env_secret("VAR")` are saved
  as `{"env": "VAR"}`; saving one set to another value raises `ManifestError`,
  and so does saving other text held under a name like a secret's, at any
  depth. An MCP setting holding a secret refers to a variable, as `${VAR}`.
  `from_manifest` lets a manifest read only each secret's own variable, and
  those named with `env=[...]`.
- An OpenAI-compatible tool (`OpenAITool`, `DeepseekTool`, `OpenRouterTool`)
  raises `LLMToolException` naming its variable when it has no API key, rather
  than letting the OpenAI SDK read `OPENAI_API_KEY`, which it would send to
  the tool's `base_url`. `DeepseekTool` and `OpenRouterTool` need their
  `base_url` (each has one by default), and send none of what the SDK reads
  from OpenAI's variables (`OPENAI_BASE_URL`, `OPENAI_ORG_ID`,
  `OPENAI_PROJECT_ID`, `OPENAI_CUSTOM_HEADERS`). `OllamaTool.api_key` reads
  `OLLAMA_API_KEY`.
- `ManifestError` is a `GrafiError`, not a `ValueError`, and
  `UntrustedImportError` both a `ManifestError` and an `ImportError`;
  `CallableSerializationError` is a `ManifestError`, no longer a `ValueError`.
  `model_dump()`, in python mode, gives plain values, with the class itself as
  `"class"`, so it is not for `json.dumps`: use `mode="json"`. `TavilyTool.client` is a property, made from `api_key` on
  first use.

Events are saved as their JSON form, flat (see
[Events](user-guide/events/events.md)):
- An event is stored as `model_dump(mode="json")`, `"event_version": 2`: no
  `event_context`, and a topic event's `data` is a list of messages, not JSON
  text. `EventCodec.encode()` and `decode()` (`default_event_codec`) save and
  load one, choosing the class by `event_type`. `Event.to_dict()`,
  `from_dict()`, `event_dict()` and `event_base()`, the `serialize_*` and
  `deserialize_*` helpers of `component_events`, and
  `EventGraph.to_dict()`/`from_dict()` are gone.
- Events stored before, of version `"1.0"`, are read as version 2, back to
  those of grafi 0.0.25, which named their fields otherwise. Stored events are
  not rewritten. An event of an earlier grafi raises `EventSerializationError`.
  `EventStorePostgres` reads tables with an `event_data` column, as written
  since grafi 0.0.30.
- Upgrade every process reading a store before any writes version 2: an
  earlier grafi skips version 2 events, and would resume a request without
  them. Rolling back after version 2 events are written is not safe.
- An event a store cannot write or read raises `EventSerializationError`: a
  value JSON cannot hold, an unknown type (register its class with
  `default_event_codec.register()`), an event of a class other than its type
  decodes as, a missing, unknown or newer version, or a field that does not
  validate. Before, a store logged and skipped an event it could not read.
  `EventStore._create_event_from_dict` is gone: a store's `codec` decodes.
- Each event class accepts only its own `event_type`. The generated classes
  are named `NodeInvokeEvent`, `ToolFailedEvent` and so on, and
  `FailedEvent.error` is text. An event in a field typed as its base class is
  saved as its own class.
- `InvokeContext.kwargs` must hold JSON values, checked when it is made: a
  datetime is saved as ISO text, and read back as that text. `Message.tools`
  is a list.
- `EventStorePostgres` writes rows with `event_version` `"2"`, and reads rows
  of either version, in `get_topic_events` too. `record_events` encodes the
  whole batch first, so an event it cannot encode writes nothing, and it
  stores a naive timestamp as UTC. `record_event` writes through it.
- `EventStoreInMemory(strict=True)` keeps events as a durable store does,
  encoded as JSON and decoded back, so a test fails on an event such a store
  could not keep. grafi's tests use it.

Providers:
- `ClaudeTool` gives a reply without tool use `tool_calls=None`, not `[]`,
  which routed it as a tool call and could loop a ReAct workflow. It always
  requests a stream, which the SDK requires for a large `max_tokens`.
- Gemini sends tool calls and their results as function-call parts; before,
  it dropped them from the history. It keeps each call's thought signature
  (in the tool call's `extra_content`, as Gemini's OpenAI-compatible API
  does) and sends it back, which Gemini 3 requires; a call it did not sign,
  such as another provider's, is sent with the value Google documents for
  that. A blocked prompt or answer sets the message's `refusal`.
- Claude, Gemini and Ollama keep a reply's text beside its tool calls (Claude
  used to blank it), and Gemini and Ollama no longer put "No content provided"
  in an empty reply. A key in Ollama's `chat_params` replaces the tool's own,
  such as `model`, rather than failing, and a tool result names its function.
- OpenAI-compatible tools send a tool call's standard fields only, whichever
  provider made it. Their streams tolerate providers that repeat fields in
  every chunk, keep URL citations (the annotations a message holds, as a
  whole answer now does too) and report usage (`stream_options` are sent to
  streams only), and an answer with audio is not streamed. An MCP image no
  longer overwrites the text before it.
- An LLM's history puts a call's results in the calls' order, which Ollama,
  matching results to calls by position, relies on, and holds a message the
  LLM consumed from several topics once. A node reading a message on several
  topics answers its calls once.

Invocations run with process default services, as tracing uses OpenTelemetry's
global provider:
- Set them once at startup with `set_default_services(ExecutionServices(...))`.
  Until then, the first invocation creates in-process ones (an in-memory event
  store) and logs once that their events are lost on exit.
- `assistant.invoke(...)` works without `GrafiRuntime` or `bind_services`. Those
  still give one invocation other services, such as a tenant's store.
- `current_services()` no longer raises outside a binding, unless
  `GRAFI_STRICT_SERVICES` is set, which forbids the in-memory fallback.
- `ExecutionServices.aclose()` (or `async with ExecutionServices(...)`) closes
  the services at shutdown; `EventStore.aclose()` releases a store's resources,
  such as `EventStorePostgres`'s connection pool.
- `GrafiRuntime()` without services runs with the current services, no longer
  with new in-process ones. So `ReActAgent.run()` keeps a conversation's
  history across turns again. For a store of its own, as `GrafiRuntime()` gave
  before, pass `GrafiRuntime(ExecutionServices())`.
- An invocation uses the services current where `invoke()` is called, in every
  layer, wherever its stream is read.

`ReActAgent.run()` without an invoke context continues a conversation of the
agent's own; before, every agent in a process shared one conversation id, the
module constant `grafi.agents.react_agent.CONVERSATION_ID`, now removed. A
server sharing an agent between users must pass an `InvokeContext` per user or
session: otherwise their turns share one history, prompts included.

`EventStorePostgres` connects lazily: constructing it does no I/O, and its
first use creates the `events` table, under an advisory lock, so processes
starting together do not race. It uses only the asyncpg driver; install it
with `pip install 'grafi[postgres]'`. psycopg2 is no longer needed, and the
sync `engine` attribute is gone (`async_engine` remains). A failure to reach
the database or create the table, from `initialize()` or the first use, is an
`EventPersistenceError`. `pool_timeout` now applies to the connection pool.

Tracing is set up with a single call: `setup_tracing(project_name=...)`. It
follows OpenTelemetry's standard environment (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_SERVICE_NAME`), returns the tracer
provider, and instruments every installed OpenInference instrumentor, not
only OpenAI's. `TracingOptions`, `is_local_endpoint_available` and the
`OTEL_COLLECTOR_ENDPOINT`/`OTEL_COLLECTOR_PORT` variables are gone: pass
`endpoint="http://host:4317"`, scheme included, or set
`OTEL_EXPORTER_OTLP_ENDPOINT`. Spans also name the Phoenix project
(`openinference.project.name`) after `project_name`. The default
tracer of `ExecutionServices` is OpenTelemetry's global tracer, so grafi's spans
are exported without passing a tracer; it is a no-op until a provider is set.
Do not pass `setup_tracing()`'s result as `tracer`: it is now the provider. An
application with a global tracer provider of its own now exports grafi's
spans, payloads included; `OPENINFERENCE_HIDE_INPUTS`/`_OUTPUTS` or
`GRAFI_SPAN_DISABLE_PAYLOADS` keep the payloads off.

Spans name their attributes as OpenInference does:
- `oi_span_type` becomes `openinference.span.kind`.
- `input` and `output` become `input.value` and `output.value`, with their
  mime types.
- `session.id` holds the conversation.
- A failure records `error.type`, an `error_id` matching its log line and
  failed events, and `error.details`, besides OpenTelemetry's exception event
  and `ERROR` status. These replace the duplicated `error`, `error.message` and
  `error.stack`.

`OPENINFERENCE_HIDE_INPUTS` and `OPENINFERENCE_HIDE_OUTPUTS` redact grafi's
spans as they redact LLM spans. `GRAFI_SPAN_DISABLE_PAYLOADS` still works.

`InMemTopicEventQueue.fetch(consumer_id)` now waits indefinitely for new events.
Previously, direct calls used a one-second default timeout. Pass `timeout=1.0`
to preserve that behavior, or `timeout=0` for an immediate read. Calls through
`TopicBase.consume()` already defaulted to an indefinite wait.

Cancelled queue reads now propagate cancellation and must leave the read cursor
unchanged. `TopicEventQueue.unconsumed_count()` is no longer abstract: a queue
backend need not implement it.

Each `TopicBase.publish_data()` call now creates a fresh destination publication
ID. Fan-out to different topics produces distinct IDs, with `emission_id`
recording the immediate source event's ID. Matched routes to the same topic are
deduplicated before delivery. Recording the same publication remains idempotent;
calling `publish_data()` again creates another publication. Older event records
without `emission_id` still decode with a value of `None`.

Runs now store every publication and consumption record with its actual
offset. Outputs are acknowledged only once their publications are stored.

Recovery restores publications in per-topic offset order, then consumer cursors,
before determining readiness. Missing or conflicting publication offsets and
consumption beyond surviving publications raise `WorkflowError` instead of
silently renumbering history or skipping records. Historical publications lost
through ID collisions or stream aggregation cannot be reconstructed automatically.

Nodes left ready by the stored history now run first on resume, in
node-definition order, then those the new input makes ready.

A node whose tool yields nothing no longer fails the run with an `IndexError`:
its `NodeRespondEvent` records `output_data` as `None` (`null` in stored
events). Readers of node respond events must allow for it; older events, with
an output, still decode.

In-flight requests, including paused HITL requests from older parallel runs,
may fail to resume if stream aggregation or input fan-out ID collisions removed
required publications. Backward-compatible event decoding does not repair those
histories; requests with complete history can still resume.

The workflow engine is rewritten. Each invocation now runs with one
coordinator that owns the run's state: a node is ready when its unread inputs
satisfy its subscription and no step of it is running; the coordinator takes
those inputs and runs the step in a task of its own, so independent nodes run in
parallel and each node runs one step at a time. A sequential run is the same
engine running one step at a time, first ready first run, and it now streams
outputs as steps commit instead of returning them all at the end. It queues each
ready node once, where the old sequential engine could queue a node again for
each publication it could consume (and then run it on inputs that did not
satisfy its subscription), so in graphs where a node becomes ready again before
it runs, steps can run in a different order and with different input batches. The per-node
polling tasks, the quiescence tracker (`AsyncNodeTracker`), the output listeners
(`AsyncOutputQueue`) and the separate sequential engine are removed: a run ends
exactly when no step is running and no node is ready, with no polling, so an
idle run uses no CPU.

Each step is committed before any node can read its output: when steps finish,
their consumption and publication records are written in one
`record_events()` batch (steps that finish together share one batch), and only
then do their publications become visible. A step that fails, stops or is
cancelled therefore leaves no consumption without a publication and no gap in a
topic's positions; retrying the request re-runs it. A custom event store must
write a `record_events()` batch atomically, as the in-memory and PostgreSQL
stores do; Postgres writes it in one transaction. A failed write fails the run
with `WorkflowError`, and the run writes no further steps, as the failed write
may still have landed.

A run keeps its topics' events itself; the event store is its only durable
state. Topic queues (`TopicEventQueue`, a topic's `event_queue`) and
`add_event()` are no longer used by workflow runs, so building a workflow with a
topic that has a custom queue raises `WorkflowError`. Workflows publish through
`TopicBase.prepare_publication()`, so building a workflow with a topic that
overrides any other public `TopicBase` instance method but `to_dict()` (`publish_data()`,
`consume()`, `commit()` and the like, which runs do not call) raises
`WorkflowError`; override `prepare_publication()` to transform or validate a
publication.

Internal modules and helpers of the old engine are removed:
`grafi.workflows.impl.parallel_engine`, `sequential_engine`, `run_recovery`,
`async_output_queue` and `async_node_tracker`, and from
`grafi.workflows.impl.utils` the functions `publish_events()` and
`get_node_input()`.

Every topic receives a step's publications together when that step commits, so
an output, such as a human-input request on an in-workflow output topic,
reaches the caller only once it is stored; tokens stream as deltas instead (see
above).
Resending the same answer event (the same event ID, answering the same
requests), for example a client retry after a failed attempt, delivers it to the
waiting node once; any other answer is a new input. Runs of one request must not
overlap, as both would restore the same history: keeping one run per
`assistant_request_id` at a time is up to the host. To hand items to another
node one at a time, or from a node that runs indefinitely, publish each item
from its own invocation.

A run stops when a node's failure reaches it (a node's own failure after the
node has recorded its failed event), when the caller closes the stream or is
cancelled, or on `workflow.stop()` (from any thread, for the runs in flight): no
new steps start, the other running steps are cancelled at once and awaited
before the close returns (a step that stopped the run, by failing or by calling
`stop()` itself from code carrying its context, is left to finish, unless the
caller leaves early or another stop follows), and steps
that already finished are still committed, unless the close itself is cancelled
or a store write failed. The first failure to reach the run is raised; later ones
are added to it as notes, and an interrupt or exit outranks an ordinary failure.
A `KeyboardInterrupt` or `SystemExit` raised by a tool, a store or the engine
during a run leaves the event loop once, from the task that raised it, as
asyncio does (the run's tasks never start eagerly, even under an eager task
factory); the run records it as its failure and stops its steps, and the run's
callers get a `WorkflowError` caused by it (or their own `CancelledError`, when
the loop's runner cancels them to clean up), so the runner's cleanup completes
before it raises the interrupt. One raised while an assistant or workflow
records its own invoke or respond event reaches the caller as an
`EventPersistenceError` caused by it; one raised while it records its failed
event is noted on the failure being raised. A cancellation during a cleanup does not
replace an interrupt already propagating.
A step the run cancelled is not a failure: an error it raises while being
cancelled (for example a transport reporting the
cancellation as an error) is logged, and its work runs again on resume. A step
that raises `CancelledError` without the run having cancelled it, such as a tool
whose transport times out internally, fails the run with `NodeExecutionError`.
The caller's task runs no tools or store calls, so a timeout around a run or its
close always raises `TimeoutError`; a caller cancelled while the run closes gets
its own `CancelledError` back, with the run's failure as a note.

Outputs are delivered at least once. An output counts as delivered when it is
handed to the caller, and delivered outputs are acknowledged when the stream
closes, so a human-input request received before closing can be answered on
resume. Outputs never handed over, outputs of steps that were not stored, and
outputs whose acknowledgement was not stored (the close was cancelled or timed
out, or the acknowledgement write failed) are delivered again when the request
resumes. Once a run fails it hands over no more
outputs.

Closing the stream of an invocation (`GrafiRuntime.invoke()`, an assistant's or
a workflow's `invoke()`) now closes each forwarded iterator and waits for the
run's steps before releasing services. A cleanup failure does not replace the
primary error or a cancellation in progress; otherwise an explicit close raises
it.

`GrafiRuntime.invoke()` now binds its services only while the assistant's stream
runs (each read, and its close) and in the tasks it starts, not in the caller's
own code between reads: code in an `async for` body that calls a component
directly needs `bind_services(runtime.services)`. Likewise a component's tracing
span is current only while the component's own code runs. A stream abandoned
without closing therefore leaves neither services nor spans attached to the
caller. Close streams all the same: one left open is closed only when it is
garbage collected, or when the loop shuts down, which closes it together with
the generators it reads: that can log errors, and leave the run's failure
recorded by only some of the components. A failed component's span records
its exception once.

`AsyncResult` now reads its source in the caller's task, as iterating the source
directly would: nothing is read ahead, so no output is counted as delivered
before the caller has it, and cancelling a read (for example a per-item timeout)
closes the source. Read from one task at a time, bounding a read with
`asyncio.timeout()` rather than `asyncio.wait_for()`, which on Python 3.11 runs
the read in another task that a second cancellation abandons, even while it is
closing the source. `await` returns only the items not yet read; items an
`await` had collected before it was cancelled or failed stay readable with `async for`;
later reads then raise as described next. A failed `AsyncResult` raises its error on
every later read, a source cut short by a cancelled read raises `RuntimeError`
on every later read, and awaiting one closed early with `aclose()` raises
`RuntimeError` instead of returning partial output.

Gemini, Ollama and synthetic tools now close their per-call clients, and every
LLM tool closes its response stream, including when the caller stops early. A
failure to close a client or stream after a completed call is logged rather than
failing the call.
