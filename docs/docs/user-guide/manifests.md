# Manifests

Every part of an agent, an assistant, a workflow, a node, a tool or a topic, is
a pydantic model, and is saved as data and loaded back with pydantic's own
methods. A manifest is a JSON file holding one, such as a whole assistant, to
store, review or ship it without its code.

## Saving and Loading

`model_dump(mode="json")` gives a component's fields, and its class by import
path, as `"class"`:

```python
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool import Tool

data = OpenAITool(model="gpt-4o-mini").model_dump(mode="json")
# {"class": "grafi.tools.llms.impl.openai_tool:OpenAITool", "tool_id": "...",
#  "name": "OpenAITool", "model": "gpt-4o-mini",
#  "api_key": {"env": "OPENAI_API_KEY"}, ...}

tool = Tool.model_validate(data)  # An OpenAITool.
```

`model_validate` builds the class the data names, which must be the class it is
called on or a subclass of it, so a subclass loads as itself, with its own
fields. A field declared as a base class, such as `tool: Tool`, saves the whole
subclass too. A field the class does not have is refused, so a misspelt one is
not ignored.

The class must be importable: defined at the top level of a module, not in the
script being run (`__main__`) or in a function. Saving one that is not fails:
`to_manifest()` raises `ManifestError`, and `model_dump(mode="json")` pydantic's
`PydanticSerializationError`, with its message.

`model_validate` and the constructors trust what they are given, as code: a
component built from data that way reads the environment variables the data
names. Load data you did not write yourself, such as a file or a request, with
`from_manifest`, which checks it against a manifest's rules (see
[Manifest Files](#manifest-files)), and only from a source you would give the
secrets it can reach (see [Trust](#trust)). `model_dump()`, in python mode, gives a
component's values as pydantic does, with the class itself as `"class"`, for
use in the same process, but a dump is configuration: a secret read from a
variable is `{"env": "VAR"}`, as in JSON, so `model_validate` of it reads that
variable again, as `from_manifest` does, a tenant's included. Copy a component
in use with `model_copy()` or `copy.deepcopy`, which keep the keys it holds
(and the values its MCP `${VAR}`s were read as). A manifest is the plain JSON
dump, `model_dump(mode="json")`: one made with pydantic's `round_trip=True` or
`serialize_as_any=True` is not. A computed field is left out of a dump, as it
follows from the fields that are; it is still computed and serialized while
dumping, so a value that is not data, such as a client, is a plain
`@property`, not a computed field. A class's `loads_computed`, merged
with its bases', names one that is saved as its state: the class loads it back
itself, taking it out of the data in a validator of its own, as a workflow
does its `topics`. `manifest_kind` names the `kind` a manifest of a class and
its subclasses has, as `"Tool"`.

Nodes refer to their topics by name, and a workflow, of any kind, saves its
topics with it, so a workflow or an assistant is saved whole. A node loaded on its own is given
every topic it names, those it subscribes to and those its routes publish to, by
name, in the validation context:

```python
node = Node.model_validate(
    data,
    context={
        "topics": {
            "agent_input_topic": agent_input_topic,
            "function_call_topic": function_call_topic,
            "agent_output_topic": agent_output_topic,
        }
    },
)
```

## Manifest Files

A manifest wraps a component's JSON in an envelope naming the format and the
component's kind:

```json
{"apiVersion": "grafi/v2", "kind": "Assistant", "spec": {"class": "...", ...}}
```

| Method | Description |
|--------|-------------|
| `to_manifest()` | The component's manifest, as a dict. |
| `SomeClass.from_manifest(manifest, *, allow_env=(), legacy_classes=None, context=None)` | Loads the component a manifest holds, which must be a `SomeClass`: a dict; JSON as a `str` or `bytes` (a `str` is always JSON, never a path; a UTF-8 BOM is fine); or the file an `os.PathLike`, such as a `pathlib.Path`, names. A component's own JSON, `model_dump(mode="json")`, loads too; keep one with `to_manifest()`, which names the format's version. |
| `assistant.generate_manifest(output_dir=".")` | Writes the assistant's manifest to `<name>_manifest.json` in `output_dir`, made if need be, and returns the file's path, a `pathlib.Path`. A failed save leaves an earlier file as it was. |

```python
from grafi.assistants.assistant import Assistant
from grafi.common.import_ref import trust_modules

path = assistant.generate_manifest("manifests")  # A pathlib.Path.

trust_modules("my_app")
assistant = Assistant.from_manifest(path)
```

A `str` is never read as a path: text from a database or a request is parsed
as JSON, so it cannot name a file for the process to read. Text that is not
JSON raises `ManifestError` ("A manifest is JSON (a path is given as a
pathlib.Path)"); to read a file, pass a `pathlib.Path`.

`from_manifest` is how to load data you did not write yourself, and the one
path that checks it. It checks the envelope's kind before building anything,
and accepts only what saving writes: every component in it names its class,
holds no field saving leaves out, gives no secret as a value, and reads only
each secret field's own environment variable, or one `allow_env` names (see
[Secrets](#secrets)). A component class with an `__init__` of its own cannot be
loaded this way, as pydantic would call it without these rules: set such a
class up in `model_post_init`.

Whatever the data holds, `from_manifest` raises `ManifestError` (an
`UntrustedImportError` is one), `pydantic.ValidationError`, or an `OSError`
reading a file; a workflow invalid as built, such as one with no input topic,
is a `ManifestError` with the `WorkflowError` as its cause. So pass untrusted
input, as text, bytes or a dict, to `from_manifest`, and handle `ManifestError`
and `pydantic.ValidationError`. `model_validate`, by contrast, raises a
`ManifestError` met while loading as itself, not as a `ValidationError`, so a
web framework validating a request body would report it as a server error.

A manifest holds the state of what it saves, and loading it reproduces that,
ids included. What follows from code is not saved: the function specs a
`FunctionCallTool` derives (`derived_specs()`), one per function, and an
`AgentCallingTool`'s or a `SyntheticTool`'s, made from its fields; and a node's
command, which follows from its tool's class. The specs a tool is given, its
`function_specs`, are saved, an LLM's too (not those its workflow wires to
it, which follow from the workflow's nodes): an MCP tool saves the specs of the tools its
servers offered, so loading it connects to nothing, and a tool that calls
functions elsewhere saves the specs it was given. A spec given for one of the
tool's own functions is not offered, the function's own spec is, and is warned
of when the tool is made or loaded.
Loading is synchronous.

An assistant loaded from a manifest keeps the workflow it holds:
`_construct_workflow()` runs only for an assistant given no workflow. Declare
the fields an assistant only builds its workflow from `exclude=True`, with a
default, as `ReActAgent`'s are: saved, they would be a second copy of what the
workflow holds, which loading ignores.

```python
class MyAssistant(Assistant):
    # What it builds its workflow from. Not saved: a manifest holds the
    # workflow, which loading keeps.
    api_key: Optional[str] = env_secret("OPENAI_API_KEY", exclude=True)
    model: str = Field(default="gpt-4o-mini", exclude=True)

    def _construct_workflow(self) -> "MyAssistant":
        ...
```

## Trust

Loading imports the classes and functions a manifest names, and a manifest is
data that may come from anywhere, so it imports them only from trusted modules:
grafi's, and those you name at startup with `trust_modules`:

```python
from grafi.common.import_ref import trust_modules

trust_modules("my_app")  # my_app and its submodules.
```

A manifest naming anything else raises `UntrustedImportError`, an
`ImportError`, before the module is imported; its message says how to trust a
package of your own, and, for the standard library, not to trust it. A name
must be of something the
trusted module defines: `"my_app.tools:os.system"`, reaching what it imported,
is refused too. Of grafi's own functions, a manifest names only its route
predicates, in `grafi.nodes.conditions`. Trust only modules whose functions are
safe for a manifest to call. Saving needs no trust.

A manifest is still configuration: it chooses what its components call, such
as an LLM's `base_url` or an MCP server's URL or command, and those receive the
secrets the components use. A tool taking its endpoint from data you did not
write can send its key there whatever rules apply, and an MCP stdio command
runs as you: `from_manifest` stops untrusted imports and reads of variables not
allowed, not that. Never load components from a party you would not give your
keys to.

## Functions and Model Classes

A field holding a function is typed `CallableRef` (from
`grafi.common.callable_ref`), as a `FunctionTool`'s `function`, a route's
`when` and an `AgentCallingTool`'s `agent_call` are. It is saved as a reference
to it, `{"ref": "my_app.functions:summarize"}`, so the function must be
importable. Saving a lambda or a nested function raises
`CallableSerializationError`, a `ManifestError`. A function that needs
configuration is a `CallableComponent` (from
`grafi.common.callable_component`), a component like any other, saved as its
class and its fields: `{"class": "my_app.functions:Threshold", "limit": 3}`.

A field holding a pydantic model class is typed `ModelRef[...]` (from
`grafi.common.manifest`), as an LLM's `chat_params` is, for a
`response_format`: the class is saved as `{"ref": "my_app.models:UserForm"}`.

## Secrets

A manifest never holds a secret's value. A field declared with
`env_secret("VAR")` (from `grafi.common.manifest`) reads its value from the
environment variable `VAR` by default, and is saved as `{"env": "VAR"}`; loading
reads the variable again. It holds the text its variable holds, typed
`Optional[str]` (or `str`), with no constraint, which would apply to a key
loaded but not to one read by default: another type is refused when the
class is defined. An LLM's `api_key` is one, read from its provider's
variable, such as `OPENAI_API_KEY`, and so is `TavilyTool.api_key`
(`TAVILY_API_KEY`). Declare your own the same way, and give a client its value
as `secret_value(field)`:

```python
from typing import Optional

from weather_sdk import WeatherClient  # Your provider's SDK.

from grafi.common.decorators.llm_function import llm_function
from grafi.common.manifest import env_secret
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class WeatherTool(FunctionCallTool):
    api_key: Optional[str] = env_secret("WEATHER_API_KEY")

    @llm_function
    async def get_weather(self, city: str) -> str:
        """The current weather in a city."""
        client = WeatherClient(api_key=self.secret_value("api_key"))
        return await client.current(city)
```

`secret_value(field)` is the value the field holds, read from its variable
when the tool was made, or given in code; else, holding none, its variable's,
read when it is called, as the variable may be set after the tool was made;
with none it raises `ValueError`, naming the variable to set. Passing
the field itself, `self.api_key`, would give the client None where its
variable, such as a tenant's, is unset, and an SDK given none reads its own
default variable, perhaps another account's key.
`secret_value(field, required=False)` returns None instead, for a client that
works without a key too, but only for a field reading its own variable: one
read from another, a tenant's, is required always. A field that is not a secret is refused
(`ValueError`). An LLM of your own gives its SDK `self.sdk_api_key()`, which
raises `LLMToolException` (see [LLM](tools/llm.md#implementation-requirements)).

A tool keeps the key it was made with, so a variable set for another user's
request since does not change it; rotated, a key is taken up by a tool made
since. One read from its variable is saved as `{"env": "VAR"}` though the
variable changed since, as is a value set in code that equals the one read.

A secret set in code to a value other than its variable's cannot be saved, as
the manifest would load a different one: saving it raises `ManifestError`. So
does saving any other field holding text under a name that says it is a
secret, at any depth, such as `password`, `clientSecret`, `GITHUB_TOKEN`, or an
`Authorization` header in a dict or a list of pairs, or a URL holding a
password: declare secrets with `env_secret`. Text that only refers to a
variable, such as `"Bearer ${TOKEN}"`, holds no secret only in an MCP
configuration, which expands it when connecting; anywhere else, such as an
LLM's `chat_params` headers, it would be sent as written, so saving it is
refused too. So is `{"env": "VAR"}` under a secret's name anywhere but a
component's secret field, the one place it is read. The names are a
convention, so a secret under another name, such as in a command's arguments,
is not recognized. The names you choose are not settings: a node, topic,
function or MCP server called `token` holds no secret by its name, as each
component checks only its own fields. It leaves a field to its values when
every value type checks its own: components, an MCP configuration, and
functions (`CallableRef`, whose `CallableComponent` checks its fields); a
field holding other values too, such as a `Dict[str, Union[Component, str]]`,
it checks itself. Nor are the properties a JSON Schema names
(under `properties`, `patternProperties`, `$defs` or `definitions`, whose
values are schemas, objects or booleans): a tool parameter called `pageToken`
or `password` is no secret. A settings mapping under one of those names, such
as a client's `{"properties": {"password": "..."}}`, is checked as any other.
A refusal gives the advice that fits: for an assistant's build parameter, to
declare it `exclude=True`; for a tool's key, to read it as `{"env": "VAR"}`;
and the MCP note only for text holding `${`.

A secret may refer to another variable, `{"env": "TEAM_OPENAI_KEY"}`, and the
component reads that one, and saves it again. Code chooses it as it likes, as
for a tenant's key:

```python
tool = OpenAITool.model_validate({"api_key": {"env": "TENANT_B_KEY"}})
assert tool.to_manifest()["spec"]["api_key"] == {"env": "TENANT_B_KEY"}
```

A component gives another its secret as `secret_reference(field)` gives it:
`{"env": "VAR"}` while it holds none (the variable may be set later) or that
variable's value now; else the value, so the other uses this one's key though
the variable changed since. An
assistant building its tools from its key passes them
`.api_key(self.secret_reference("api_key"))`, as `ReActAgent` does, so the
tools read, and save, the variable the assistant's key came from, a tenant's
included:

```python
from grafi.agents.react_agent import ReActAgent

agent = ReActAgent.model_validate({"api_key": {"env": "TENANT_B_KEY"}})
llm = agent.workflow.nodes["OpenAIInputNode"].tool
assert llm is not None  # A node's tool is Optional.
assert llm.to_manifest()["spec"]["api_key"] == {"env": "TENANT_B_KEY"}
```

A manifest reads only each secret field's own variable, unless `from_manifest`
names others:

```python
assistant = Assistant.from_manifest(path, allow_env=["TEAM_OPENAI_KEY"])
tool = Tool.from_manifest(data, allow_env=["TEAM_OPENAI_KEY"])  # Its JSON.
```

so a manifest cannot have grafi read another secret of yours; loading it
otherwise raises `ManifestError`. `allow_env` is a list of names: a string, or a
mapping such as `os.environ`, raises `TypeError`, as iterating a mapping would
allow all its keys. An
OpenAI-compatible tool (OpenAI, DeepSeek, OpenRouter) never calls its provider
without a key of its own, as the OpenAI SDK given none would read
`OPENAI_API_KEY`, whatever the provider; and only `OpenAITool` lets the SDK
add what it reads from OpenAI's variables (`OPENAI_ORG_ID`,
`OPENAI_PROJECT_ID`, `OPENAI_CUSTOM_HEADERS`), so another provider's
`base_url` receives none of them. Claude, Gemini and Ollama call theirs with
no key where the tool's own variable, such as `ANTHROPIC_API_KEY`, is unset,
as their SDKs then use only their provider's own credentials, such as
`ANTHROPIC_AUTH_TOKEN`, Google's `GOOGLE_API_KEY` or Vertex AI's, or none, for
a local Ollama. A key read from another variable, a tenant's, each of them
requires: unset, it raises `LLMToolException` naming it. A manifest that
starts a program, as an MCP server's command, runs it as you: review such a
manifest as you would a script.

An MCP server's settings that hold a secret, such as its headers, environment
variables, `auth` or URL parameters named like one, refer to an environment
variable, as `${VAR}`, which is expanded when connecting, with the value the
variable had when the tool was made (a variable unset or empty when the tool
is made is read when it connects; unset or empty then, the connection fails),
as a tool keeps the key it was made with; saving one set to a
value raises `ManifestError`. A manifest's `${VAR}` references must be named in
`from_manifest(..., allow_env=[...])` too. Code gives them as it likes, as the
example below does: an MCP configuration chooses what runs, so it is code's, or
a manifest's you trust. Each call connects anew, so calls hold no state in
common; calls made at once to a stdio server each start its process, with no
cap.

```python
from typing import Any, Dict

from grafi.tools.function_calls.impl.mcp_tool import MCPTool

connections: Dict[str, Any] = {
    "docs": {
        "transport": "http",
        "url": "https://mcp.example.com/mcp/",
        "headers": {"Authorization": "Bearer ${DOCS_MCP_TOKEN}"},
    }
}
mcp_tool = await MCPTool.builder().connections(connections).build()
```

## Your Own Components

A tool, an assistant or a topic of your own is saved with its fields, with no
code of its own. A field holding something that is not data, such as a client,
an index or a database collection, is left out with `Field(exclude=True)`; such
a component is rebuilt in code rather than loaded. Saving one holding such a
value raises `ManifestError`, naming the innermost field that holds it, such as
`ClientTool.client`, not the workflow or node around it; a topic's, held by a
workflow's `topics`, is named too. A field left out must have a default, as
loading could not make it otherwise: saving a component whose excluded field is
required raises `ManifestError` (`... is never saved, but required ... give it
a default`). So does saving a component that holds itself, directly or not.

## Manifests Saved Before grafi/v2

`from_manifest` reads a manifest saved by grafi 0.0.35 or 0.0.36 (0.0.30 to
0.0.34 pickled every topic's condition and a function-call tool's functions,
which loading refuses, and earlier ones no grafi loads: build such an
assistant in code and save it again), an
assistant's `to_dict()`, or a tool's or a topic's, and upgrades it. Any tool
dict naming a `base_class` (`Tool`, `LLMTool`, `FunctionTool`,
`FunctionCallTool`) is a tool. It names classes by their bare names: grafi's
own tools are known, and `legacy_classes` maps others to their import paths:

```python
from pathlib import Path

assistant = Assistant.from_manifest(
    Path("old_manifest.json"),
    legacy_classes={"WeatherTool": "my_app.tools:WeatherTool"},
)
```

Its masked keys are dropped, so they are read from their variables. A tool's
specs are dropped too, as grafi 0.0.36 and earlier derived them again on loading, but
an MCP tool's, which its servers gave. A topic's
condition, from before routes, becomes the `when` of the routes to it; one on
a topic no node publishes to, such as an input topic's, which no route can
hold, is refused: check the input before invoking instead. The
assistant loads as the class `from_manifest` is called on, such as
`ReActAgent.from_manifest(...)`, or one `legacy_classes` maps its `type` to,
with the workflow it holds. A topic saved on its own with a condition is
refused, as only routes hold conditions now: load the assistant holding it. A
function it holds pickled, from an older grafi, is refused, unread, by an error
naming where it was, a tool's `function`, `agent_call` or one of its
`functions`, or a route's or a topic's condition: build the assistant in code
and save it again, or replace the function with `{"ref": "module:function"}`.

## Errors

| Error | When |
|-------|------|
| `ManifestError` (a `GrafiError`) | A component cannot be saved, as when it holds a secret, a value JSON cannot hold (such as a client), or its class cannot be imported; the message names the innermost field, `Class.field cannot be saved: ...`. Or it holds itself, or leaves out a field that has no default. Or a manifest is not JSON, is malformed, of another version or kind, names a class that is not the one expected, or breaks a rule above; or it reads a variable not allowed. `to_manifest()` raises it; `model_dump(mode="json")` raises pydantic's `PydanticSerializationError` with its message. Raised while loading, it comes out of validation as itself. |
| `CallableSerializationError` (a `ManifestError`) | A function cannot be saved or loaded. |
| `UntrustedImportError` (a `ManifestError`, and an `ImportError`) | A manifest names a class or function outside the trusted modules. |
| `pydantic.ValidationError` | A component's fields are invalid, missing, or unknown, or a node names a topic its workflow does not have. |
| `OSError` | `from_manifest` cannot read the file a path names. |

`from_manifest` raises only these: anything else the data makes go wrong, such
as a `WorkflowError` building a workflow, is a `ManifestError` with it as the
cause.
