import json
import os
import stat
from pathlib import Path
from typing import ClassVar
from typing import List
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ValidationError

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBase
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import CallableSerializationError
from grafi.common.exceptions import WorkflowError
from grafi.common.manifest import ManifestError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import Workflow


class EchoTool(Tool):
    """A tool answering with its reply, a field saved with it."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    reply: str = "echo"

    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content=self.reply)]


def _echo_workflow(reply: str = "echo") -> EventDrivenWorkflow:
    """agent_input -> echo_node -> agent_output."""
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = (
        Node.builder()
        .name("echo_node")
        .tool(EchoTool(name="echo", reply=reply))
        .subscribe(input_topic)
        .publish_to(output_topic)
        .build()
    )
    return EventDrivenWorkflow.builder().name("echo_workflow").node(node).build()


class RecordingAssistant(Assistant):
    """An assistant building its workflow in code, recording each build, with a
    field of its own."""

    builds: ClassVar[List[str]] = []

    greeting: str = "hello"

    def _construct_workflow(self) -> "RecordingAssistant":
        type(self).builds.append(self.name)
        self.workflow = _echo_workflow(reply=self.greeting)
        return self


class TestAssistant:
    @pytest.fixture
    def invoke_context(self):
        """Fixture providing a mock InvokeContext."""
        return InvokeContext(
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="test_request",
        )

    @pytest.fixture
    def mock_workflow(self, invoke_context):
        """Create a mock Workflow instance."""
        mock_workflow = Mock(spec=Workflow)

        async def mock_invoke(*args, **kwargs):
            yield ConsumeFromTopicEvent(
                invoke_context=invoke_context,
                name="agent_output",
                type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
                consumer_name="test_consumer",
                consumed_type="Workflow",
                offset=0,
                data=[Message(content="async workflow response", role="assistant")],
            )

        mock_workflow.invoke.return_value = mock_invoke()
        return mock_workflow

    @pytest.fixture
    def mock_assistant(self, mock_workflow):
        """Create a mock Assistant instance."""
        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(
                assistant_id="test_id",
                name="test_assistant",
                type="test_type",
                oi_span_type=OpenInferenceSpanKindValues.AGENT,
                workflow=mock_workflow,
            )
            return assistant

    @pytest.fixture
    def assistant(self):
        """An assistant with a real workflow, which a manifest can hold."""
        return Assistant(
            assistant_id="test_id",
            name="test_assistant",
            type="test_type",
            oi_span_type=OpenInferenceSpanKindValues.AGENT,
            workflow=_echo_workflow(),
        )

    @pytest.fixture
    def input_messages(self):
        """Fixture providing sample input messages."""
        return [Message(content="test message", role="user")]

    # Test Assistant Creation and Initialization
    def test_assistant_creation_with_defaults(self):
        """Test Assistant creation with default values."""
        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant()

            assert assistant.name == "Assistant"
            assert assistant.type == "assistant"
            assert assistant.oi_span_type == OpenInferenceSpanKindValues.AGENT
            assert assistant.workflow is not None
            assert len(assistant.assistant_id) > 0

    def test_assistant_creation_with_custom_values(self, mock_workflow):
        """Test Assistant creation with custom values."""
        custom_id = "custom_assistant_id"

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(
                assistant_id=custom_id,
                name="custom_assistant",
                type="custom_type",
                oi_span_type=OpenInferenceSpanKindValues.CHAIN,
                workflow=mock_workflow,
            )

            assert assistant.assistant_id == custom_id
            assert assistant.name == "custom_assistant"
            assert assistant.type == "custom_type"
            assert assistant.oi_span_type == OpenInferenceSpanKindValues.CHAIN
            assert assistant.workflow == mock_workflow

    def test_model_post_init_calls_construct_workflow(self):
        """Test that model_post_init calls _construct_workflow."""
        with patch.object(Assistant, "_construct_workflow") as mock_construct:
            Assistant()
            mock_construct.assert_called_once()

    def test_given_workflow_is_not_constructed(self):
        """An assistant given its workflow keeps it, without building one."""
        with patch.object(Assistant, "_construct_workflow") as mock_construct:
            workflow = _echo_workflow()
            assistant = Assistant(workflow=workflow)

            mock_construct.assert_not_called()
            assert assistant.workflow is workflow

    # Test Async Invoke Method
    @pytest.mark.asyncio
    @patch("grafi.assistants.assistant.record_assistant_invoke")
    async def test_invoke_success(
        self, mock_decorator, mock_assistant, invoke_context, input_messages
    ):
        """Test successful async invoke method."""
        # Setup the decorator to call the original function
        mock_decorator.side_effect = lambda func: func

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context, data=input_messages
        )

        # Invoke
        result_events = []
        async for event in mock_assistant.invoke(input_data):
            result_events.append(event)

        # Verify
        mock_assistant.workflow.invoke.assert_called_once_with(
            input_data, False, stream=False
        )
        assert len(result_events) == 1
        assert result_events[0].data[0].content == "async workflow response"
        assert result_events[0].data[0].role == "assistant"

    @pytest.mark.asyncio
    @patch("grafi.assistants.assistant.record_assistant_invoke")
    async def test_invoke_with_empty_messages(
        self, mock_decorator, mock_assistant, invoke_context
    ):
        """Test async invoke with empty messages."""
        mock_decorator.side_effect = lambda func: func
        empty_messages = []

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context, data=empty_messages
        )

        result_events = []
        async for event in mock_assistant.invoke(input_data):
            result_events.append(event)

        mock_assistant.workflow.invoke.assert_called_once_with(
            input_data, False, stream=False
        )
        assert len(result_events) == 1

    @pytest.mark.asyncio
    @patch("grafi.assistants.assistant.record_assistant_invoke")
    async def test_invoke_multiple_yields(
        self, mock_decorator, mock_assistant, invoke_context, input_messages
    ):
        """Test async invoke with multiple yields."""
        mock_decorator.side_effect = lambda func: func

        # Setup mock to yield multiple times
        async def mock_multi_yield(*args, **kwargs):
            yield ConsumeFromTopicEvent(
                invoke_context=invoke_context,
                name="agent_output",
                type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
                consumer_name="test_consumer",
                consumed_type="Workflow",
                offset=0,
                data=[Message(content="first response", role="assistant")],
            )
            yield ConsumeFromTopicEvent(
                invoke_context=invoke_context,
                name="agent_output",
                type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
                consumer_name="test_consumer",
                consumed_type="Workflow",
                offset=0,
                data=[Message(content="second response", role="assistant")],
            )

        mock_assistant.workflow.invoke.return_value = mock_multi_yield()

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context, data=input_messages
        )

        result_events = []
        async for event in mock_assistant.invoke(input_data):
            result_events.append(event)

        assert len(result_events) == 2
        assert result_events[0].data[0].content == "first response"
        assert result_events[1].data[0].content == "second response"

    @pytest.mark.asyncio
    @patch("grafi.assistants.assistant.record_assistant_invoke")
    async def test_invoke_workflow_exception_propagated(
        self, mock_decorator, mock_assistant, invoke_context, input_messages
    ):
        """Test that async workflow exceptions are propagated."""
        mock_decorator.side_effect = lambda func: func

        async def mock_error_generator(*args, **kwargs):
            raise ValueError("Async workflow error")
            yield  # This line won't be reached, but needed for generator syntax

        mock_assistant.workflow.invoke.return_value = mock_error_generator()

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context, data=input_messages
        )

        with pytest.raises(ValueError, match="Async workflow error"):
            async for _ in mock_assistant.invoke(input_data):
                pass

    # Test to_manifest Method
    def test_to_manifest_success(self, assistant):
        """The manifest wraps the assistant's JSON in the grafi/v2 envelope."""
        result = assistant.to_manifest()

        assert set(result) == {"apiVersion", "kind", "spec"}
        assert result["apiVersion"] == "grafi/v2"
        assert result["kind"] == "Assistant"
        spec = result["spec"]
        assert spec == assistant.model_dump(mode="json")
        assert spec["class"] == "grafi.assistants.assistant:Assistant"
        assert spec["assistant_id"] == "test_id"
        assert spec["name"] == "test_assistant"
        assert spec["type"] == "test_type"
        assert spec["oi_span_type"] == "AGENT"
        # The workflow is saved, with its topics and nodes
        workflow = spec["workflow"]
        assert workflow["class"] == (
            "grafi.workflows.impl.event_driven_workflow:EventDrivenWorkflow"
        )
        assert workflow["workflow_id"] == assistant.workflow.workflow_id
        assert set(workflow["topics"]) == {"agent_input", "agent_output"}
        assert workflow["nodes"]["echo_node"]["tool"]["class"] == (
            f"{__name__}:EchoTool"
        )
        # The manifest is plain JSON
        assert json.loads(json.dumps(result)) == result

    def test_to_manifest_serialization_error_propagated(self, assistant):
        """A workflow that cannot be saved fails loudly."""
        node = assistant.workflow.nodes["echo_node"]
        node.publisher_router.routes[0].when = lambda event: True

        with pytest.raises(CallableSerializationError, match="without pickle"):
            assistant.to_manifest()

    # Test generate_manifest Method
    def test_generate_manifest_success(self, assistant, tmp_path):
        """Test successful manifest generation."""
        output_dir = str(tmp_path)

        result_path = assistant.generate_manifest(output_dir)

        # Verify the method returns the path to the generated manifest.
        expected_path = os.path.join(output_dir, "test_assistant_manifest.json")
        assert result_path == Path(expected_path)

        # Verify file was created and contains correct data
        assert os.path.exists(expected_path)

        with open(expected_path, "r") as f:
            manifest_data = json.load(f)

        assert manifest_data == assistant.to_manifest()

    def test_generate_manifest_with_default_directory(
        self, assistant, tmp_path, monkeypatch
    ):
        """Test manifest generation with default directory."""
        monkeypatch.chdir(tmp_path)

        result_path = assistant.generate_manifest()

        assert result_path == Path("test_assistant_manifest.json")
        manifest_file = tmp_path / "test_assistant_manifest.json"
        assert json.loads(manifest_file.read_text()) == assistant.to_manifest()

    def test_generate_manifest_custom_directory(self, assistant, tmp_path):
        """Test manifest generation with custom directory."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        assistant.generate_manifest(str(custom_dir))

        expected_path = custom_dir / "test_assistant_manifest.json"
        assert expected_path.exists()

        with open(expected_path, "r") as f:
            manifest_data = json.load(f)

        assert manifest_data["kind"] == "Assistant"
        assert manifest_data["spec"]["assistant_id"] == "test_id"

    @pytest.mark.asyncio
    async def test_eight_node_dag_workflow(self):
        """
        Test a DAG workflow with 8 nodes: A->B, B->C, C->D, C->E, C->F, D->G, E->G, F->G, G->H.

        Each node concatenates the previous input with its own label.
        For example, node B receives "A" and outputs "AB".

        The topology creates a fan-out at C (to D, E, F) and a fan-in at G (from D, E, F).
        """
        from grafi.common.events.topic_events.publish_to_topic_event import (
            PublishToTopicEvent,
        )
        from grafi.common.models.invoke_context import InvokeContext
        from grafi.common.models.message import Message
        from grafi.nodes.node import Node
        from grafi.tools.functions.function_tool import FunctionTool
        from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
        from grafi.topics.topic_impl.input_topic import InputTopic
        from grafi.topics.topic_impl.output_topic import OutputTopic
        from grafi.topics.topic_impl.topic import Topic
        from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

        # Define the concatenation function for each node
        def make_concat_func(label: str):
            def concat_func(messages):
                # Collect all content from input messages
                contents = []
                for msg in messages:
                    if msg.content:
                        contents.append(msg.content)
                # Sort to ensure deterministic ordering for fan-in scenarios
                contents.sort()
                combined = "".join(contents)
                return f"{combined}{label}"

            return concat_func

        # Create topics
        # Input/Output topics for the workflow
        agent_input_topic = InputTopic(name="agent_input")
        agent_output_topic = OutputTopic(name="agent_output")

        # Intermediate topics for connecting nodes
        topic_a_out = Topic(name="topic_a_out")
        topic_b_out = Topic(name="topic_b_out")
        topic_c_out = Topic(name="topic_c_out")
        topic_d_out = Topic(name="topic_d_out")
        topic_e_out = Topic(name="topic_e_out")
        topic_f_out = Topic(name="topic_f_out")
        topic_g_out = Topic(name="topic_g_out")

        # Create nodes
        # Node A: subscribes to agent_input, publishes to topic_a_out
        node_a = (
            Node.builder()
            .name("NodeA")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolA")
                .function(make_concat_func("A"))
                .build()
            )
            .publish_to(topic_a_out)
            .build()
        )

        # Node B: subscribes to topic_a_out, publishes to topic_b_out
        node_b = (
            Node.builder()
            .name("NodeB")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_a_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolB")
                .function(make_concat_func("B"))
                .build()
            )
            .publish_to(topic_b_out)
            .build()
        )

        # Node C: subscribes to topic_b_out, publishes to topic_c_out
        node_c = (
            Node.builder()
            .name("NodeC")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_b_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolC")
                .function(make_concat_func("C"))
                .build()
            )
            .publish_to(topic_c_out)
            .build()
        )

        # Node D: subscribes to topic_c_out, publishes to topic_d_out (fan-out from C)
        node_d = (
            Node.builder()
            .name("NodeD")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_c_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolD")
                .function(make_concat_func("D"))
                .build()
            )
            .publish_to(topic_d_out)
            .build()
        )

        # Node E: subscribes to topic_c_out, publishes to topic_e_out (fan-out from C)
        node_e = (
            Node.builder()
            .name("NodeE")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_c_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolE")
                .function(make_concat_func("E"))
                .build()
            )
            .publish_to(topic_e_out)
            .build()
        )

        # Node F: subscribes to topic_c_out, publishes to topic_f_out (fan-out from C)
        node_f = (
            Node.builder()
            .name("NodeF")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_c_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolF")
                .function(make_concat_func("F"))
                .build()
            )
            .publish_to(topic_f_out)
            .build()
        )

        # Node G: subscribes to topic_d_out AND topic_e_out AND topic_f_out (fan-in)
        node_g = (
            Node.builder()
            .name("NodeG")
            .type("ConcatNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(topic_d_out)
                .and_()
                .subscribed_to(topic_e_out)
                .and_()
                .subscribed_to(topic_f_out)
                .build()
            )
            .tool(
                FunctionTool.builder()
                .name("ConcatToolG")
                .function(make_concat_func("G"))
                .build()
            )
            .publish_to(topic_g_out)
            .build()
        )

        # Node H: subscribes to topic_g_out, publishes to agent_output
        node_h = (
            Node.builder()
            .name("NodeH")
            .type("ConcatNode")
            .subscribe(SubscriptionBuilder().subscribed_to(topic_g_out).build())
            .tool(
                FunctionTool.builder()
                .name("ConcatToolH")
                .function(make_concat_func("H"))
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Build the workflow
        workflow = (
            EventDrivenWorkflow.builder()
            .name("EightNodeDAGWorkflow")
            .node(node_a)
            .node(node_b)
            .node(node_c)
            .node(node_d)
            .node(node_e)
            .node(node_f)
            .node(node_g)
            .node(node_h)
            .build()
        )

        # Create assistant with the workflow
        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(
                name="EightNodeDAGAssistant",
                workflow=workflow,
            )

        # Create invoke context and input
        invoke_context = InvokeContext(
            conversation_id="test_dag_conversation",
            invoke_id="test_dag_invoke",
            assistant_request_id="test_dag_request",
        )

        # Start with empty input - each node adds its label
        input_messages = [Message(content="", role="user")]
        input_data = PublishToTopicEvent(
            invoke_context=invoke_context, data=input_messages
        )

        # Invoke the workflow (using default parallel mode)
        result_events = []
        async for event in assistant.invoke(input_data):
            result_events.append(event)

        # Verify we get exactly 1 event from the agent_output topic
        assert len(result_events) == 1, f"Expected 1 event, got {len(result_events)}"
        assert result_events[0].name == "agent_output"

        # The expected output path is:
        # A: "" -> "A"
        # B: "A" -> "AB"
        # C: "AB" -> "ABC"
        # D: "ABC" -> "ABCD"
        # E: "ABC" -> "ABCE"
        # F: "ABC" -> "ABCF"
        # G: combines "ABCD", "ABCE", "ABCF" (sorted) -> "ABCDABCEABCFG"
        # H: "ABCDABCEABCFG" -> "ABCDABCEABCFGH"
        expected_output = "ABCDABCEABCFGH"
        assert result_events[0].data[0].content == expected_output

    @pytest.mark.parametrize("name", ["../escaped", "nested/name", "C:evil", "a\\b"])
    def test_a_name_holding_a_path_is_never_a_manifests_file(
        self, assistant, tmp_path, name
    ):
        assistant.name = name
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        with pytest.raises(ManifestError, match="so it holds no ./."):
            assistant.generate_manifest(str(output_dir))

        assert list(tmp_path.rglob("*")) == [output_dir]

    @pytest.mark.parametrize("name", ["Q&A Assistant (v2) #1", "..", "ReAct+Search"])
    def test_a_name_holding_no_path_names_its_manifests_file(
        self, assistant, tmp_path, name
    ):
        assistant.name = name

        path = assistant.generate_manifest(tmp_path)

        assert path == tmp_path / f"{name}_manifest.json"
        assert list(tmp_path.iterdir()) == [path]

    def test_a_link_at_the_manifests_path_is_replaced_never_followed(
        self, assistant, tmp_path
    ):
        """One planted in a shared directory cannot redirect the write."""
        target = tmp_path / "elsewhere"
        target.write_text("kept")
        link = tmp_path / f"{assistant.name}_manifest.json"
        link.symlink_to(target)

        assistant.generate_manifest(tmp_path)

        assert not link.is_symlink()
        assert json.loads(link.read_text()) == assistant.to_manifest()
        assert target.read_text() == "kept"

    def test_generate_manifest_makes_its_directory(self, assistant, tmp_path):
        path = assistant.generate_manifest(tmp_path / "manifests" / "today")

        assert Assistant.from_manifest(path).to_manifest() == assistant.to_manifest()
        assert list(path.parent.iterdir()) == [path]  # No temporary file left.

    def test_a_manifest_is_readable_as_the_umask_allows(self, assistant, tmp_path):
        """Written as open() writes a file, so another user may read it."""
        previous = os.umask(0o022)
        try:
            path = assistant.generate_manifest(tmp_path)
            path.chmod(0o640)
            assistant.generate_manifest(tmp_path)
        finally:
            os.umask(previous)

        assert stat.S_IMODE(path.stat().st_mode) == 0o644

    def test_failed_save_keeps_the_previous_manifest(self, assistant, tmp_path):
        """A save that fails leaves the manifest already written whole."""
        path = assistant.generate_manifest(str(tmp_path))
        saved = Path(path).read_text()
        node = assistant.workflow.nodes["echo_node"]
        node.publisher_router.routes[0].when = lambda event: True

        with pytest.raises(CallableSerializationError):
            assistant.generate_manifest(str(tmp_path))

        assert Path(path).read_text() == saved
        assert list(tmp_path.iterdir()) == [Path(path)]

    def test_a_failed_write_leaves_no_temporary_file(
        self, assistant, tmp_path, monkeypatch
    ):
        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", fail)

        with pytest.raises(OSError, match="disk full"):
            assistant.generate_manifest(str(tmp_path))

        assert list(tmp_path.iterdir()) == []

    def test_generate_manifest_serialization_error(self, assistant, tmp_path):
        """Test manifest generation with a workflow that cannot be saved."""
        node = assistant.workflow.nodes["echo_node"]
        node.publisher_router.routes[0].when = lambda event: True

        with pytest.raises(CallableSerializationError, match="without pickle"):
            assistant.generate_manifest(str(tmp_path))

    @pytest.mark.asyncio
    async def test_full_async_workflow_integration(
        self, mock_workflow, invoke_context, input_messages
    ):
        """Test full async integration with real workflow calls."""
        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="async_integration_test", workflow=mock_workflow)

            input_data = PublishToTopicEvent(
                invoke_context=invoke_context, data=input_messages
            )

            # Test asynchronous invoke
            async_results = []
            async for event in assistant.invoke(input_data):
                async_results.append(event)

            assert len(async_results) == 1
            assert async_results[0].data[0].content == "async workflow response"

    # Test Edge Cases
    def test_assistant_with_none_workflow(self):
        """Test Assistant behavior with None workflow."""
        with patch.object(Assistant, "_construct_workflow"):
            with pytest.raises(Exception):  # This should fail during validation
                Assistant(workflow=None)

    def test_assistant_name_affects_manifest_filename(self, tmp_path):
        """Test that assistant name affects manifest filename."""
        assistant = Assistant(name="special_assistant_name", workflow=_echo_workflow())

        assistant.generate_manifest(str(tmp_path))

        expected_file = tmp_path / "special_assistant_name_manifest.json"
        assert expected_file.exists()


class TestAssistantFromManifest:
    """``Assistant.from_manifest`` restores an assistant, with its saved
    workflow, from a manifest file or dict."""

    @pytest.fixture(autouse=True)
    def no_builds(self):
        RecordingAssistant.builds.clear()
        yield
        RecordingAssistant.builds.clear()

    @pytest.fixture
    def original(self) -> RecordingAssistant:
        assistant = RecordingAssistant(
            assistant_id="recording_id",
            name="recording_assistant",
            type="recording_type",
            oi_span_type=OpenInferenceSpanKindValues.CHAIN,
            greeting="hi there",
        )
        assert RecordingAssistant.builds == ["recording_assistant"]
        return assistant

    def _check_restored(
        self, restored: AssistantBase, original: RecordingAssistant
    ) -> None:
        assert type(restored) is RecordingAssistant
        assert restored.assistant_id == "recording_id"
        assert restored.name == "recording_assistant"
        assert restored.type == "recording_type"
        assert restored.oi_span_type == OpenInferenceSpanKindValues.CHAIN
        # The subclass's own field survives
        assert restored.greeting == "hi there"
        # The workflow is the saved one, not one built again
        assert RecordingAssistant.builds == ["recording_assistant"]
        workflow = restored.workflow
        assert isinstance(workflow, EventDrivenWorkflow)
        assert workflow is not original.workflow
        assert workflow.workflow_id == original.workflow.workflow_id
        assert workflow.name == "echo_workflow"
        node = workflow.nodes["echo_node"]
        assert node.node_id == original.workflow.nodes["echo_node"].node_id
        assert type(node.tool) is EchoTool
        assert node.tool.reply == "hi there"
        assert node.subscribed_topics == [workflow.topics["agent_input"]]
        assert node.publish_to == [workflow.topics["agent_output"]]

    def test_from_manifest_file(self, original: RecordingAssistant, tmp_path):
        path = original.generate_manifest(str(tmp_path))

        restored = Assistant.from_manifest(path)

        self._check_restored(restored, original)

    def test_from_manifest_path_object(self, original: RecordingAssistant, tmp_path):
        path = original.generate_manifest(str(tmp_path))

        restored = RecordingAssistant.from_manifest(tmp_path / os.path.basename(path))

        self._check_restored(restored, original)

    def test_from_manifest_dict(self, original: RecordingAssistant):
        restored = Assistant.from_manifest(original.to_manifest())

        self._check_restored(restored, original)

    def test_round_trip_is_stable(self, original: RecordingAssistant, tmp_path):
        manifest = original.to_manifest()

        restored = Assistant.from_manifest(manifest)

        assert restored.to_manifest() == manifest
        path = restored.generate_manifest(str(tmp_path))
        assert json.loads(open(path).read()) == manifest
        assert Assistant.from_manifest(path).to_manifest() == manifest

    def test_model_validate_also_skips_construction(self, original: RecordingAssistant):
        restored = AssistantBase.model_validate(original.model_dump(mode="json"))

        self._check_restored(restored, original)

    @pytest.mark.asyncio
    async def test_restored_assistant_runs(self, original: RecordingAssistant):
        restored = Assistant.from_manifest(original.to_manifest())
        input_data = PublishToTopicEvent(
            invoke_context=InvokeContext(
                conversation_id="conversation",
                invoke_id="invoke",
                assistant_request_id="restored_request",
            ),
            data=[Message(role="user", content="hello")],
        )

        outputs = [event async for event in restored.invoke(input_data)]

        assert [event.data[0].content for event in outputs] == ["hi there"]

    def test_manifest_of_another_kind_fails(self, original: RecordingAssistant):
        """A manifest saying it holds another kind is refused."""
        manifest = {**original.to_manifest(), "kind": "Workflow"}

        with pytest.raises(
            ManifestError,
            match="The manifest's kind is 'Workflow', but its spec is of kind "
            "'Assistant'.",
        ):
            Assistant.from_manifest(manifest)
        # Checked before anything is built.
        assert RecordingAssistant.builds == ["recording_assistant"]

    def test_manifest_without_a_kind_fails(self, original: RecordingAssistant):
        manifest = original.to_manifest()
        del manifest["kind"]

        with pytest.raises(ManifestError, match="The manifest's kind is None"):
            Assistant.from_manifest(manifest)

    @pytest.mark.parametrize(
        "path",
        [
            ("workflow",),
            ("workflow", "nodes", "echo_node"),
            ("workflow", "nodes", "echo_node", "tool"),
            ("workflow", "topics", "agent_input"),
        ],
    )
    def test_every_component_of_a_manifest_names_its_class(
        self, original: RecordingAssistant, path
    ):
        manifest = original.to_manifest()
        component = manifest["spec"]
        for key in path:
            component = component[key]
        del component["class"]

        with pytest.raises(ManifestError, match='names its class, as "class"'):
            Assistant.from_manifest(manifest)

    def test_python_dump_round_trips(self, original: RecordingAssistant):
        """A python-mode dump holds values, classes themselves among them, and
        loads back in this process, keeping the workflow."""
        data = original.model_dump()

        assert data["class"] is RecordingAssistant
        assert data["workflow"]["class"] is EventDrivenWorkflow
        assert data["workflow"]["nodes"]["echo_node"]["tool"]["class"] is EchoTool

        restored = AssistantBase.model_validate(data)

        self._check_restored(restored, original)
        assert restored.model_dump() == data
        assert restored.to_manifest() == original.to_manifest()

    def test_workflow_manifest_is_not_an_assistant(self, original: RecordingAssistant):
        """A workflow's manifest does not load as an assistant."""
        manifest = original.workflow.to_manifest()
        assert manifest["kind"] == "Workflow"

        with pytest.raises(ManifestError, match="is not a subclass of Assistant"):
            Assistant.from_manifest(manifest)

    def test_unsupported_version_fails(self, original: RecordingAssistant):
        manifest = {**original.to_manifest(), "apiVersion": "grafi/v9"}

        with pytest.raises(ManifestError, match="Unsupported manifest version"):
            Assistant.from_manifest(manifest)

    def test_spec_without_class_fails(self, original: RecordingAssistant):
        manifest = original.to_manifest()
        del manifest["spec"]["class"]

        with pytest.raises(ManifestError, match="with its class"):
            Assistant.from_manifest(manifest)

    def test_workflow_needs_its_topics(self, original: RecordingAssistant):
        """A manifest without a workflow's topics cannot restore its nodes."""
        manifest = original.to_manifest()
        del manifest["spec"]["workflow"]["topics"]

        with pytest.raises(ValidationError, match="Unknown topic 'agent_input'"):
            Assistant.from_manifest(manifest)

    def test_workflow_without_input_and_output_topics_fails(self):
        """A manifest's workflow is checked as one built in code is."""
        manifest = {
            "apiVersion": "grafi/v2",
            "kind": "Assistant",
            "spec": {
                "class": "grafi.assistants.assistant:Assistant",
                "workflow": {
                    "class": (
                        "grafi.workflows.impl.event_driven_workflow:"
                        "EventDrivenWorkflow"
                    ),
                    "nodes": {},
                    "topics": {},
                },
            },
        }

        # A manifest's errors are ManifestError's, the workflow's its cause.
        with pytest.raises(ManifestError, match="agent_input_topic") as raised:
            Assistant.from_manifest(manifest)
        assert isinstance(raised.value.__cause__, WorkflowError)

    def test_legacy_manifest_is_upgraded(self):
        """A manifest saved by the former to_dict(), without an apiVersion,
        loads, its own tool classes named with legacy_classes."""
        legacy = {
            "assistant_id": "legacy_id",
            "name": "legacy_assistant",
            "type": "assistant",
            "oi_span_type": "AGENT",
            "workflow": {
                "workflow_id": "legacy_workflow_id",
                "name": "EventDrivenWorkflow",
                "type": "EventDrivenWorkflow",
                "oi_span_type": "AGENT",
                "topics": {
                    "agent_input": {"name": "agent_input", "type": "AgentInputTopic"},
                    "agent_output": {
                        "name": "agent_output",
                        "type": "AgentOutputTopic",
                    },
                },
                "nodes": {
                    "echo_node": {
                        "class": "Node",
                        "node_id": "legacy_node_id",
                        "name": "echo_node",
                        "type": "Node",
                        "tool": {
                            "class": "EchoTool",
                            "base_class": "Tool",
                            "tool_id": "legacy_tool_id",
                            "name": "echo",
                            "type": "EchoTool",
                            "oi_span_type": "TOOL",
                        },
                        "oi_span_type": "CHAIN",
                        "subscribed_expressions": [{"topic": "agent_input"}],
                        "publish_to": ["agent_output"],
                        "command": {"class": "Command"},
                    }
                },
            },
        }

        with pytest.raises(ManifestError, match="Unknown tool class 'EchoTool'"):
            Assistant.from_manifest(legacy)

        restored = Assistant.from_manifest(
            legacy, legacy_classes={"EchoTool": EchoTool}
        )

        assert type(restored) is Assistant
        assert restored.assistant_id == "legacy_id"
        workflow = restored.workflow
        assert isinstance(workflow, EventDrivenWorkflow)
        assert workflow.workflow_id == "legacy_workflow_id"
        node = workflow.nodes["echo_node"]
        assert node.node_id == "legacy_node_id"
        assert type(node.tool) is EchoTool
        assert node.tool.tool_id == "legacy_tool_id"
        assert node.publish_to == [workflow.topics["agent_output"]]
        assert type(workflow.topics["agent_input"]) is InputTopic

        # Loaded through a subclass, it is one, with the saved workflow.
        recording = RecordingAssistant.from_manifest(
            legacy, legacy_classes={"EchoTool": EchoTool}
        )

        assert type(recording) is RecordingAssistant
        assert recording.assistant_id == "legacy_id"
        assert recording.workflow.workflow_id == "legacy_workflow_id"
        assert RecordingAssistant.builds == []


def test_concurrent_saves_of_one_manifest_never_collide(tmp_path) -> None:
    """Each writes beside it under a name of its own, then moves it over."""
    from concurrent.futures import ThreadPoolExecutor

    assistant = Assistant(name="shared")
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(
            pool.map(lambda _: assistant.generate_manifest(tmp_path), range(50))
        )

    assert set(paths) == {tmp_path / "shared_manifest.json"}
    assert list(tmp_path.iterdir()) == [tmp_path / "shared_manifest.json"]


def test_an_invoke_taking_no_stream_is_refused_when_its_class_is_defined():
    """Rather than when a caller, or grafi, passes stream."""
    with pytest.raises(
        TypeError, match="NoStream.invoke\\(\\) takes no stream by keyword"
    ):

        class NoStream(Assistant):
            async def invoke(self, input_data, is_sequential=False):  # type: ignore[override]
                yield input_data


def test_a_workflow_whose_invoke_takes_stream_only_by_position_is_refused():
    from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

    with pytest.raises(TypeError, match="takes no stream by keyword"):

        class Positional(EventDrivenWorkflow):
            async def invoke(self, input_data, is_sequential=False, stream=False, /):  # type: ignore[override]
                yield input_data


def test_an_invoke_wrapped_by_an_adapter_taking_stream_is_accepted():
    """A wrapper passing stream on, to an invoke that predates it."""
    import functools

    def adds_stream(invoke):
        @functools.wraps(invoke)
        async def wrapper(self, input_data, is_sequential=False, *, stream=False):
            async for output in invoke(self, input_data, is_sequential):
                yield output

        return wrapper

    class Adapted(Assistant):
        @adds_stream
        async def invoke(self, input_data, is_sequential=False):  # type: ignore[override]
            yield input_data

    assert Adapted.invoke.__wrapped__ is not None
