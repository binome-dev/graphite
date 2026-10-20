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

The rules on this page apply to the JSON form. `model_dump()`, in python mode,
gives a component's values as pydantic does, with the class itself as
`"class"`, for use in the same process.

Nodes refer to their topics by name, and a workflow saves its topics with it,
so a workflow or an assistant is saved whole. A node loaded on its own is given
its topics in the validation context:
`Node.model_validate(data, context={"topics": {topic.name: topic}})`.

## Manifest Files

A manifest wraps a component's JSON in an envelope naming the format and the
component's kind:

```json
{"apiVersion": "grafi/v2", "kind": "Assistant", "spec": {"class": "...", ...}}
```

| Method | Description |
|--------|-------------|
| `to_manifest()` | The component's manifest, as a dict. |
| `SomeClass.from_manifest(manifest, *, env=(), legacy_classes=None, context=None)` | Loads the component a manifest holds, a dict or the path of a JSON file, which must be a `SomeClass`. |
| `assistant.generate_manifest(output_dir=".")` | Writes the assistant's manifest to `<name>_manifest.json`, and returns the file's path. A failed save leaves an earlier file as it was. |

```python
from grafi.assistants.assistant import Assistant
from grafi.common.import_ref import trust_modules

path = assistant.generate_manifest("manifests")

trust_modules("my_app")
assistant = Assistant.from_manifest(path)
```

`from_manifest` is how to load a manifest you did not write with care. It checks
the kind before building anything, and accepts only what saving writes: every
component in it names its class, holds no field saving leaves out (such as a
function's spec), and gives no secret as a value (see [Secrets](#secrets)). A
component class with an `__init__` of its own cannot be loaded this way, as
pydantic would call it without these rules: set such a class up in
`model_post_init`.

A manifest holds the state of what it saves, and loading it reproduces that,
ids included. What follows from code is not saved: a `FunctionCallTool`'s
function specs come from its functions, and a node's command from its tool. An
MCP tool, though, is saved with the tools its servers offered, so loading
connects to nothing. Loading is synchronous.

An assistant loaded from a manifest keeps the workflow it holds:
`_construct_workflow()` runs only for an assistant given no workflow. Fields an
assistant only builds its workflow from are best `Field(exclude=True)`, as
`ReActAgent`'s are, as editing them in a manifest would change nothing.

## Trust

Loading imports the classes and functions a manifest names, and a manifest is
data that may come from anywhere, so it imports them only from trusted modules:
grafi's, and those you name at startup with `trust_modules`:

```python
from grafi.common.import_ref import trust_modules

trust_modules("my_app")  # my_app and its submodules.
```

A manifest naming anything else raises `UntrustedImportError`, an
`ImportError`, before the module is imported. A name must be of something the
trusted module defines: `"my_app.tools:os.system"`, reaching what it imported,
is refused too. Of grafi's own functions, a manifest names only its route
predicates, in `grafi.nodes.conditions`. Trust only modules whose functions are
safe for a manifest to call. Saving needs no trust.

A manifest is still configuration: it chooses what its components call, such
as an LLM's `base_url` or an MCP server's URL or command, and those receive the
secrets the components use. Load manifests from sources you trust with them.

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
reads the variable again. An LLM's `api_key` is one, read from its provider's
variable, such as `OPENAI_API_KEY`, and so is `TavilyTool.api_key`
(`TAVILY_API_KEY`). Declare your own the same way:

```python
from typing import Optional

from grafi.assistants.assistant import Assistant
from grafi.common.manifest import env_secret


class MyAssistant(Assistant):
    api_key: Optional[str] = env_secret("OPENAI_API_KEY")
```

A secret set in code to a value other than its variable's cannot be saved, as
the manifest would load a different one: saving it raises `ManifestError`. So
does saving any other field holding text under a name that says it is a
secret, at any depth, such as `password`, `clientSecret`, `GITHUB_TOKEN`, or an
`Authorization` header in a dict or a list of pairs, or a URL holding a
password: declare secrets with `env_secret`. Text that only refers to a
variable, such as `"Bearer ${TOKEN}"`, is not a secret. The names are a
convention, so a secret under another name, such as in a command's
arguments, is not recognized.

A manifest may refer to another variable, `{"env": "TEAM_OPENAI_KEY"}`, and the
component reads that one, and saves it again. `from_manifest` lets a secret
read only its own variable, unless you name others:

```python
assistant = Assistant.from_manifest(path, env=["TEAM_OPENAI_KEY"])
```

so a manifest cannot have grafi read any other secret of yours. An
OpenAI-compatible tool (OpenAI, DeepSeek, OpenRouter) never calls its provider
without its own key, and only `OpenAITool` lets the OpenAI SDK add what it
reads from OpenAI's variables (`OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`,
`OPENAI_CUSTOM_HEADERS`), so another provider's `base_url` receives none of
them. Other SDKs given no key read their provider's own variables, such as
Google's `GOOGLE_API_KEY`. A manifest that starts a program, as an MCP server's
command, runs it as you: review such a manifest as you would a script.

An MCP server's settings that hold a secret, such as its headers, environment
variables, `auth` or URL parameters named like one, refer to an environment
variable, as `${VAR}`, which is expanded when connecting; saving one set to a
value raises `ManifestError`. A manifest's `${VAR}` references must be named in
`from_manifest(..., env=[...])` too.

```python
from grafi.tools.function_calls.impl.mcp_tool import MCPTool

connections = {
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
a component is rebuilt in code rather than loaded.

## Manifests Saved Before grafi/v2

`from_manifest` reads a manifest saved by an earlier grafi, an assistant's
`to_dict()`, and upgrades it. It names classes by their bare names: grafi's own
tools are known, and `legacy_classes` maps others to their import paths:

```python
assistant = Assistant.from_manifest(
    "old_manifest.json",
    legacy_classes={"WeatherTool": "my_app.tools:WeatherTool"},
)
```

Its masked keys are dropped, so they are read from their variables. A topic's
condition, from before routes, becomes the `when` of the routes to it. The
assistant loads as the class `from_manifest` is called on, such as
`ReActAgent.from_manifest(...)`, or one `legacy_classes` maps its `type` to,
with the workflow it holds. A function it holds pickled, from an older grafi,
cannot be loaded: save the manifest again with this version.

## Errors

| Error | When |
|-------|------|
| `ManifestError` (a `GrafiError`) | A component cannot be saved, as when it holds a secret or its class cannot be imported; or a manifest is malformed, of another version or kind, names a class that is not the one expected, or breaks a rule of `from_manifest`. `to_manifest()` raises it as it is; `model_dump(mode="json")` raises pydantic's `PydanticSerializationError` with its message. |
| `CallableSerializationError` (a `ManifestError`) | A function cannot be saved or loaded. |
| `UntrustedImportError` (a `ManifestError`, and an `ImportError`) | A manifest names a class or function outside the trusted modules. |
| `pydantic.ValidationError` | A component's fields are invalid, missing, or unknown, or a node names a topic its workflow does not have. |
