"""Tests for reading manifests saved before grafi/v2 (grafi.common.manifest_v1).

The fixtures in tests/common/data are an assistant's ``to_dict()`` as saved
before grafi/v2: with publisher routes (as tests_integration saved it before
grafi/v2), and, before routes, with each node's ``publish_to`` topic names.
"""

import copy
import json
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from unittest.mock import patch

import pytest
from loguru import logger
from mcp.types import Prompt
from mcp.types import Resource

from grafi.agents.react_agent import ReActAgent
from grafi.assistants.assistant import Assistant
from grafi.common.callable_component import CallableComponent
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import resolve_import_ref
from grafi.common.manifest import API_VERSION
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest_v1 import TOOL_CLASSES
from grafi.common.manifest_v1 import TOPIC_CLASSES
from grafi.common.manifest_v1 import upgrade_manifest
from grafi.nodes.conditions import always_true
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.function_calls.impl.synthetic_tool import SyntheticTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool import Tool
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests.wiring import offered_to

DATA = Path(__file__).parent / "data"
ROUTES_MANIFEST = DATA / "legacy_simple_function_call_assistant_manifest.json"
PUBLISH_TO_MANIFEST = DATA / "legacy_publish_to_assistant_manifest.json"

MASK = "****************"


class LocalInfoMock(FunctionCallTool):
    """The function-call tool the fixtures name by its bare name."""

    @llm_function
    def get_weather_mock(self, postcode: str) -> str:
        """Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: The weather information for the given postcode.
        """
        return f"Sunny at {postcode}"

    @llm_function
    def get_population_mock(self, postcode: str) -> str:
        """Function to get population information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve population information.

        Returns:
            str: The population information for the given postcode.
        """
        return f"Many people at {postcode}"


class LegacyAssistant(Assistant):
    """An assistant subclass, which a manifest names by its ``type``."""

    def _construct_workflow(self) -> "LegacyAssistant":
        raise AssertionError("A loaded assistant keeps its saved workflow.")


class Mentions(CallableComponent):
    """A topic's condition of your own, saved as a component before grafi/v2."""

    word: str

    def __call__(self, event: PublishToTopicEvent) -> bool:
        return self.word in str(event.data[-1].content)


LOCAL_INFO_MOCK = f"{__name__}:LocalInfoMock"


@pytest.fixture
def legacy() -> Dict[str, Any]:
    """The assistant saved before grafi/v2, with publisher routes."""
    return json.loads(ROUTES_MANIFEST.read_text())


@pytest.fixture
def legacy_publish_to() -> Dict[str, Any]:
    """The assistant saved before publisher routes, with publish_to lists."""
    return json.loads(PUBLISH_TO_MANIFEST.read_text())


@pytest.fixture
def warnings() -> Iterator[List[str]]:
    """The loguru warnings logged during the test."""
    messages: List[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(handler)


@pytest.fixture
def openai_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    return "fake-openai-key"


def _nodes(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return manifest["spec"]["workflow"]["nodes"]


def _tools(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [node["tool"] for node in _nodes(manifest).values()]


def _mcp_node(resources: List[str], prompts: List[str]) -> Dict[str, Any]:
    """A function-call node with an MCPTool, as saved before grafi/v2."""
    return {
        "class": "Node",
        "node_id": "4eff51ad47344a38a434c605bf630556",
        "name": "FunctionCallNode",
        "type": "FunctionCallNode",
        "oi_span_type": "CHAIN",
        "tool": {
            "class": "MCPTool",
            "base_class": "FunctionCallTool",
            "tool_id": "8924fa0f628440e3b0f0376df723d896",
            "name": "MCPTool",
            "type": "MCPTool",
            "oi_span_type": "TOOL",
            "function_specs": [
                {
                    "name": "hello",
                    "description": "Say hello.",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                }
            ],
            "functions": {},
            "mcp_config": {
                "mcpServers": {
                    "hello": {"url": "http://localhost:8000/mcp/", "transport": "http"}
                }
            },
            "resources": resources,
            "prompts": prompts,
        },
        "subscribed_expressions": [{"topic": "function_call_topic"}],
        "command": {"class": "FunctionCallCommand"},
        "publisher_router": {
            "routes": [
                {
                    "topic": "function_result_topic",
                    "when": {"ref": "grafi.nodes.conditions:always_true"},
                    "from_stage": None,
                }
            ]
        },
    }


# --------------------------------------------------------------------------- #
# The upgraded manifest
# --------------------------------------------------------------------------- #


def test_upgrade_wraps_the_assistant_in_an_envelope(legacy: Dict[str, Any]) -> None:
    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    assert upgraded["apiVersion"] == API_VERSION
    assert upgraded["kind"] == "Assistant"
    spec = upgraded["spec"]
    assert spec["class"] == "grafi.assistants.assistant:Assistant"
    assert {key: spec[key] for key in ("assistant_id", "name", "type")} == {
        "assistant_id": "b6f603c5d6804e97a85958908b8d5d46",
        "name": "SimpleFunctionCallAssistant",
        "type": "SimpleFunctionCallAssistant",
    }
    workflow = spec["workflow"]
    assert workflow["class"] == (
        "grafi.workflows.impl.event_driven_workflow:EventDrivenWorkflow"
    )
    assert workflow["workflow_id"] == "bb1edfa98ea44b7684052737f69ef4d1"
    assert {name: topic["class"] for name, topic in workflow["topics"].items()} == {
        "agent_input_topic": "grafi.topics.topic_impl.input_topic:InputTopic",
        "function_call_topic": "grafi.topics.topic_impl.topic:Topic",
        "agent_output_topic": "grafi.topics.topic_impl.output_topic:OutputTopic",
        "function_result_topic": "grafi.topics.topic_impl.topic:Topic",
    }


def test_upgrade_leaves_its_input_unchanged(legacy: Dict[str, Any]) -> None:
    saved = copy.deepcopy(legacy)

    upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    assert legacy == saved


def test_bare_tool_names_become_import_paths(legacy: Dict[str, Any]) -> None:
    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    nodes = _nodes(upgraded)
    assert {name: node["class"] for name, node in nodes.items()} == dict.fromkeys(
        nodes, "grafi.nodes.node:Node"
    )
    assert {name: node["tool"]["class"] for name, node in nodes.items()} == {
        "OpenAIInputNode": "grafi.tools.llms.impl.openai_tool:OpenAITool",
        "FunctionCallNode": LOCAL_INFO_MOCK,
        "OpenAIOutputNode": "grafi.tools.llms.impl.openai_tool:OpenAITool",
    }


@pytest.mark.parametrize("name, path", sorted(TOOL_CLASSES.items()))
def test_known_tool_names_name_grafi_tool_classes(name: str, path: str) -> None:
    tool_class = resolve_import_ref(path)

    assert tool_class.__name__ == name
    assert issubclass(tool_class, Tool)


@pytest.mark.parametrize("topic_type, path", sorted(TOPIC_CLASSES.items()))
def test_topic_types_name_grafi_topic_classes(topic_type: str, path: str) -> None:
    topic_class = resolve_import_ref(path)

    assert issubclass(topic_class, TopicBase)
    assert topic_class().type.value == topic_type


def test_masked_secrets_are_dropped(legacy: Dict[str, Any]) -> None:
    assert MASK in json.dumps(legacy)

    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    assert MASK not in json.dumps(upgraded)
    assert all("api_key" not in tool for tool in _tools(upgraded))


def test_what_grafi_v2_does_not_load_is_dropped(legacy: Dict[str, Any]) -> None:
    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    nodes = _nodes(upgraded)
    assert all("command" not in node for node in nodes.values())
    assert all("base_class" not in tool for tool in _tools(upgraded))
    routes = nodes["OpenAIInputNode"]["publisher_router"]["routes"]
    assert routes == [
        {
            "topic": "function_call_topic",
            "when": {"ref": "grafi.nodes.conditions:has_tool_call"},
        },
        {
            "topic": "agent_output_topic",
            "when": {"ref": "grafi.nodes.conditions:has_text_response"},
        },
    ]


def test_publish_to_lists_become_routes(legacy_publish_to: Dict[str, Any]) -> None:
    upgraded = upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})

    nodes = _nodes(upgraded)
    assert all("publish_to" not in node for node in nodes.values())
    assert {
        name: node["publisher_router"]["routes"] for name, node in nodes.items()
    } == {
        "OpenAIInputNode": [
            {
                "topic": "function_call_topic",
                "when": {"ref": "grafi.nodes.conditions:has_tool_call"},
            },
            {
                "topic": "agent_output_topic",
                "when": {"ref": "grafi.nodes.conditions:has_text_response"},
            },
        ],
        "FunctionCallNode": [{"topic": "function_result_topic"}],
        "OpenAIOutputNode": [
            {
                "topic": "agent_output_topic",
                "when": {"ref": "grafi.nodes.conditions:has_text_response"},
            }
        ],
    }


def test_publish_to_manifest_loads(
    legacy_publish_to: Dict[str, Any], openai_key: str
) -> None:
    assistant = Assistant.from_manifest(
        legacy_publish_to, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    workflow = assistant.workflow
    node = workflow.nodes["OpenAIInputNode"]
    assert [topic.name for topic in node.publish_to] == [
        "function_call_topic",
        "agent_output_topic",
    ]
    assert all(topic is workflow.topics[topic.name] for topic in node.publish_to)


def test_topic_conditions_move_to_the_routes_publishing_to_them(
    legacy_publish_to: Dict[str, Any], openai_key: str, warnings: List[str]
) -> None:
    """Routing moved from topics to routes: each topic's condition becomes the
    `when` of the routes to it, grafi's own predicates where they now are."""
    topics = legacy_publish_to["workflow"]["topics"]
    assert all("condition" in topic for topic in topics.values())

    upgraded = upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})

    assert warnings == []  # Moved as it was, so nothing to warn of.

    upgraded_topics = upgraded["spec"]["workflow"]["topics"]
    assert all("condition" not in topic for topic in upgraded_topics.values())
    assistant = Assistant.from_manifest(upgraded)
    nodes = assistant.workflow.nodes
    routes = nodes["OpenAIInputNode"].publisher_router.routes
    assert [route.when for route in routes] == [has_tool_call, has_text_response]
    [result] = nodes["FunctionCallNode"].publisher_router.routes
    assert result.when is always_true


def test_a_condition_of_a_topic_no_node_publishes_to_is_refused(
    legacy_publish_to: Dict[str, Any],
) -> None:
    """An input topic's condition filtered the request's input; no route can
    hold it, so it is not dropped silently."""
    topics = legacy_publish_to["workflow"]["topics"]
    topics["agent_input_topic"]["condition"] = {"ref": "my_app.routes:is_long"}

    with pytest.raises(ManifestError, match="'agent_input_topic' has a condition"):
        upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})


def test_a_bare_pickled_condition_is_refused_as_pickled(
    legacy_publish_to: Dict[str, Any],
) -> None:
    """As grafi 0.0.30 to 0.0.34 saved one, before naming whether a node
    publishes to its topic."""
    topics = legacy_publish_to["workflow"]["topics"]
    topics["agent_input_topic"]["condition"] = "gASVAAAAAAAAAACMBGJsb2KULg=="

    with pytest.raises(ManifestError, match="saved by pickle"):
        upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})


def test_a_topic_condition_of_your_own_is_kept(
    legacy_publish_to: Dict[str, Any],
) -> None:
    topics = legacy_publish_to["workflow"]["topics"]
    topics["function_result_topic"]["condition"] = {"ref": "my_app.routes:ok"}

    upgraded = upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})

    [route] = _nodes(upgraded)["FunctionCallNode"]["publisher_router"]["routes"]
    assert route == {
        "topic": "function_result_topic",
        "when": {"ref": "my_app.routes:ok"},
    }


@pytest.mark.parametrize(
    "condition, when",
    [
        ({"ref": "grafi.topics.topic_base:always_true"}, None),
        (None, None),
        (
            {"ref": "grafi.topics.conditions:has_tool_call"},
            {"ref": "grafi.nodes.conditions:has_tool_call"},
        ),
        (
            {"ref": "grafi.topics.conditions:has_no_tool_call"},
            {"ref": "grafi.nodes.conditions:has_no_tool_call"},
        ),
        ({"ref": "my_app.routes:ok"}, {"ref": "my_app.routes:ok"}),
    ],
    ids=["always", "none", "grafi", "grafi other", "your own"],
)
def test_a_topic_condition_becomes_the_when_of_its_routes(
    legacy_publish_to: Dict[str, Any], condition: Any, when: Any
) -> None:
    topics = legacy_publish_to["workflow"]["topics"]
    topics["agent_output_topic"]["condition"] = condition

    upgraded = upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})

    expected = {
        "topic": "agent_output_topic",
        **({} if when is None else {"when": when}),
    }
    nodes = _nodes(upgraded)
    assert nodes["OpenAIInputNode"]["publisher_router"]["routes"][1] == expected
    assert nodes["OpenAIOutputNode"]["publisher_router"]["routes"] == [expected]


def test_a_topic_condition_saved_as_a_component_loads_on_its_routes(
    legacy_publish_to: Dict[str, Any], openai_key: str
) -> None:
    topics = legacy_publish_to["workflow"]["topics"]
    topics["agent_output_topic"]["condition"] = {
        "component": f"{__name__}:Mentions",
        "config": {"word": "done"},
    }

    assistant = Assistant.from_manifest(
        legacy_publish_to, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    nodes = assistant.workflow.nodes
    for name in ("OpenAIInputNode", "OpenAIOutputNode"):
        when = nodes[name].publisher_router.routes[-1].when
        assert isinstance(when, Mentions) and when.word == "done"
    manifest = assistant.to_manifest()
    [route] = _nodes(manifest)["OpenAIOutputNode"]["publisher_router"]["routes"]
    assert route["when"] == {"class": f"{__name__}:Mentions", "word": "done"}


# --------------------------------------------------------------------------- #
# Callables saved as components before grafi/v2: {"component": path, "config"}
# --------------------------------------------------------------------------- #

LEGACY_MENTIONS = {"component": f"{__name__}:Mentions", "config": {"word": "done"}}
UPGRADED_MENTIONS = {"class": f"{__name__}:Mentions", "word": "done"}


def test_a_route_condition_saved_as_a_component_is_upgraded(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    node = legacy["workflow"]["nodes"]["FunctionCallNode"]
    node["publisher_router"]["routes"][0]["when"] = LEGACY_MENTIONS
    classes = {"LocalInfoMock": LOCAL_INFO_MOCK}

    upgraded = upgrade_manifest(legacy, classes)

    [route] = _nodes(upgraded)["FunctionCallNode"]["publisher_router"]["routes"]
    assert route == {"topic": "function_result_topic", "when": UPGRADED_MENTIONS}
    assistant = Assistant.from_manifest(legacy, legacy_classes=classes)
    [loaded] = assistant.workflow.nodes["FunctionCallNode"].publisher_router.routes
    assert isinstance(loaded.when, Mentions) and loaded.when.word == "done"


def _legacy_tool(name: str, **fields: Any) -> Dict[str, Any]:
    """A grafi tool as saved before grafi/v2, with ``fields`` of its own."""
    return {
        "class": name,
        "base_class": "Tool",
        "tool_id": "c3c4a8d9e1f24b0e9a7d6c5b4a392817",
        "name": name,
        "type": name,
        "oi_span_type": "TOOL",
        **fields,
    }


@pytest.mark.parametrize(
    "tool, field",
    [
        (_legacy_tool("FunctionTool", function=LEGACY_MENTIONS), "function"),
        (
            _legacy_tool(
                "AgentCallingTool",
                agent_name="helper",
                agent_description="Helps.",
                argument_description="What with.",
                agent_call=LEGACY_MENTIONS,
            ),
            "agent_call",
        ),
    ],
    ids=["function", "agent_call"],
)
def test_a_tools_callable_saved_as_a_component_is_upgraded(
    legacy: Dict[str, Any], openai_key: str, tool: Dict[str, Any], field: str
) -> None:
    legacy["workflow"]["nodes"]["FunctionCallNode"]["tool"] = tool

    upgraded = upgrade_manifest(legacy, {})

    assert _nodes(upgraded)["FunctionCallNode"]["tool"][field] == UPGRADED_MENTIONS
    loaded = Assistant.from_manifest(upgraded).workflow.nodes["FunctionCallNode"].tool
    assert type(loaded).__name__ == tool["class"]
    callable_ = getattr(loaded, field)
    assert isinstance(callable_, Mentions) and callable_.word == "done"
    assert loaded.model_dump(mode="json")[field] == UPGRADED_MENTIONS


def test_a_function_call_tools_functions_saved_as_components_are_upgraded(
    legacy: Dict[str, Any],
) -> None:
    """Each value of ``functions`` is a callable, upgraded as any is; a
    reference is kept as it is."""
    tool = legacy["workflow"]["nodes"]["FunctionCallNode"]["tool"]
    tool["functions"] = {
        "mentions": LEGACY_MENTIONS,
        "always": {"ref": "grafi.nodes.conditions:always_true"},
    }

    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    assert _nodes(upgraded)["FunctionCallNode"]["tool"]["functions"] == {
        "mentions": UPGRADED_MENTIONS,
        "always": {"ref": "grafi.nodes.conditions:always_true"},
    }


def test_a_callable_saved_as_grafi_v2_saves_it_is_kept(legacy: Dict[str, Any]) -> None:
    node = legacy["workflow"]["nodes"]["FunctionCallNode"]
    node["publisher_router"]["routes"][0]["when"] = UPGRADED_MENTIONS
    node["tool"]["functions"] = {"ok": {"ref": "my_app.routes:ok"}}

    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})

    upgraded_node = _nodes(upgraded)["FunctionCallNode"]
    assert upgraded_node["publisher_router"]["routes"][0]["when"] == UPGRADED_MENTIONS
    assert upgraded_node["tool"]["functions"] == {"ok": {"ref": "my_app.routes:ok"}}


def _synthetic_node() -> Dict[str, Any]:
    """A function-call node with a SyntheticTool, as saved before grafi/v2:
    its models as the JSON schemas they made."""
    return {
        "class": "Node",
        "node_id": "5d0b4ba3a3a74c3a8f2e0c1c9f6e8d11",
        "name": "FunctionCallNode",
        "type": "FunctionCallNode",
        "oi_span_type": "CHAIN",
        "tool": {
            "class": "SyntheticTool",
            "base_class": "FunctionCallTool",
            "tool_id": "c3c4a8d9e1f24b0e9a7d6c5b4a392817",
            "name": "SyntheticTool",
            "type": "SyntheticTool",
            "oi_span_type": "TOOL",
            "tool_name": "forecast",
            "description": "Forecast the weather.",
            "input_schema": {
                "type": "object",
                "properties": {"postcode": {"type": "string"}},
                "required": ["postcode"],
            },
            "output_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
            "model": "gpt-4o-mini",
            "openai_api_key": MASK,
        },
        "subscribed_expressions": [{"topic": "function_call_topic"}],
        "command": {"class": "FunctionCallCommand"},
        "publisher_router": {
            "routes": [{"topic": "function_result_topic", "from_stage": None}]
        },
    }


def test_synthetic_tool_schemas_become_its_models(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    node = _synthetic_node()
    legacy["workflow"]["nodes"]["FunctionCallNode"] = node

    upgraded = upgrade_manifest(legacy, {})

    tool = _nodes(upgraded)["FunctionCallNode"]["tool"]
    assert tool["class"] == TOOL_CLASSES["SyntheticTool"]
    assert "input_schema" not in tool and "output_schema" not in tool
    assert tool["input_model"] == node["tool"]["input_schema"]
    assert tool["output_model"] == node["tool"]["output_schema"]
    assert "openai_api_key" not in tool  # Masked, so read from its variable.
    loaded = Assistant.from_manifest(upgraded).workflow.nodes["FunctionCallNode"]
    synthetic = loaded.tool
    assert isinstance(synthetic, SyntheticTool)
    assert synthetic.input_model == node["tool"]["input_schema"]
    assert synthetic.output_model == node["tool"]["output_schema"]
    assert synthetic.openai_api_key == openai_key
    [spec] = synthetic.get_function_specs()
    assert (spec.name, spec.description) == ("forecast", "Forecast the weather.")


def test_mcp_resources_and_prompts_saved_as_json_text_are_parsed(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    resource = Resource(uri="file:///notes.txt", name="notes", mimeType="text/plain")
    prompt = Prompt(name="greeting", description="Greet someone.")
    legacy["workflow"]["nodes"]["FunctionCallNode"] = _mcp_node(
        [resource.model_dump_json()], [prompt.model_dump_json()]
    )

    upgraded = upgrade_manifest(legacy, {})

    tool = _nodes(upgraded)["FunctionCallNode"]["tool"]
    assert tool["class"] == TOOL_CLASSES["MCPTool"]
    # Saved by field name, they load by MCP's names: "meta" becomes "_meta".
    assert tool["resources"] == [_by_alias(resource.model_dump_json())]
    assert tool["prompts"] == [_by_alias(prompt.model_dump_json())]
    loaded = Assistant.from_manifest(upgraded).workflow.nodes["FunctionCallNode"].tool
    assert isinstance(loaded, MCPTool)
    assert [(r.name, str(r.uri), r.mimeType) for r in loaded.resources] == [
        ("notes", "file:///notes.txt", "text/plain")
    ]
    assert [(p.name, p.description) for p in loaded.prompts] == [
        ("greeting", "Greet someone.")
    ]
    assert loaded.mcp_config["mcpServers"]["hello"]["transport"] == "http"
    assert [spec.name for spec in loaded.get_function_specs()] == ["hello"]


def _by_alias(text: str) -> Dict[str, Any]:
    item = json.loads(text)
    item["_meta"] = item.pop("meta")
    return item


def test_legacy_mcp_meta_survives(legacy: Dict[str, Any], openai_key: str) -> None:
    resource = Resource(uri="file:///n.txt", name="n", _meta={"k": 1})
    legacy["workflow"]["nodes"]["FunctionCallNode"] = _mcp_node(
        [resource.model_dump_json()], []
    )

    loaded = Assistant.from_manifest(upgrade_manifest(legacy, {}))

    [restored] = loaded.workflow.nodes["FunctionCallNode"].tool.resources
    assert restored.meta == {"k": 1}


def test_empty_mcp_resources_and_prompts_are_dropped(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    legacy["workflow"]["nodes"]["FunctionCallNode"] = _mcp_node([], [])

    upgraded = upgrade_manifest(legacy, {})

    tool = _nodes(upgraded)["FunctionCallNode"]["tool"]
    assert "resources" not in tool and "prompts" not in tool
    loaded = Assistant.from_manifest(upgraded).workflow.nodes["FunctionCallNode"].tool
    assert (loaded.resources, loaded.prompts) == ([], [])


# --------------------------------------------------------------------------- #
# Classes grafi does not know
# --------------------------------------------------------------------------- #


def test_unknown_tool_class_raises_naming_legacy_classes(
    legacy: Dict[str, Any],
) -> None:
    match = r"Unknown tool class 'LocalInfoMock'.*legacy_classes"
    with pytest.raises(ManifestError, match=match):
        upgrade_manifest(legacy, {})
    with pytest.raises(ManifestError, match=match):
        Assistant.from_manifest(legacy)


def test_unknown_node_class_raises(legacy: Dict[str, Any]) -> None:
    legacy["workflow"]["nodes"]["OpenAIInputNode"]["class"] = "CustomNode"
    classes = {"LocalInfoMock": LOCAL_INFO_MOCK}

    with pytest.raises(ManifestError, match="Unknown node class 'CustomNode'"):
        upgrade_manifest(legacy, classes)
    upgraded = upgrade_manifest(legacy, {**classes, "CustomNode": Node})
    assert _nodes(upgraded)["OpenAIInputNode"]["class"] == "grafi.nodes.node:Node"


def test_unknown_topic_type_raises(legacy: Dict[str, Any]) -> None:
    legacy["workflow"]["topics"]["function_call_topic"]["type"] = "CustomTopic"
    with pytest.raises(ManifestError, match="Unknown topic type 'CustomTopic'"):
        upgrade_manifest(legacy, {"LocalInfoMock": LOCAL_INFO_MOCK})


def test_dict_without_a_workflow_is_not_a_manifest() -> None:
    with pytest.raises(ManifestError, match="Not a manifest"):
        upgrade_manifest({"name": "SimpleFunctionCallAssistant"}, {})


@pytest.mark.parametrize("named_as", [LocalInfoMock, LOCAL_INFO_MOCK])
def test_legacy_classes_name_classes_or_import_paths(
    legacy: Dict[str, Any], named_as: Any
) -> None:
    upgraded = upgrade_manifest(legacy, {"LocalInfoMock": named_as})

    assert _nodes(upgraded)["FunctionCallNode"]["tool"]["class"] == LOCAL_INFO_MOCK


def test_the_assistant_loads_as_the_class_loading_it(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    """A manifest before grafi/v2 names its assistant's class only by its
    ``type``: loaded by an assistant class, it is one of that class."""
    classes = {"LocalInfoMock": LocalInfoMock}
    with patch.object(
        ReActAgent,
        "_construct_workflow",
        side_effect=AssertionError("the saved workflow is rebuilt"),
    ):
        agent = ReActAgent.from_manifest(legacy, legacy_classes=classes)

    assert type(agent) is ReActAgent
    assert agent.assistant_id == "b6f603c5d6804e97a85958908b8d5d46"
    assert agent.workflow.workflow_id == "bb1edfa98ea44b7684052737f69ef4d1"
    assert type(LegacyAssistant.from_manifest(legacy, legacy_classes=classes)) is (
        LegacyAssistant
    )
    assert type(Assistant.from_manifest(legacy, legacy_classes=classes)) is Assistant
    assert type(Component.from_manifest(legacy, legacy_classes=classes)) is Assistant
    upgraded = upgrade_manifest(legacy, classes, ReActAgent)
    assert upgraded["spec"]["class"] == "grafi.agents.react_agent:ReActAgent"
    assert upgrade_manifest(legacy, classes, Node)["spec"]["class"] == (
        "grafi.assistants.assistant:Assistant"
    )


def test_a_react_agent_saves_only_its_workflow(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    agent = ReActAgent.from_manifest(
        legacy, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    manifest = json.loads(json.dumps(agent.to_manifest()))

    spec = manifest["spec"]
    assert spec["class"] == "grafi.agents.react_agent:ReActAgent"
    assert not {"api_key", "system_prompt", "function_call_tool", "model"} & set(spec)
    again = ReActAgent.from_manifest(manifest)
    assert again.workflow.workflow_id == agent.workflow.workflow_id
    assert again.to_manifest() == manifest
    spec["model"] = "gpt-4o"  # What it builds a workflow from, never saved.
    with pytest.raises(ManifestError, match="ReActAgent.model is never saved"):
        ReActAgent.from_manifest(manifest)


def test_a_v1_manifest_holds_an_assistant(legacy: Dict[str, Any]) -> None:
    with pytest.raises(ManifestError, match="is not a subclass of EventDrivenWorkflow"):
        EventDrivenWorkflow.from_manifest(
            legacy, legacy_classes={"LocalInfoMock": LocalInfoMock}
        )


def test_legacy_classes_name_the_assistants_class(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    classes = {
        "LocalInfoMock": LocalInfoMock,
        "SimpleFunctionCallAssistant": LegacyAssistant,
    }

    assistant = Assistant.from_manifest(legacy, legacy_classes=classes)

    assert type(assistant) is LegacyAssistant
    assert assistant.workflow.workflow_id == "bb1edfa98ea44b7684052737f69ef4d1"


# --------------------------------------------------------------------------- #
# Loading the upgraded manifest
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["dict", "path", "text"])
def test_legacy_manifest_loads(
    legacy: Dict[str, Any], openai_key: str, source: str
) -> None:
    manifest: Any = {
        "dict": legacy,
        "path": ROUTES_MANIFEST,
        "text": Path(ROUTES_MANIFEST).read_text(encoding="utf-8"),
    }[source]

    assistant = Assistant.from_manifest(
        manifest, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    assert type(assistant) is Assistant
    assert assistant.assistant_id == "b6f603c5d6804e97a85958908b8d5d46"
    workflow = assistant.workflow
    assert isinstance(workflow, EventDrivenWorkflow)
    assert workflow.workflow_id == "bb1edfa98ea44b7684052737f69ef4d1"
    assert {name: type(topic) for name, topic in workflow.topics.items()} == {
        "agent_input_topic": InputTopic,
        "function_call_topic": Topic,
        "agent_output_topic": OutputTopic,
        "function_result_topic": Topic,
    }
    nodes = workflow.nodes
    assert {name: node.node_id for name, node in nodes.items()} == {
        "OpenAIInputNode": "6f9085b566e444cdb32156f517015794",
        "FunctionCallNode": "8776600c35e6460684b5648921e01cfd",
        "OpenAIOutputNode": "62b65d7f45be4a6fa37ad8b24e0dd7e2",
    }
    assert {name: node.tool.tool_id for name, node in nodes.items()} == {
        "OpenAIInputNode": "3ff8a415b92342ad9455befa827cb8ac",
        "FunctionCallNode": "a9e1056de5b847729bfdb909fb6ce849",
        "OpenAIOutputNode": "8bbe6f433b724b47b182db34da686eba",
    }


def test_loaded_legacy_assistant_is_wired(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    assistant = Assistant.from_manifest(
        legacy, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    nodes = assistant.workflow.nodes
    llm = nodes["OpenAIInputNode"].tool
    assert isinstance(llm, OpenAITool)
    assert (llm.name, llm.model, llm.api_key) == (
        "UserInputLLM",
        "gpt-4o-mini",
        openai_key,  # The masked key, read from its variable.
    )
    routes = nodes["OpenAIInputNode"].publisher_router.routes
    assert [(r.topic.name, r.when) for r in routes] == [
        ("function_call_topic", has_tool_call),
        ("agent_output_topic", has_text_response),
    ]
    assert nodes["FunctionCallNode"].publisher_router.routes[0].when is always_true
    functions = nodes["FunctionCallNode"].tool
    assert isinstance(functions, LocalInfoMock)
    assert functions._functions() == LocalInfoMock._methods
    # The function-call node's functions are offered to the LLM calling it.
    assert offered_to(assistant.workflow, "OpenAIInputNode") == [
        "get_weather_mock",
        "get_population_mock",
    ]
    assert offered_to(assistant.workflow, "OpenAIOutputNode") == []


def test_loaded_legacy_assistant_saves_as_grafi_v2(
    legacy: Dict[str, Any], openai_key: str
) -> None:
    assistant = Assistant.from_manifest(
        legacy, legacy_classes={"LocalInfoMock": LocalInfoMock}
    )

    manifest = json.loads(json.dumps(assistant.to_manifest()))

    assert manifest["apiVersion"] == API_VERSION
    tools = _tools(manifest)
    assert [tool.get("api_key") for tool in tools] == [
        {"env": "OPENAI_API_KEY"},
        None,
        {"env": "OPENAI_API_KEY"},
    ]
    assert Assistant.from_manifest(manifest).to_manifest() == manifest


def test_a_pickled_condition_is_refused_by_name(
    legacy_publish_to: Dict[str, Any],
) -> None:
    """grafi before v2 pickled a topic condition it could not name: loading it
    would run any code it holds, so it is refused, and not shown."""
    pickled = "gAWVGgIAAAAAAACMF2Nsb3VkcGlja2xl" * 20
    legacy_publish_to["workflow"]["topics"]["agent_output_topic"]["condition"] = {
        "base64": pickled
    }

    match = "condition of the topic 'agent_output_topic' saved by pickle"
    with pytest.raises(ManifestError, match=match) as raised:
        upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})
    assert pickled not in str(raised.value)


def test_a_tool_saved_on_its_own_before_grafi_v2_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As ToolFactory.from_dict() read a tool's to_dict()."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    saved = {
        "class": "OpenAITool",
        "base_class": "Tool",
        "tool_id": "t1",
        "name": "Planner",
        "type": "OpenAITool",
        "oi_span_type": "LLM",
        "api_key": "****************",
        "model": "gpt-4o-mini",
    }

    tool = Tool.from_manifest(saved)

    assert type(tool) is OpenAITool
    assert (tool.tool_id, tool.name, tool.api_key) == ("t1", "Planner", "sk-fake")


def test_a_topic_saved_on_its_own_before_grafi_v2_loads_unless_conditioned() -> None:
    """Routes hold a topic's condition now: alone, it has none to give it."""
    topic = TopicBase.from_manifest({"name": "answers", "type": "Topic"})
    assert (type(topic), topic.name) == (Topic, "answers")

    conditioned = {
        "name": "answers",
        "type": "Topic",
        "condition": {"ref": "my_app.routes:ok"},
    }
    with pytest.raises(ManifestError, match="has a condition, which routes now hold"):
        TopicBase.from_manifest(conditioned)


class RemoteSearch(FunctionCallTool):
    """Calls its functions elsewhere."""


def test_a_tool_of_your_own_saved_before_grafi_v2_is_named_by_legacy_classes() -> None:
    """grafi before v2 wrote its base class, as LLMTool or FunctionCallTool.
    Its specs it derived again on loading, as grafi does: a saved one stale
    since, as of a function removed, is not offered."""
    saved = {
        "class": "RemoteSearch",
        "base_class": "FunctionCallTool",
        "name": "RemoteSearch",
        "function_specs": [
            {"name": "search", "description": "Search.", "parameters": {}}
        ],
    }

    with pytest.raises(ManifestError, match="Unknown tool class 'RemoteSearch'"):
        Tool.from_manifest(saved)
    tool = Tool.from_manifest(saved, legacy_classes={"RemoteSearch": RemoteSearch})

    assert type(tool) is RemoteSearch
    assert tool.get_function_specs() == []


@pytest.mark.parametrize("text", ["", "get_weather", "ABC123"])
def test_only_pickles_text_is_taken_for_a_pickle(text: str) -> None:
    """Other text is left as it is (a tool of yours may hold text so named);
    one in a function's field is refused when loaded, as saved by its name
    only, as by grafi 0.0.29."""
    from grafi.common.callable_ref import deserialize_callable
    from grafi.common.manifest_v1 import _callable

    assert _callable(text) == text
    with pytest.raises(ManifestError, match="saved by pickle"):
        _callable("gASVAAAAAAAAAACMBGJsb2KULg==")
    with pytest.raises(ManifestError, match="saved by its name only"):
        deserialize_callable(text)


def test_an_accept_all_condition_of_either_module_is_none(
    legacy_publish_to: Dict[str, Any],
) -> None:
    """always_true, where 0.0.36 had it or where it is now: no condition, so
    an input topic may have it."""
    topics = legacy_publish_to["workflow"]["topics"]
    topics["agent_input_topic"]["condition"] = {
        "ref": "grafi.nodes.conditions:always_true"
    }

    upgraded = upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})

    upgraded_topics = upgraded["spec"]["workflow"]["topics"]
    assert "condition" not in upgraded_topics["agent_input_topic"]


def test_an_assistant_of_0_0_29_is_refused_up_front(
    legacy_publish_to: Dict[str, Any],
) -> None:
    """Its nodes publish to whole topics, as no later grafi saved them."""
    node = legacy_publish_to["workflow"]["nodes"]["OpenAIOutputNode"]
    node["publish_to"] = [{"name": "agent_output_topic", "condition": {}}]

    with pytest.raises(ManifestError, match="saved by grafi 0.0.29 or earlier"):
        upgrade_manifest(legacy_publish_to, {"LocalInfoMock": LOCAL_INFO_MOCK})
