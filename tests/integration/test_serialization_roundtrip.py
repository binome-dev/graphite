"""End-to-end manifests: assistants built, saved as JSON, loaded back, and run.

An assistant's manifest holds its whole workflow: every tool kind grafi saves
(LLMs, function-call tools and their subclasses, search, synthetic,
agent-calling and MCP tools, function tools), the pickle-free callable forms
(module-level references, CallableComponent configs, and ``@llm_function``
methods, which load with their class), and its secrets, as the environment
variables they come from. Loading one rebuilds it with the same classes, fields
and ids (which recovering an interrupted request relies on), and links the
function-call nodes' functions to the LLMs calling them again.
"""

import json
import uuid
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest.mock import patch

import pytest
from mcp.types import Prompt
from mcp.types import Resource
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.assistants.assistant import Assistant
from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.manifest import ManifestError
from grafi.common.manifest import env_secret
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.conditions import has_text_response
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.function_calls.impl.synthetic_tool import SyntheticTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm import LLM
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

ENV = {
    "OPENAI_API_KEY": "fake-openai-key",
    "ANTHROPIC_API_KEY": "fake-anthropic-key",
    "TAVILY_API_KEY": "fake-tavily-key",
}

MCP_CONFIG = {
    "mcpServers": {
        "hello": {
            "url": "http://localhost:8000/mcp/",
            "transport": "http",
            "headers": {"Authorization": "Bearer ${HELLO_MCP_TOKEN}"},
        }
    }
}


@pytest.fixture(autouse=True)
def secrets(monkeypatch: pytest.MonkeyPatch) -> Dict[str, str]:
    """The environment variables the tools read their keys from."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return ENV


# --------------------------------------------------------------------------- #
# Module-level building blocks, which manifests name by import path
# --------------------------------------------------------------------------- #


class Weather(BaseModel):
    summary: str


class WeatherQuery(BaseModel):
    postcode: str


class WeatherReport(BaseModel):
    summary: str
    temperature: float


def get_weather(postcode: str) -> str:
    """Get the weather at a postcode.

    Args:
        postcode (str): Where to get the weather.
    """
    return f"Sunny at {postcode}"


def ask_expert(invoke_context: InvokeContext, prompt: Message) -> Dict[str, Any]:
    return {"content": f"The expert says: {prompt.content}"}


def shout(messages: Messages) -> str:
    return (messages[-1].content or "").upper()


def has_content(event: PublishToTopicEvent) -> bool:
    return event.data[-1].content is not None


class Prefixer(CallableComponent):
    """A function tool's function, saved as its config."""

    prefix: str

    def __call__(self, messages: Messages) -> str:
        return f"{self.prefix}{messages[-1].content}"


class MinContentLength(CallableComponent):
    """A route's predicate, saved as its config."""

    minimum: int

    def __call__(self, event: PublishToTopicEvent) -> bool:
        return len(event.data[-1].content or "") >= self.minimum


class GreetTool(FunctionCallTool):
    """A function-call tool subclass: its method loads with its class."""

    name: str = "GreetTool"
    type: str = "GreetTool"
    greeting: str = "Hello"

    @llm_function
    def greet(self, name: str) -> str:
        """Greet someone.

        Args:
            name (str): Who to greet.
        """
        return f"{self.greeting}, {name}!"


class ScriptedLLM(OpenAITool):
    """An LLM that calls each function it is offered, with the ``arguments``
    given for it, then answers with their results. What it calls is what the
    workflow linked to it."""

    name: str = "ScriptedLLM"
    arguments: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        results = sorted(str(m.content) for m in input_data if m.role == "tool")
        if results:
            yield [Message(role="assistant", content=" | ".join(results))]
            return
        calls = [
            ChatCompletionMessageToolCall(
                id=f"call_{spec.name}",
                type="function",
                function=Function(
                    name=spec.name,
                    arguments=json.dumps(self.arguments.get(spec.name, {})),
                ),
            )
            for spec in self.get_function_specs()
        ]
        yield [Message(role="assistant", content=None, tool_calls=calls or None)]


def _runnable_workflow(
    greeting: str = "Hi", prefix: str = ">> ", api_key: Optional[str] = None
) -> EventDrivenWorkflow:
    """Input -> ScriptedLLM <-> (GreetTool + get_weather) -> Prefixer -> Output.
    Runs without a model."""
    agent_input = InputTopic(name="agent_input")
    function_call = Topic(name="function_call")
    function_result = Topic(name="function_result")
    answer = Topic(name="answer")
    agent_output = OutputTopic(name="agent_output")
    llm = ScriptedLLM(
        name="Planner",
        api_key=api_key,
        arguments={"get_weather": {"postcode": "2000"}, "greet": {"name": "Ada"}},
    )
    helper = GreetTool(
        name="Helper", greeting=greeting, functions={"get_weather": get_weather}
    )
    return (
        EventDrivenWorkflow.builder()
        .name("runnable_workflow")
        .node(
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result)
                .build()
            )
            .tool(llm)
            .publish_to(function_call, when=has_tool_call)
            .publish_to(answer, when=has_text_response)
            .build()
        )
        .node(
            Node.builder()
            .name("FunctionCallNode")
            .subscribe(function_call)
            .tool(helper)
            .publish_to(function_result)
            .build()
        )
        .node(
            Node.builder()
            .name("FormatNode")
            .subscribe(answer)
            .tool(FunctionTool(name="Format", function=Prefixer(prefix=prefix)))
            .publish_to(agent_output, when=has_content)
            .build()
        )
        .build()
    )


class WeatherAssistant(Assistant):
    """An assistant subclass with fields of its own, which build its
    workflow."""

    name: str = "WeatherAssistant"
    type: str = "WeatherAssistant"
    api_key: Optional[str] = env_secret("OPENAI_API_KEY")
    greeting: str = "Hi"
    prefix: str = ">> "

    def _construct_workflow(self) -> "WeatherAssistant":
        self.workflow = _runnable_workflow(self.greeting, self.prefix, self.api_key)
        return self


def _kitchen_sink() -> Assistant:
    """An assistant with a node for each kind of tool. It is never run."""
    agent_input = InputTopic(name="agent_input")
    function_call = Topic(name="function_call")
    function_result = Topic(name="function_result")
    review = Topic(name="review")
    agent_output = OutputTopic(name="agent_output")
    planner = (
        OpenAITool.builder()
        .name("Planner")
        .model("gpt-4o-mini")
        .system_message("Plan.")
        .chat_params({"temperature": 0.1, "response_format": Weather})
        .build()
    )
    function_call_tools = {
        "HelperNode": GreetTool(
            name="Helper",
            greeting="Hi",
            functions={"get_weather": get_weather},
            on_error="raise",
        ),
        "SearchNode": TavilyTool.builder()
        .name("Search")
        .search_depth("basic")
        .max_tokens(1234)
        .build(),
        "DuckNode": DuckDuckGoTool(name="Duck", fixed_max_results=3),
        "SyntheticNode": SyntheticTool.builder()
        .tool_name("forecast")
        .description("Forecast the weather.")
        .input_model(WeatherQuery)
        .output_model(WeatherReport)
        .model("gpt-4o-mini")
        .build(),
        "AgentNode": AgentCallingTool.builder()
        .agent_name("expert")
        .agent_description("Ask an expert.")
        .argument_description("The question.")
        .agent_call(ask_expert)
        .build(),
        "MCPNode": MCPTool(
            name="MCP",
            mcp_config=MCP_CONFIG,
            function_specs=[
                FunctionSpec.model_validate(
                    {
                        "name": "hello",
                        "description": "Say hello.",
                        "parameters": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    }
                )
            ],
            resources=[Resource(uri="file:///notes.txt", name="notes")],
            prompts=[Prompt(name="greeting", description="Greet someone.")],
        ),
    }
    builder = (
        EventDrivenWorkflow.builder()
        .name("kitchen_sink_workflow")
        .node(
            Node.builder()
            .name("PlannerNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result)
                .build()
            )
            .tool(planner)
            .publish_to(function_call, when=has_tool_call)
            .publish_to(agent_output, when=has_text_response)
            .build()
        )
    )
    for name, tool in function_call_tools.items():
        builder.node(
            Node.builder()
            .name(name)
            .type("FunctionCallNode")
            .subscribe(function_call)
            .tool(tool)
            .publish_to(function_result)
            .build()
        )
    workflow = (
        builder.node(
            Node.builder()
            .name("ReviewerNode")
            .subscribe(agent_input)
            .tool(ClaudeTool(name="Reviewer", system_message="Review."))
            .publish_to(review)
            .build()
        )
        .node(
            Node.builder()
            .name("ShoutNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(review)
                .and_()
                .subscribed_to(agent_input)
                .build()
            )
            .tool(FunctionTool(name="Shout", function=shout))
            .publish_to(agent_output, when=MinContentLength(minimum=3))
            .build()
        )
        .node(
            Node.builder()
            .name("MCPFunctionNode")
            .subscribe(review)
            .tool(MCPFunctionTool(mcp_config=MCP_CONFIG, function_name="hello"))
            .publish_to(agent_output)
            .build()
        )
        .build()
    )
    return Assistant(name="KitchenSink", workflow=workflow)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _event(content: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        ),
        data=[Message(role="user", content=content)],
    )


async def _run(assistant: Assistant, text: str) -> List[Any]:
    return [
        event.data[0].content
        async for event in assistant.invoke(_event(text), is_sequential=True)
    ]


# The variables the manifests' MCP connections refer to, which loading them
# must allow.
MCP_ENV = ["HELLO_MCP_TOKEN"]


def _reload(assistant: Assistant) -> Assistant:
    """The assistant's manifest, as JSON text, loaded back."""
    manifest = json.loads(json.dumps(assistant.to_manifest()))
    return Assistant.from_manifest(manifest, env=MCP_ENV)


def _ids(assistant: Assistant) -> Dict[str, Any]:
    """What identifies an assistant's parts: what events record, and what
    recovering an interrupted request matches them against."""
    workflow = assistant.workflow
    return {
        "assistant": (type(assistant), assistant.assistant_id, assistant.name),
        "workflow": (type(workflow), workflow.workflow_id, workflow.name),
        "topics": {name: (type(t), t.type) for name, t in workflow.topics.items()},
        "nodes": {
            name: (node.node_id, node.type, type(node.tool), node.tool.tool_id)
            for name, node in workflow.nodes.items()
        },
        "tool_names": {name: n.tool.name for name, n in workflow.nodes.items()},
    }


def _offered(assistant: Assistant) -> Dict[str, Any]:
    """By node: the functions each LLM is offered, and what each function-call
    node answers for the LLMs calling it."""
    offered: Dict[str, Any] = {}
    for name, node in assistant.workflow.nodes.items():
        if isinstance(node.tool, LLM):
            offered[name] = sorted(s.name for s in node.tool.get_function_specs())
        elif isinstance(node.command, FunctionCallCommand):
            offered[name] = node.command.offered
    return offered


# --------------------------------------------------------------------------- #
# A runnable assistant, restored from its manifest, runs as it did
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_restored_assistant_runs_as_the_original() -> None:
    assistant = WeatherAssistant()
    expected = [">> Hi, Ada! | Sunny at 2000"]
    assert await _run(assistant, "How is it?") == expected

    restored = _reload(assistant)

    assert type(restored) is WeatherAssistant
    assert _ids(restored) == _ids(assistant)
    assert await _run(restored, "How is it?") == expected


@pytest.mark.asyncio
async def test_function_calls_are_linked_again_on_load() -> None:
    assistant = WeatherAssistant()
    manifest = assistant.to_manifest()
    llm = manifest["spec"]["workflow"]["nodes"]["LLMNode"]["tool"]
    assert "function_specs" not in llm  # Linked by the workflow, not saved.

    restored = Assistant.from_manifest(manifest)

    assert _offered(restored) == _offered(assistant)
    assert _offered(restored) == {
        "LLMNode": ["get_weather", "greet"],
        "FunctionCallNode": {"function_call": frozenset({"get_weather", "greet"})},
    }
    # A restored copy of a restored copy is linked once, not twice.
    again = _reload(restored)
    assert again.workflow.nodes["LLMNode"].tool.get_function_specs() == (
        assistant.workflow.nodes["LLMNode"].tool.get_function_specs()
    )
    assert await _run(again, "How is it?") == [">> Hi, Ada! | Sunny at 2000"]


def test_assistant_subclass_saves_its_fields_and_loads_its_saved_workflow(
    secrets: Dict[str, str],
) -> None:
    assistant = WeatherAssistant(greeting="Howdy", prefix="~ ")
    manifest = json.loads(json.dumps(assistant.to_manifest()))

    spec = manifest["spec"]
    assert manifest["kind"] == "Assistant"
    assert spec["class"] == f"{__name__}:WeatherAssistant"
    assert (spec["greeting"], spec["prefix"]) == ("Howdy", "~ ")
    assert spec["api_key"] == {"env": "OPENAI_API_KEY"}
    with patch.object(
        WeatherAssistant,
        "_construct_workflow",
        side_effect=AssertionError("the saved workflow is rebuilt"),
    ):
        restored = Assistant.from_manifest(manifest)

    assert type(restored) is WeatherAssistant
    assert (restored.greeting, restored.prefix) == ("Howdy", "~ ")
    assert restored.api_key == secrets["OPENAI_API_KEY"]
    assert _ids(restored) == _ids(assistant)


@pytest.mark.asyncio
async def test_callable_forms_in_the_manifest() -> None:
    nodes = WeatherAssistant().to_manifest()["spec"]["workflow"]["nodes"]

    helper = nodes["FunctionCallNode"]["tool"]
    # Its @llm_function method loads with its class; only what it was given
    # is saved, by reference. What it offers follows from them, unsaved.
    assert helper["functions"] == {"get_weather": {"ref": f"{__name__}:get_weather"}}
    assert "function_specs" not in helper
    assert nodes["FormatNode"]["tool"]["function"] == {
        "class": f"{__name__}:Prefixer",
        "prefix": ">> ",
    }
    assert [
        route["when"] for route in nodes["LLMNode"]["publisher_router"]["routes"]
    ] == [
        {"ref": "grafi.nodes.conditions:has_tool_call"},
        {"ref": "grafi.nodes.conditions:has_text_response"},
    ]
    assert nodes["FormatNode"]["publisher_router"]["routes"] == [
        {"topic": "agent_output", "when": {"ref": f"{__name__}:has_content"}}
    ]
    assert nodes["LLMNode"]["subscribed_expressions"] == [
        {
            "op": "OR",
            "left": {"topic": "agent_input"},
            "right": {"topic": "function_result"},
        }
    ]


def test_manifest_holds_no_pickle_and_no_secret(secrets: Dict[str, str]) -> None:
    text = json.dumps(_kitchen_sink().to_manifest())

    assert "base64" not in text and "pickle" not in text
    for value in secrets.values():
        assert value not in text


# --------------------------------------------------------------------------- #
# Every tool kind, restored with its class, fields and ids
# --------------------------------------------------------------------------- #


@pytest.fixture
def kitchen_sink() -> Assistant:
    return _kitchen_sink()


@pytest.fixture
def restored(kitchen_sink: Assistant) -> Assistant:
    """The kitchen sink loaded from its manifest, without connecting to MCP
    servers."""
    no_connection = AssertionError("loading connected to an MCP server")
    with (
        patch(
            "grafi.tools.function_calls.impl.mcp_tool.Client", side_effect=no_connection
        ),
        patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client",
            side_effect=no_connection,
        ),
    ):
        return _reload(kitchen_sink)


def test_every_tool_kind_round_trips(
    kitchen_sink: Assistant, restored: Assistant
) -> None:
    manifest = kitchen_sink.to_manifest()

    assert restored.to_manifest() == manifest
    assert _ids(restored) == _ids(kitchen_sink)
    assert {
        name: type(n.tool).__name__ for name, n in restored.workflow.nodes.items()
    } == {
        "PlannerNode": "OpenAITool",
        "HelperNode": "GreetTool",
        "SearchNode": "TavilyTool",
        "DuckNode": "DuckDuckGoTool",
        "SyntheticNode": "SyntheticTool",
        "AgentNode": "AgentCallingTool",
        "MCPNode": "MCPTool",
        "ReviewerNode": "ClaudeTool",
        "ShoutNode": "FunctionTool",
        "MCPFunctionNode": "MCPFunctionTool",
    }


def test_secrets_are_saved_as_their_variables(
    kitchen_sink: Assistant, restored: Assistant, secrets: Dict[str, str]
) -> None:
    nodes = kitchen_sink.to_manifest()["spec"]["workflow"]["nodes"]

    assert {
        (name, key): value
        for name, node in nodes.items()
        for key, value in node["tool"].items()
        if isinstance(value, dict) and set(value) == {"env"}
    } == {
        ("PlannerNode", "api_key"): {"env": "OPENAI_API_KEY"},
        ("SearchNode", "api_key"): {"env": "TAVILY_API_KEY"},
        ("SyntheticNode", "openai_api_key"): {"env": "OPENAI_API_KEY"},
        ("ReviewerNode", "api_key"): {"env": "ANTHROPIC_API_KEY"},
    }
    tools = {name: node.tool for name, node in restored.workflow.nodes.items()}
    assert tools["PlannerNode"].api_key == secrets["OPENAI_API_KEY"]
    assert tools["SearchNode"].api_key == secrets["TAVILY_API_KEY"]
    assert tools["SyntheticNode"].openai_api_key == secrets["OPENAI_API_KEY"]
    assert tools["ReviewerNode"].api_key == secrets["ANTHROPIC_API_KEY"]
    # An MCP secret stays a reference, expanded only when connecting.
    assert tools["MCPNode"].mcp_config == MCP_CONFIG
    assert tools["MCPFunctionNode"].mcp_config == MCP_CONFIG


def test_tool_fields_are_restored(restored: Assistant) -> None:
    tools = {name: node.tool for name, node in restored.workflow.nodes.items()}

    planner = tools["PlannerNode"]
    assert (planner.model, planner.system_message) == ("gpt-4o-mini", "Plan.")
    assert planner.chat_params == {"temperature": 0.1, "response_format": Weather}
    assert planner.structured_output is True

    helper = tools["HelperNode"]
    assert (helper.greeting, helper.on_error) == ("Hi", "raise")
    assert helper.functions == {
        "greet": GreetTool.greet,
        "get_weather": get_weather,
    }

    search = tools["SearchNode"]
    assert (search.search_depth, search.max_tokens) == ("basic", 1234)
    assert tools["DuckNode"].fixed_max_results == 3

    synthetic = tools["SyntheticNode"]
    assert (synthetic.input_model, synthetic.output_model) == (
        WeatherQuery,
        WeatherReport,
    )
    assert (synthetic.tool_name, synthetic.model) == ("forecast", "gpt-4o-mini")

    agent = tools["AgentNode"]
    assert agent.agent_call is ask_expert
    assert (agent.agent_name, agent.agent_description) == ("expert", "Ask an expert.")

    mcp = tools["MCPNode"]
    assert [spec.name for spec in mcp.function_specs] == ["hello"]
    assert [(r.name, str(r.uri)) for r in mcp.resources] == [
        ("notes", "file:///notes.txt")
    ]
    assert [(p.name, p.description) for p in mcp.prompts] == [
        ("greeting", "Greet someone.")
    ]

    mcp_function = tools["MCPFunctionNode"]
    assert mcp_function.function_name == "hello"
    assert mcp_function.function.__self__ is mcp_function
    assert mcp_function.function.__func__ is MCPFunctionTool.invoke_mcp_function

    assert tools["ShoutNode"].function is shout
    assert (tools["ReviewerNode"].name, tools["ReviewerNode"].system_message) == (
        "Reviewer",
        "Review.",
    )


def test_model_classes_are_saved_by_import_path(kitchen_sink: Assistant) -> None:
    nodes = kitchen_sink.to_manifest()["spec"]["workflow"]["nodes"]

    planner = nodes["PlannerNode"]["tool"]
    assert planner["chat_params"] == {
        "temperature": 0.1,
        "response_format": {"ref": f"{__name__}:Weather"},
    }
    synthetic = nodes["SyntheticNode"]["tool"]
    assert synthetic["input_model"] == {"ref": f"{__name__}:WeatherQuery"}
    assert synthetic["output_model"] == {"ref": f"{__name__}:WeatherReport"}


def test_routes_and_subscriptions_are_restored(restored: Assistant) -> None:
    workflow = restored.workflow
    nodes = workflow.nodes

    routes = nodes["PlannerNode"].publisher_router.routes
    assert [(r.topic.name, r.when) for r in routes] == [
        ("function_call", has_tool_call),
        ("agent_output", has_text_response),
    ]
    when = nodes["ShoutNode"].publisher_router.routes[0].when
    assert isinstance(when, MinContentLength) and when.minimum == 3
    (expression,) = nodes["ShoutNode"].subscribed_expressions
    assert isinstance(expression, CombinedExpr) and expression.op is LogicalOp.AND
    (expression,) = nodes["PlannerNode"].subscribed_expressions
    assert isinstance(expression, CombinedExpr) and expression.op is LogicalOp.OR
    # Nodes share their workflow's topics, one per name.
    for node in nodes.values():
        for topic in [*node.subscribed_topics, *node.publish_to]:
            assert topic is workflow.topics[topic.name]


def test_function_calls_of_every_kind_are_linked_again_on_load(
    kitchen_sink: Assistant, restored: Assistant
) -> None:
    offered = _offered(restored)

    assert offered == _offered(kitchen_sink)
    assert offered["PlannerNode"] == sorted(
        spec.name
        for node in restored.workflow.nodes.values()
        if isinstance(node.tool, FunctionCallTool)
        for spec in node.tool.get_function_specs()
    )
    assert {"greet", "get_weather", "forecast", "expert", "hello"} <= set(
        offered["PlannerNode"]
    )
    assert offered["ReviewerNode"] == []  # It calls no functions.


def test_workflow_manifest_round_trips(kitchen_sink: Assistant) -> None:
    manifest = json.loads(json.dumps(kitchen_sink.workflow.to_manifest()))

    with pytest.raises(ManifestError, match="HELLO_MCP_TOKEN"):
        EventDrivenWorkflow.from_manifest(manifest)
    workflow = EventDrivenWorkflow.from_manifest(manifest, env=MCP_ENV)

    assert manifest["kind"] == "Workflow"
    assert set(manifest["spec"]["topics"]) == set(workflow.topics)
    assert workflow.to_manifest() == manifest


def test_workflow_is_constructed_from_its_json(kitchen_sink: Assistant) -> None:
    """A workflow's JSON, without its class, constructs it: its nodes name
    the topics it holds."""
    workflow = kitchen_sink.workflow
    data = json.loads(json.dumps(workflow.model_dump(mode="json")))
    del data["class"]

    rebuilt = EventDrivenWorkflow(**data)

    assert rebuilt.to_manifest() == workflow.to_manifest()
    for node in rebuilt.nodes.values():
        for topic in [*node.subscribed_topics, *node.publish_to]:
            assert topic is rebuilt.topics[topic.name]


def test_python_dump_round_trips_in_process(
    kitchen_sink: Assistant, secrets: Dict[str, str]
) -> None:
    """``model_dump()`` holds the values themselves -- classes, functions,
    topics and secrets -- and loads back as the same assistant."""
    planner = kitchen_sink.workflow.nodes["PlannerNode"].tool
    planner.api_key = "a-literal-key"  # Never saved as JSON; held in process.

    data = kitchen_sink.model_dump()

    assert data["class"] is Assistant
    nodes = data["workflow"]["nodes"]
    assert nodes["PlannerNode"]["tool"]["class"] is OpenAITool
    assert nodes["PlannerNode"]["tool"]["api_key"] == "a-literal-key"
    assert nodes["SearchNode"]["tool"]["api_key"] == secrets["TAVILY_API_KEY"]
    assert nodes["PlannerNode"]["tool"]["chat_params"]["response_format"] is Weather
    assert nodes["ShoutNode"]["tool"]["function"] is shout
    assert nodes["AgentNode"]["tool"]["agent_call"] is ask_expert
    route = nodes["PlannerNode"]["publisher_router"]["routes"][0]
    assert route["when"] is has_tool_call
    assert route["topic"]["class"] is Topic
    assert route["topic"]["name"] == "function_call"
    assert data["workflow"]["topics"]["agent_input"]["class"] is InputTopic
    with patch(
        "grafi.tools.function_calls.impl.mcp_tool.Client",
        side_effect=AssertionError("loading connected to an MCP server"),
    ):
        restored = Assistant.model_validate(data)

    assert _ids(restored) == _ids(kitchen_sink)
    assert restored.model_dump() == data
    assert restored.workflow.nodes["PlannerNode"].tool.api_key == "a-literal-key"
    assert _offered(restored) == _offered(kitchen_sink)
    for node in restored.workflow.nodes.values():
        for topic in [*node.subscribed_topics, *node.publish_to]:
            assert topic is restored.workflow.topics[topic.name]


# --------------------------------------------------------------------------- #
# Manifest files
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generated_manifest_file_loads_and_runs(tmp_path: Path) -> None:
    assistant = WeatherAssistant()

    path = assistant.generate_manifest(output_dir=str(tmp_path))

    assert Path(path) == tmp_path / "WeatherAssistant_manifest.json"
    assert json.loads(Path(path).read_text()) == assistant.to_manifest()
    restored = Assistant.from_manifest(path)
    assert _ids(restored) == _ids(assistant)
    assert await _run(restored, "How is it?") == [">> Hi, Ada! | Sunny at 2000"]


def test_failed_manifest_save_leaves_the_file_intact(tmp_path: Path) -> None:
    assistant = WeatherAssistant()
    path = Path(assistant.generate_manifest(output_dir=str(tmp_path)))
    saved = path.read_text()
    assistant.workflow.nodes["LLMNode"].tool.api_key = "a-literal-key"

    with pytest.raises(ManifestError, match="ScriptedLLM.api_key"):
        assistant.generate_manifest(output_dir=str(tmp_path))

    assert path.read_text() == saved
    assert list(tmp_path.iterdir()) == [path]


def test_failed_manifest_write_leaves_no_partial_file(tmp_path: Path) -> None:
    assistant = WeatherAssistant()
    path = Path(assistant.generate_manifest(output_dir=str(tmp_path)))
    saved = path.read_text()
    assistant.greeting = "Howdy"

    with patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            assistant.generate_manifest(output_dir=str(tmp_path))

    assert path.read_text() == saved
    assert list(tmp_path.iterdir()) == [path]  # The partial file is removed.
    assistant.generate_manifest(output_dir=str(tmp_path))
    assert json.loads(path.read_text())["spec"]["greeting"] == "Howdy"


# --------------------------------------------------------------------------- #
# What cannot be saved, or loaded, fails loudly
# --------------------------------------------------------------------------- #


def test_closure_cannot_be_saved() -> None:
    def make_adder(n: int) -> Any:
        def adder(messages: Messages) -> int:
            return n

        return adder

    assistant = WeatherAssistant()
    assistant.workflow.nodes["FormatNode"].tool.function = make_adder(1)

    with pytest.raises(CallableSerializationError, match="without pickle"):
        assistant.to_manifest()
    with pytest.raises(PydanticSerializationError, match="without pickle"):
        assistant.model_dump(mode="json")


def test_nested_literal_secret_cannot_be_saved(kitchen_sink: Assistant) -> None:
    planner = kitchen_sink.workflow.nodes["PlannerNode"].tool
    planner.api_key = "a-literal-key"

    with pytest.raises(ManifestError, match="OpenAITool.api_key .*OPENAI_API_KEY"):
        kitchen_sink.to_manifest()
    with pytest.raises(ManifestError, match="OpenAITool.api_key"):
        kitchen_sink.workflow.nodes["PlannerNode"].to_manifest()
    with pytest.raises(PydanticSerializationError, match="OpenAITool.api_key"):
        kitchen_sink.model_dump(mode="json")


def test_secret_within_a_tool_setting_cannot_be_saved(
    kitchen_sink: Assistant,
) -> None:
    planner = kitchen_sink.workflow.nodes["PlannerNode"].tool
    planner.chat_params = {"extra_headers": {"Authorization": "Bearer sk-literal"}}

    match = "OpenAITool.chat_params holds a secret, at 'Authorization'"
    with pytest.raises(ManifestError, match=match):
        kitchen_sink.to_manifest()
    with pytest.raises(PydanticSerializationError, match=match):
        kitchen_sink.model_dump(mode="json")

    planner.chat_params = {"extra_headers": {"Authorization": "Bearer ${API_TOKEN}"}}
    spec = kitchen_sink.to_manifest()["spec"]
    saved = spec["workflow"]["nodes"]["PlannerNode"]["tool"]["chat_params"]
    assert saved == planner.chat_params  # A reference, expanded by no one here.


def test_a_manifest_reads_only_the_variables_it_is_allowed(
    kitchen_sink: Assistant,
) -> None:
    manifest = json.loads(json.dumps(kitchen_sink.to_manifest()))
    with pytest.raises(ManifestError, match=r"HELLO_MCP_TOKEN.*env=\['HELLO_MCP"):
        Assistant.from_manifest(manifest)

    tool = manifest["spec"]["workflow"]["nodes"]["PlannerNode"]["tool"]
    tool["api_key"] = {"env": "TAVILY_API_KEY"}  # Not its own variable.
    with pytest.raises(ManifestError, match="TAVILY_API_KEY"):
        Assistant.from_manifest(manifest, env=MCP_ENV)

    tool["api_key"] = "sk-literal"  # Refused by the component holding it.
    match = "Assistant.workflow holds a secret, at 'api_key', and a manifest never"
    with pytest.raises(ManifestError, match=match):
        Assistant.from_manifest(manifest, env=MCP_ENV)

    tool["api_key"] = None  # Saving writes its variable, never null.
    with pytest.raises(ManifestError, match="OpenAITool.api_key is given a value"):
        Assistant.from_manifest(manifest, env=MCP_ENV)


def test_nested_literal_mcp_secret_cannot_be_saved(kitchen_sink: Assistant) -> None:
    mcp = kitchen_sink.workflow.nodes["MCPNode"].tool
    mcp.mcp_config = {
        "mcpServers": {"hello": {"headers": {"Authorization": "Bearer t0ken"}}}
    }

    match = "The MCP server 'hello' has 'Authorization' set to a value"
    with pytest.raises(ManifestError, match=match):
        kitchen_sink.to_manifest()
    with pytest.raises(PydanticSerializationError, match=match):
        kitchen_sink.model_dump(mode="json")


def test_legacy_pickle_payload_is_rejected() -> None:
    """A pickle, as grafi before v2 saved a lambda, is of no shape a callable
    is loaded from: refused, naming the upgrade of a manifest before v2."""
    manifest = WeatherAssistant().to_manifest()
    tool = manifest["spec"]["workflow"]["nodes"]["FormatNode"]["tool"]
    tool["function"] = "gASVbase64legacyblob"

    with pytest.raises(CallableSerializationError, match="Cannot load a callable") as e:
        Assistant.from_manifest(manifest)
    assert "Component.from_manifest()" in str(e.value)


def test_route_to_a_topic_outside_the_workflow_is_rejected() -> None:
    manifest = WeatherAssistant().to_manifest()
    node = manifest["spec"]["workflow"]["nodes"]["FormatNode"]
    node["publisher_router"]["routes"][0]["topic"] = "nowhere"

    with pytest.raises(ValidationError, match="Unknown topic 'nowhere'"):
        Assistant.from_manifest(manifest)


def test_mcp_resource_and_prompt_metadata_round_trips() -> None:
    resource = Resource.model_validate(
        {"uri": "file:///notes.txt", "name": "notes", "_meta": {"owner": "ada"}}
    )
    prompt = Prompt.model_validate({"name": "greeting", "_meta": {"v": 2}})
    tool = MCPTool(mcp_config=MCP_CONFIG, resources=[resource], prompts=[prompt])

    loaded = MCPTool.model_validate(
        json.loads(json.dumps(tool.model_dump(mode="json")))
    )

    assert loaded.resources == [resource]
    assert loaded.prompts == [prompt]
    assert loaded.resources[0].meta == {"owner": "ada"}
