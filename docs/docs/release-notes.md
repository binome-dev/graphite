# Release notes

## Unreleased

### Upgrading from 0.0.36

Each step is detailed in the sections after it. A class whose `invoke`
takes no `stream`, a tool's that yields, or an `EventDrivenWorkflow`'s
decorated with `@record_workflow_invoke`, is refused when it is defined,
saying what to change.

1. A tool's `invoke` is `async def` and `return`s its messages; a streaming
   tool calls `emit_delta(text)` instead of yielding chunks, and `MsgsAGen` is
   gone. A command's `invoke` returns its tool's output.
2. Remove `Message(is_streaming=...)`; a function or function-call tool's
   `to_messages`, and an LLM's `to_messages` and `to_stream_messages`, are
   never called (a subclass defining one is warned): an LLM makes its
   answer in `invoke()`, streamed or not, so post-process an answer by
   overriding `invoke()`, decorated with `@record_tool_invoke`, calling
   `super().invoke()`: the answer it returns is the one recorded. Its text
   streams as the provider gives it; build such a tool with
   `.is_streaming(False)` where the raw text must not reach a caller.
3. Save with `model_dump(mode="json")` or `to_manifest()`, load with
   `model_validate` or `from_manifest`, in place of `to_dict`/`from_dict`,
   `ToolFactory` and `TopicFactory`; copy a component with `model_copy()`.
   Loading is not awaited, as `Assistant.from_dict` was, and
   `generate_manifest()` returns a `pathlib.Path`, not a `str`.
4. Pass `stream=` through an overridden `invoke` of an assistant or workflow,
   declaring the two overloads `Assistant.invoke` has (see the
   [Assistant](user-guide/assistant.md) guide); callers wanting live text pass
   `stream=True`; delete calls to `get_async_output_events()`.
5. A `FunctionTool` function returning `None` now publishes nothing (it was
   `"null"`), so nodes after it do not run; the strings a generator function
   yields are streamed text, concatenated as they are into one message
   (`"a"`, `"b"` give `"ab"`; 0.0.36 published each): yield dicts or
   `Message`s for separate results.
6. A function-call tool answers a failing call with its error, to the LLM; use
   `.on_error("raise")` to fail the run as before.
7. Sync functions run in worker threads, concurrently: make them thread-safe,
   and async if they use the event loop.
8. A function's parameter for the request's context is typed `InvokeContext`;
   one only named `ctx` or `context` is now offered to the LLM.
9. Declare secrets with `env_secret("VAR")`, typed `Optional[str]`, also
   where a subclass declares its `api_key` again. Declare an assistant's build parameters
   `exclude=True`, and any field left out of manifests with a default. Give
   `TavilyTool` its `api_key`, not a `client`. An assistant passes its key on
   as `.api_key(self.secret_reference("api_key"))`, its builder typing the key
   `grafi.common.manifest.SecretInput`, a value or `{"env": "VAR"}`. A tool of
   yours gives its SDK client `self.secret_value("api_key")` (an LLM's,
   `self.sdk_api_key()`), not the field, which is None for a tenant's unset
   variable.
10. Call `trust_modules("my_app")` at startup, before loading a manifest.
11. Load data you did not write yourself with `from_manifest`, naming in
    `allow_env` any variable it reads besides each secret's own; give it a
    file as a `pathlib.Path` (a `str` is JSON). Never load components from a
    party you would not give your keys to: data chooses the endpoints that
    receive them.
12. Give a node's command with `@use_command` on its tool's class, not
    `node.command = ...`.
13. A function-call tool deriving specs from its fields overrides
    `derived_specs()`, merging `super().derived_specs()`; one calling
    functions elsewhere overrides `call_function()`, which is called for each
    function it offers but does not have. Its `function_specs` holds only the
    specs of functions it calls elsewhere: drop code adding its own
    functions' specs, which a warning names. Code reading all it offers reads
    `get_function_specs()`; `functions` holds only those it is given.

    Code reading what an LLM node is offered reads
    `workflow.offered_to(node_name)` (narrowing an assistant's `workflow` to
    `EventDrivenWorkflow`): outside a step of the node, the LLM's
    `get_function_specs()` holds only the specs it is given. A workflow no
    longer calls an LLM's `add_function_specs()` as it is built (a subclass
    overriding it is warned): code reacting to the functions it is offered
    reads `self.get_function_specs()` in `invoke()` (a copy of the tool,
    `model_copy()`, is offered them too), and an LLM handing its call to
    another passes them on,
    `inner.model_copy(update={"function_specs": self.get_function_specs()})`.
14. Route with the publishing node, `publish_to(topic, when=predicate)` on
    every node publishing to that topic, not with a topic's condition:
    `Topic(condition=...)`, `OutputTopic(condition=...)` and
    `TopicBuilder.condition()` raise for grafi's topics, and the predicates
    moved from `grafi.topics.conditions` and `grafi.topics.topic_base` to
    `grafi.nodes.conditions`.
15. Give a component only fields it has, `OpenAITool(temperature=0.2)` is
    refused (pass it in `chat_params`), and `InvokeContext.kwargs` only JSON
    values. Ollama's `chat_params` are sent now (0.0.36 ignored them): one
    `chat()` takes neither as an argument nor as an option, such as OpenAI's
    `max_tokens` (Ollama's `num_predict`), is refused when the tool is made.
16. An event store of your own accepts `event_types` in its history reads,
    writes `self.codec.encode(event)` where it wrote `event.to_dict()`, and
    reads with `self.codec.decode(d)` where it called
    `self._create_event_from_dict(d)`; it needs no codec set up, sets
    `self.codec` where it set `self._codec` (which nothing reads now), and one
    of its own is `default_event_codec.copy()`, not `EventCodec({...})`. An
    event class of yours, whose `to_dict()`/`from_dict()` nothing calls now (a
    warning says so), reads the events its `to_dict()` stored in a
    `model_validator(mode="before")` (see
    [Events](user-guide/events/events.md#custom-event-types)).
17. Upgrade every process reading an event store before any writes version 2
    events.
18. Load manifests saved by 0.0.35 or 0.0.36 with
    `from_manifest(..., legacy_classes=...)` (build older ones in code);
    remove an LLM's saved `"is_streaming": false` for it to stream, and
    replace a saved `"model": "gpt-4.1-nano"`, 0.0.36's default, which OpenAI
    retired. A condition on an input topic, which no route can hold, is
    refused: check the input before invoking instead.
19. Set services once at startup, `set_default_services(ExecutionServices(...))`;
    `GrafiRuntime()` runs with them, not with a store of its own. A
    `ReActAgent` serving several users is given an `InvokeContext` per user:
    `CONVERSATION_ID` is gone.
20. Call `setup_tracing(project_name=...)`, which returns the tracer provider it
    sets: leave `ExecutionServices.tracer` out (a provider given there is
    refused); `TracingOptions` and `OTEL_COLLECTOR_*` are gone (pass
    `endpoint=`, or set `OTEL_EXPORTER_OTLP_ENDPOINT`).
21. Install `grafi[postgres]` for `EventStorePostgres` (asyncpg; psycopg2 and
    `.engine` are gone).
22. `InMemTopicEventQueue.fetch()` waits until an event comes: pass
    `timeout=1.0` for 0.0.36's wait.

### Streaming

Streaming is the caller's choice, on a side channel:
- A caller streams with `invoke(..., stream=True)`, on an assistant, a
  workflow or `GrafiRuntime`, and gets `grafi.runtime.Delta`s (the text, the
  node, the step's number in the run and, from a function call, the call's id)
  between the outputs. An overridden `invoke`, of an assistant or a workflow,
  takes the keyword-only `stream: bool = False` and passes it on; one that does
  not is refused when its class is defined (`TypeError`, saying what to add).
- Deltas are never published or stored. A stream's chunks are no longer
  events, so a streamed answer is one stored message rather than two records
  per token, and routing only sees whole messages. Every output reaches the
  caller once its step is stored. A step that fails mid-stream commits no
  consumption or publication, and streams again when its request resumes.
- `Message.is_streaming`, `get_async_output_events()` and the workflow's
  streamed output topics are gone: `Message(..., is_streaming=...)` raises
  `TypeError` (stored messages holding it still load). A tool that yielded
  `is_streaming` chunks calls `emit_delta(text)` for each piece instead, then
  returns its whole output; `streaming()` says whether anyone receives them.
  Where a tool is invoked directly, as in a test, `deltas_to(...)` collects
  its deltas.
- Histories stored before hold a stream's chunks as outputs: resuming such a
  request delivers the unacknowledged ones as they are, one chunk each.
- `LLM.is_streaming` defaults to `True`, and means: stream to a caller that
  streams. The provider is asked for a stream only then (Claude always is, as
  its SDK refuses a long request otherwise, and gives deltas only then), and
  every LLM returns its answer as one message, its text, refusal and tool
  calls together (OpenAI-compatible tools, Claude, Gemini, Ollama). Structured output from a
  parse endpoint is never streamed. `to_stream_messages` is gone (a subclass
  of grafi's providers defining it is warned, at class definition, that grafi never calls it); a
  provider of your own checks `should_stream()`. A manifest saved before stores
  `"is_streaming": false`, the old default: remove it, or set it to `true`, for
  that LLM to stream.

### Tools

Tools return their output, run plain functions, and answer every tool call:
- `Tool.invoke(invoke_context, input_data)` is a coroutine returning the
  tool's output, `Messages`, which its node publishes as one event; no
  messages, and the node publishes nothing. It was an async generator of
  batches, which a node held until its step ended anyway. `Command.invoke`
  returns the tool's output too, and `MsgsAGen` is gone: a tool of your own
  `return`s what it yielded. A tool or command whose `invoke` is not
  `async def`, a sync `def` or an async generator, raises `TypeError` when its
  class is defined; a tool returning anything but a list of messages fails,
  with a `TypeError` recorded as its failed event when its `invoke` is
  decorated with `@record_tool_invoke`. A node publishes at most once a step,
  so its `NodeRespondEvent` records all it published. A recorded stream's
  function runs within the recording, so a failure starting it is recorded.
  An override decorated alike, calling `super().invoke()`, is recorded
  once, with what it returns (0.0.36 recorded it twice).
- `node.command` cannot be set: a node's command follows from its tool's class,
  named with `@use_command(...)`, so a saved node loads with the command it ran.
  It is made from the node's tool when read, again once the node holds
  another.
- A function given to `FunctionTool` or `FunctionCallTool` may be sync or
  async, or a generator. Sync code runs in a worker thread (a `FunctionTool`'s
  ran on the event loop): in the executor of the invocation's services
  (`ExecutionServices(executor=...)`, a thread pool), else in grafi's own
  thread pool, one for each event loop, as asyncio's default executor is,
  never asyncio's default executor itself, which resolves host names for every
  connection the process opens. A forked process starts with fresh pools.
  grafi's pool has `min(32, cpu + 4)` workers, and a sync generator holds one
  for its whole run: give many slow sync functions a pool of their own. A sync
  function needing an invocation of its own should be async instead: a durable
  store's connections belong to the loop that opened them. A tool's sync
  functions, which run concurrently, must be thread-safe, and code using the
  loop, such as `asyncio.Event.set()`, must be async; a sync generator runs
  whole in one worker thread. Sync code
  cannot be stopped midway: a stop or a cancellation drops a call not yet
  started, and waits for one running to return, so sync code must not wait
  for the loop. Each string a generator yields streams as a delta, and its
  result is that text, joined; if it also yields other values, those are its
  results.
- `FunctionTool`: messages a function returns pass as they are (they were
  encoded as JSON); `None` outputs nothing (it was `"null"`); an async
  generator's strings make one message, and the other values it yields make
  one output (each item was a publication). `to_messages` is gone, and a
  subclass having it, its own or a mixin's, gets a `UserWarning` when its
  class is defined, once, pointing to the method's line, as for each method a
  tool class lists in `removed_methods`, which grafi no longer calls (`FunctionTool` and
  `FunctionCallTool`'s `to_messages`, and the `to_messages` and
  `to_stream_messages` of grafi's LLM providers, `OpenAICompatibleTool`,
  `ClaudeTool`, `GeminiTool` and `OllamaTool`, whose converters are private
  now);
  `grafi.tools.results.as_messages` converts values.
- A function-call tool answers each call it is given with exactly one
  `role="tool"` message, its content text: a string as it is, anything else as
  JSON. Calls run concurrently. Arguments are validated and coerced against
  the function's signature, and a parameter typed `InvokeContext` is passed
  the request's context; parameters named `ctx` or `context` are no longer
  hidden from the LLM. `ParameterSchema.type` is declared: a JSON Schema
  type, a list of them, or `None`, left out of the schema (one using `anyOf`
  has none).
- A failed call (an unknown function, malformed or invalid arguments, an
  exception) is answered with `Error: <type>: <message>`, so the LLM can
  recover. Before, it failed the run, or, for an unknown function, went
  unanswered and could end the run without output. `on_error="raise"`
  (`.on_error("raise")` on the builder) fails the node with
  `FunctionCallException` instead.
- In a workflow, a function-call node passes its tool the unanswered calls to
  its functions; on each topic carrying calls, the first function-call node
  reading it (preferring one with `on_error="return"`) also answers the calls there
  naming a function no LLM calling there was offered.
  `FunctionCallCommand` passes every call not yet answered, not only a
  message's first.
- A subclass registers the `@llm_function` methods of its base classes, and an
  override, decorated or not, is the one called. `.function(...)` on a
  subclass's builder keeps the class's own methods, and replaces a function of
  the same name. A plain function is called with the LLM's arguments alone;
  one whose first parameter is `self` is passed the tool. A tool's
  `functions` are those it is given; its class's `@llm_function` methods are
  merged with them as they are read, so the tool's set-up assigns nothing: a
  subclass may define its own `model_post_init` without calling its base's,
  and see its functions there, or use `validate_assignment`.
- A function-call tool calls its own functions itself.
  `async def call_function(invoke_context, name, arguments)` is called for each
  function it offers (`get_function_specs()`) but does not have -- a spec it
  is given (an `MCPTool`'s) or one it derives from its fields (an
  `AgentCallingTool`'s agent, a `SyntheticTool`'s tool) -- and by default
  raises `LookupError`, answered `No function`: override it to call functions
  elsewhere, as those three do. `AgentCallingTool` and `SyntheticTool` answer
  only their own name (`agent_name`, `tool_name`); another given spec's call
  is answered `No function`. When a function and a spec a subclass makes
  from its fields share a name, the function wins, offered and called.
  `to_messages` is gone from function-call tools (a subclass having it is
  warned). `MCPFunctionTool.invoke_mcp_function` returns its text. An
  `MCPTool` is built by checking its arguments, listing its servers, then
  made with what they offer. Both MCP tools connect per call (`grafi.tools.mcp_config.connect`),
  so calls hold no state in common (calls made at once to a stdio server each
  start its process, with no cap); a connection failing to close is logged,
  and fails no call answered.
- A tool class's command, set with `@use_command`, is inherited by its
  subclasses; `TOOL_COMMAND_REGISTRY` is gone.

`has_text_response` is true only for a final answer: text with no tool call.
Text that came with tool calls was also routed to the output.

### Manifests

Components are saved as data with pydantic, in manifests (see
[Manifests](user-guide/manifests.md)):
- Assistants, workflows, nodes, tools and topics are saved with
  `model_dump(mode="json")`, which names the class by import path as `"class"`,
  and loaded with `model_validate`, as that class, synchronously. Every
  `to_dict()` and `from_dict()` of theirs (and of routes, expressions and
  commands) is gone, as are `ToolFactory`, `TopicFactory`,
  `add_additional_properties` and `Assistant.from_dict`. A tool of your own
  saves its fields without a `to_dict()`; one holding a client or an index
  leaves it out with a default, `Field(default=None, exclude=True)` (saving
  refuses a required field it leaves out). A field a component does not have
  is refused, as `OpenAITool(temperature=0.2)` is (0.0.36 ignored it), and a
  class defined in a script or a function cannot be saved.
- A manifest is `{"apiVersion": "grafi/v2", "kind": ..., "spec": ...}`:
  `to_manifest()`, `generate_manifest()`, which makes its directory, writes
  the file whole (beside it, then moved over it; a link there is replaced) and
  returns its `pathlib.Path`, refusing an assistant name holding `/`, `\`,
  `:` or NUL, which names the file, and `from_manifest(...)`, which also upgrades a manifest
  saved before (`legacy_classes` names its own classes), and requires that
  every component name its class. An assistant loaded from
  one keeps the workflow it holds; `ReActAgent` saves only its workflow.
- An LLM's `function_specs`, the specs it is given for functions the app
  answers, is a field, saved when not empty (it was private, and not saved).
  A function-call node's function of the same name is offered with its own
  spec instead (0.0.36 offered the given one), and a `UserWarning` says so as
  the workflow is built, or when `offered_to` is called.
- A `FunctionCallTool`'s `function_specs` holds only the specs it is given,
  such as an MCP server's or those of a tool calling functions elsewhere, and
  is saved when not empty. `get_function_specs()` is what the LLM is offered:
  the specs it derives, then those it is given, once each by name.
  `derived_specs()` gives those it derives, one per function, and those a
  subclass makes from its fields, as `AgentCallingTool` and `SyntheticTool`
  do: a subclass that appended specs in `model_post_init` overrides it
  instead. A function no spec can be made of, such as a `functools.partial`,
  is refused when the tool is made (`TypeError`). A spec it is given for one
  of its own functions is not offered, the function's own is, and a
  `UserWarning` says so, in code as in a manifest; so an `MCPTool`'s own
  function wins over a server's tool of the same name.
- Loading imports classes and functions only from trusted modules: grafi's,
  and those named with `grafi.common.import_ref.trust_modules("my_app")`;
  others raise `UntrustedImportError`, an `ImportError`, whose message says not
  to trust the standard library when it names it. Functions are saved by
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
  depth. An MCP setting holding a secret refers to a variable, as `${VAR}`,
  which the MCP tool expands when connecting, with the value the variable had
  when the tool was made (a variable unset or empty when the tool is made is
  read when it connects; unset or empty then, the connection fails); such text
  anywhere else, as in
  an LLM's `chat_params` headers, would be sent as written, so saving it is
  refused too, as is `{"env": "VAR"}` under such a name anywhere but a
  component's secret field.
  Each component checks only its own fields, and leaves a field to its
  values only if every value type checks its own: components, an
  `MCPConfig`, and a function field (`CallableRef`), whose
  `CallableComponent` checks its own (a `Dict[str, Union[Component, str]]` is
  checked). So the names you choose, of nodes, topics, functions and MCP
  servers, are not taken for secrets' names, nor are the properties a JSON
  Schema names (when their values are schemas), such as a tool parameter
  called `pageToken`; a client's `{"properties": {"password": ...}}` is still
  refused. A refusal gives the advice that fits: an assistant's build
  parameter is declared `exclude=True` with a default, a tool's key read as
  `{"env": "VAR"}`.
- `from_manifest` is the one path that checks data: every component in it
  names its class, holds only what saving writes, gives no secret as a value,
  and reads only each secret field's own variable, or one named with
  `allow_env=[...]`, for `{"env": "VAR"}` and MCP's `${VAR}` alike.
  `allow_env` is a list of names: a string, or a mapping such as
  `os.environ`, raises `TypeError`. `model_validate` and the constructors
  trust what they are given, as code: `OpenAITool.model_validate({"api_key":
  {"env": "TENANT_B_KEY"}})` reads that variable, and is saved as it.
  `secret_reference("api_key")` gives a secret as another component is to
  receive it, `{"env": "VAR"}` while it holds none or that variable's value
  now (else the value, so the receiving component uses the same key), and
  `LLMBuilder.api_key()` takes one, so a tenant's variable carries through an
  assistant to its LLM, as `ReActAgent` passes it. `from_manifest` stops
  imports from untrusted modules and reads of variables not allowed; it does
  not stop the data choosing an endpoint, such as an LLM's `base_url` or an
  MCP server, that receives the secrets its components read: never load
  components from a party you would not give your keys to. Whatever the data
  holds, `from_manifest` raises `ManifestError` (a workflow invalid as built
  has its `WorkflowError` as the cause), `pydantic.ValidationError`, or an
  `OSError` reading a file.
- `from_manifest` takes a dict; JSON as a `str` or `bytes` (a `str` is always
  JSON, never a path, so request text cannot name a file; a UTF-8 BOM is
  fine); or the file an `os.PathLike`, such as a `pathlib.Path`, names. A
  component's own JSON (`model_dump(mode="json")`) loads too, but keep one with
  `to_manifest()`, which names the format's version. A tool's or a topic's
  `to_dict()` from grafi 0.0.35 or 0.0.36 upgrades too (0.0.30 to 0.0.34
  pickled topics' conditions and tools' functions, which are refused): any tool dict
  naming a `base_class` is a tool, named with `legacy_classes` if of your own.
  A tool saved so had its specs derived again on loading, so upgrading drops
  them, but an MCP tool's, which its servers gave. A topic holding a
  condition is refused, as routes hold conditions now, and a pickled
  function's error names where it was: a tool's function, `agent_call` or
  functions, a route's or a topic's condition.
- `to_manifest()` raises `ManifestError` for every failure to save, such as a
  field holding a client, naming the innermost field, a workflow's topics'
  too: `Class.field cannot be saved`; a reference cycle; or a field saving
  leaves out that loading would not restore: one `exclude` leaves out without
  a default (`is never saved, but required ... give it a default`), or one
  `exclude_if` leaves out holding other than its default.
- Any workflow, not only an `EventDrivenWorkflow`, saves its topics and loads
  them back. An assistant's fields that only build its workflow are declared
  `exclude=True`, as grafi's examples now do.
- A tool gives its SDK client the key `Component.secret_value(field)` reads:
  the one it holds, read from its variable when the tool was made or given in
  code; else, holding none, its variable's, read when used, so a key set after
  the tool was made is used. One read from its variable is saved as it, though
  the variable changed since. With none, it raises naming the variable, rather than leaving the
  SDK to read its own, perhaps another account's key: always for an
  OpenAI-compatible tool (`OpenAITool`, `DeepseekTool`, `OpenRouterTool`),
  whose SDK would read `OPENAI_API_KEY` and send it to the tool's `base_url`,
  and for `TavilyTool` and `SyntheticTool`; for Claude, Gemini and Ollama,
  whose SDKs read only their provider's own credentials (such as
  `ANTHROPIC_AUTH_TOKEN`), only when the key is read from a variable other
  than the tool's own, a tenant's. An LLM raises `LLMToolException`, from
  `sdk_api_key()`. `DeepseekTool` and `OpenRouterTool` need their
  `base_url` (each has one by default), and send none of what the SDK reads
  from OpenAI's variables (`OPENAI_BASE_URL`, `OPENAI_ORG_ID`,
  `OPENAI_PROJECT_ID`, `OPENAI_CUSTOM_HEADERS`). `OllamaTool.api_key` reads
  `OLLAMA_API_KEY`.
- Loading and saving raise `ManifestError`, a `GrafiError`, where 0.0.36's
  factories raised `ValueError`: catch `ManifestError` (and pydantic's
  `ValidationError` for invalid fields). `UntrustedImportError` is both a
  `ManifestError` and an `ImportError`; `CallableSerializationError` is a
  `ManifestError`, no longer a `ValueError`, and is exported from
  `grafi.common.exceptions` with the others.
- A dump is configuration. `model_dump()`, in python mode, gives plain values,
  with the class itself as `"class"`, so it is not for `json.dumps`: use
  `mode="json"`. A secret read from a variable is a reference to it,
  `{"env": "VAR"}`, in either mode, so `model_validate(dump)` reads that
  variable again, as `from_manifest` does, a tenant's included. Copy a
  component in use with `model_copy()` or `copy.deepcopy`, which keep the keys
  it holds and the values its MCP `${VAR}`s were read as. A computed field is
  left out of a dump, unless a class's `loads_computed` names it as state the
  class loads back itself, as a workflow does its `topics`.
- `TavilyTool.client` is a property, made with its key on first use, and
  again when the key changes, as a copy given another key has.

### Events

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
  An event of version 1 of a type of yours, stored by its own `to_dict()`,
  reaches its class as stored, to read in a before-validator; only grafi's
  own types are upgraded from version 1, and every type from version 2 on.
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
- Assistant events no longer have `model` (stored ones holding it still load):
  an assistant's model is a parameter it builds its workflow from.
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
- `get_agent_events` and `get_conversation_events` take a keyword-only
  `event_types` (`None`, the default, for every type), and an LLM, or a
  resumed request, reads only the events it needs. Both return events oldest
  first, by timestamp in Postgres and as recorded in memory; a reader needing
  an order of its own sorts them, as grafi sorts a topic's by offset. An event
  store of your own accepts it by keyword, and may return more than asked; one
  whose reads, its own or a mixin's, take no `event_types` raises `TypeError`
  when its class is defined. A store encodes and decodes with `self.codec`,
  which needs no setting up: one written for 0.0.36 and earlier set
  `self._codec`, which nothing reads now. A store with event types of its own
  registers them on `default_event_codec.copy()`, grafi's types and its own
  apart from every other store's; `EventCodec({...})` starts with only the types given, without grafi's.

### Packaging and providers

Packaging: grafi ships type information (`py.typed`), and requires pydantic 2
from 2.13.4 (`polymorphic_serialization`). Every LLM builder has
`.api_key(...)`, `OllamaToolBuilder`'s included. Every LLM has
`sdk_api_key()`, new: the key it gives its SDK, or an `LLMToolException`
naming its variable.

Providers:
- `OpenAITool`'s default model is `gpt-4o-mini`, as `ReActAgent`'s is:
  OpenAI retired `gpt-4.1-nano`, the default before.
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
  in an empty reply, and an Ollama tool result names its function.
- Ollama's `chat_params` are passed to `chat()`; 0.0.36 ignored them. A model
  setting (a field of `ollama.Options`), such as `temperature`, is passed in
  its `options` (one given in `options` too wins); any other key is an
  argument of `chat()`, so `model` replaces the tool's own, and a misspelt
  key is refused when the tool is made.
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

### Services and tracing

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
- An assistant's span no longer carries `model`: an assistant's model is a
  parameter it builds its workflow from, which a loaded assistant does not
  keep.
- A failure records `error.type`, an `error_id` matching its log line and
  failed events, and `error.details`, besides OpenTelemetry's exception event
  and `ERROR` status. These replace the duplicated `error`, `error.message` and
  `error.stack`.

`OPENINFERENCE_HIDE_INPUTS` and `OPENINFERENCE_HIDE_OUTPUTS` redact grafi's
spans as they redact LLM spans. `GRAFI_SPAN_DISABLE_PAYLOADS` still works.

### Topics and routing

A node routes what it publishes; a topic is a queue, and never drops an event:
- A node declares where its output goes with
  `Node.builder().publish_to(topic, when=predicate)`, each a route of its
  `publisher_router`; with no `when`, the route is always taken. A node is
  saved with its routes, a `when` by reference to its function.
- A topic's `condition` is gone: `Topic(condition=...)` and
  `OutputTopic(condition=...)` raise `ValidationError` naming the route that
  holds one now, and `TopicBuilder.condition()` raises for grafi's topics
  (a topic of yours may declare a `condition` field). The predicates
  (`always_true`, `has_tool_call`, `has_no_tool_call`, `has_text_response`)
  moved from `grafi.topics.conditions` (`always_true` from
  `grafi.topics.topic_base`) to `grafi.nodes.conditions`, as route predicates.
- An assistant's manifest saved by 0.0.36 loads with each topic's condition
  moved to the `when` of every route publishing to that topic; a topic saved
  on its own with a condition is refused: load the assistant holding it. So is
  a condition on a topic no node publishes to, such as an input topic's, which
  no route can hold: check the input before invoking instead.

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

### Workflow runs and recovery

A workflow wires its nodes as it is built, to check them, and again as
each run starts: each topic's readers, the functions each LLM node is
offered and the calls each function-call node answers. A run binds a
node's wiring to each of its steps (`grafi.runtime.wiring`), so a tool or
node a workflow shares with another holds none of it, and a node added,
removed, replaced or changed reaches the next run (0.0.36 added the
functions to the LLM tool when the workflow was built, for good). An
LLM's `get_function_specs()` returns, in a step of its node, those its
workflow wires to it, then its `function_specs`, the specs it is given;
`workflow.offered_to(node_name)` returns both. A
node's subscriptions are fixed when it is built: to change them, build a
new node, with its builder or constructor. A run refuses a node whose
subscriptions name other topics than when it was built (changed in place,
or copied with `model_copy(update=...)`).

Runs now store every publication and consumption record with its actual
offset. Outputs are acknowledged only once their publications are stored.

Recovery restores publications in per-topic offset order, then consumer cursors,
before determining readiness. Missing or conflicting publication offsets and
consumption beyond surviving publications raise `WorkflowError` instead of
silently renumbering history or skipping records. Historical publications lost
through ID collisions or stream aggregation cannot be reconstructed automatically.

Nodes left ready by the stored history now run first on resume, in
node-definition order, then those the new input makes ready.

A node whose tool returns no messages no longer fails the run with an `IndexError`:
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
overrides any other public `TopicBase` instance method (`publish_data()`,
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
