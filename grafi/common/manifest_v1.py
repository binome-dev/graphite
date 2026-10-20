"""Read manifests saved before ``grafi/v2``: an assistant's ``to_dict()``.

They name classes by bare name and mask secrets, and they hold what grafi/v2
loads differently or not at all (``base_class``, a node's ``command``, a route's
``from_stage``). :func:`upgrade_manifest` rewrites one as a grafi/v2 manifest;
see :meth:`grafi.common.manifest.Component.from_manifest`.
"""

import json
from typing import Any
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Union

from grafi.common.manifest import API_VERSION
from grafi.common.manifest import ManifestError
from grafi.common.manifest import import_path

_TOOLS = "grafi.tools"

# grafi's tool classes, by the bare names manifests before grafi/v2 use.
TOOL_CLASSES = {
    "FunctionCallTool": f"{_TOOLS}.function_calls.function_call_tool:FunctionCallTool",
    "FunctionTool": f"{_TOOLS}.functions.function_tool:FunctionTool",
    "OpenAITool": f"{_TOOLS}.llms.impl.openai_tool:OpenAITool",
    "ClaudeTool": f"{_TOOLS}.llms.impl.claude_tool:ClaudeTool",
    "GeminiTool": f"{_TOOLS}.llms.impl.gemini_tool:GeminiTool",
    "OllamaTool": f"{_TOOLS}.llms.impl.ollama_tool:OllamaTool",
    "DeepseekTool": f"{_TOOLS}.llms.impl.deepseek_tool:DeepseekTool",
    "OpenRouterTool": f"{_TOOLS}.llms.impl.openrouter_tool:OpenRouterTool",
    "AgentCallingTool": (
        f"{_TOOLS}.function_calls.impl.agent_calling_tool:AgentCallingTool"
    ),
    "SyntheticTool": f"{_TOOLS}.function_calls.impl.synthetic_tool:SyntheticTool",
    "TavilyTool": f"{_TOOLS}.function_calls.impl.tavily_tool:TavilyTool",
    "GoogleSearchTool": (
        f"{_TOOLS}.function_calls.impl.google_search_tool:GoogleSearchTool"
    ),
    "DuckDuckGoTool": f"{_TOOLS}.function_calls.impl.duckduckgo_tool:DuckDuckGoTool",
    "MCPTool": f"{_TOOLS}.function_calls.impl.mcp_tool:MCPTool",
    "MCPFunctionTool": f"{_TOOLS}.functions.impl.mcp_function_tool:MCPFunctionTool",
}

# grafi's topic classes, by their topic type.
TOPIC_CLASSES = {
    "Topic": "grafi.topics.topic_impl.topic:Topic",
    "AgentInputTopic": "grafi.topics.topic_impl.input_topic:InputTopic",
    "AgentOutputTopic": "grafi.topics.topic_impl.output_topic:OutputTopic",
    "InWorkflowInputTopic": (
        "grafi.topics.topic_impl.in_workflow_input_topic:InWorkflowInputTopic"
    ),
    "InWorkflowOutputTopic": (
        "grafi.topics.topic_impl.in_workflow_output_topic:InWorkflowOutputTopic"
    ),
}

_ASSISTANT = "grafi.assistants.assistant:Assistant"
_WORKFLOW = "grafi.workflows.impl.event_driven_workflow:EventDrivenWorkflow"
_NODE = "grafi.nodes.node:Node"

# What a manifest before grafi/v2 wrote in place of a secret.
_MASK = "****************"

# Tool fields saved under other names before grafi/v2: SyntheticTool's.
_RENAMED = {"input_schema": "input_model", "output_schema": "output_model"}


def upgrade_manifest(
    manifest: Mapping[str, Any],
    legacy_classes: Mapping[str, Union[str, type]],
    loading: Optional[type] = None,
) -> Dict[str, Any]:
    """A manifest saved before grafi/v2, an assistant's ``to_dict()``, as a
    grafi/v2 manifest. ``legacy_classes`` maps bare class names to classes or
    import paths: a tool's, a node's, or the assistant's ``type``. The
    assistant is of that class, else of the assistant class ``loading``, the
    one loading it, else an ``Assistant``."""
    if "workflow" not in manifest:
        raise ManifestError(
            "Not a manifest: neither a grafi/v2 manifest (with an apiVersion) "
            "nor an assistant saved before it (with a workflow)."
        )
    classes = {
        name: value if isinstance(value, str) else import_path(value)
        for name, value in legacy_classes.items()
    }
    spec = {
        key: value
        for key, value in manifest.items()
        if key in ("assistant_id", "name", "type", "oi_span_type")
    }
    assistant = classes.get(str(manifest.get("type")), _ASSISTANT)
    if assistant == _ASSISTANT and loading is not None:
        from grafi.assistants.assistant import Assistant

        if issubclass(loading, Assistant):
            assistant = import_path(loading)
    workflow = _workflow(manifest["workflow"], classes)
    return {
        "apiVersion": API_VERSION,
        "kind": "Assistant",
        "spec": {"class": assistant, **spec, "workflow": workflow},
    }


def _workflow(data: Mapping[str, Any], classes: Mapping[str, str]) -> Dict[str, Any]:
    workflow = {
        key: value
        for key, value in data.items()
        if key in ("workflow_id", "name", "type", "oi_span_type")
    }
    topics = data.get("topics", {})
    # Before routes, a topic's condition chose what it took; a route holds it.
    conditions = {
        name: _condition(topic.get("condition")) for name, topic in topics.items()
    }
    return {
        "class": _WORKFLOW,
        **workflow,
        "topics": {name: _topic(topic) for name, topic in topics.items()},
        "nodes": {
            name: _node(node, classes, conditions)
            for name, node in data.get("nodes", {}).items()
        },
    }


def _condition(condition: Any) -> Any:
    """A topic's condition, as the ``when`` of the routes to it: None for
    always, and grafi's own predicates where they now are."""
    if not isinstance(condition, Mapping) or "ref" not in condition:
        return condition  # None, a component, or a pickle, which fails loudly.
    module, _, name = str(condition["ref"]).partition(":")
    if condition["ref"] == "grafi.topics.topic_base:always_true":
        return None
    if module == "grafi.topics.conditions":
        return {"ref": f"grafi.nodes.conditions:{name}"}
    return condition


def _topic(data: Mapping[str, Any]) -> Dict[str, Any]:
    topic_type = data.get("type", "Topic")
    if topic_type not in TOPIC_CLASSES:
        raise ManifestError(f"Unknown topic type {topic_type!r}")
    topic = {key: value for key, value in data.items() if key != "condition"}
    return {"class": TOPIC_CLASSES[topic_type], **topic}


def _node(
    data: Mapping[str, Any],
    classes: Mapping[str, str],
    conditions: Mapping[str, Any],
) -> Dict[str, Any]:
    node = {
        key: value
        for key, value in data.items()
        if key not in ("class", "command", "publish_to", "publisher_router")
    }
    name = data.get("class", "Node")
    node_class = _NODE if name == "Node" else _class(name, classes, "node")
    if "publisher_router" in data:
        routes = [
            {key: value for key, value in route.items() if key != "from_stage"}
            for route in data["publisher_router"].get("routes", [])
        ]
    else:  # The list of topic names, before routes.
        routes = [
            {"topic": topic, **_when(conditions.get(topic))}
            for topic in data.get("publish_to", [])
        ]
    if data.get("tool") is not None:
        node["tool"] = _tool(data["tool"], classes)
    return {"class": node_class, **node, "publisher_router": {"routes": routes}}


def _tool(data: Mapping[str, Any], classes: Mapping[str, str]) -> Dict[str, Any]:
    tool = {
        _RENAMED.get(key, key): value
        for key, value in data.items()
        if key not in ("class", "base_class") and value != _MASK
    }
    for key in ("resources", "prompts"):  # MCPTool's, each as JSON text.
        items: List[Any] = tool.get(key, [])
        tool[key] = [_mcp_item(i) for i in items]
    if not tool.get("resources") and not tool.get("prompts"):
        tool.pop("resources", None)
        tool.pop("prompts", None)
    tool_class = _class(data.get("class"), classes, "tool")
    if tool_class != TOOL_CLASSES["MCPTool"]:
        tool.pop("function_specs", None)  # They follow from the functions.
    return {"class": tool_class, **tool}


def _when(condition: Any) -> Dict[str, Any]:
    """A route's ``when``, unless it is always."""
    return {} if condition is None else {"when": condition}


def _mcp_item(item: Any) -> Any:
    """An MCP resource or prompt, saved as JSON text by its field names, as
    MCP names its fields (``_meta``)."""
    item = json.loads(item) if isinstance(item, str) else dict(item)
    if "meta" in item and "_meta" not in item:
        item["_meta"] = item.pop("meta")
    return item


def _class(name: Any, classes: Mapping[str, str], kind: str) -> str:
    if name in classes:
        return classes[name]
    if kind == "tool" and name in TOOL_CLASSES:
        return TOOL_CLASSES[name]
    raise ManifestError(
        f"Unknown {kind} class {name!r}: this manifest predates grafi/v2, which "
        "names classes by import path. Name its class with legacy_classes, as "
        f'legacy_classes={{"{name}": "my_app.module:{name}"}}.'
    )
