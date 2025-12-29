import asyncio
import json
import os
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue
from grafi.workflows.workflow import Workflow


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
        mock_workflow.to_dict.return_value = {"workflow": "data"}
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
        mock_assistant.workflow.invoke.assert_called_once_with(input_data, False)
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

        mock_assistant.workflow.invoke.assert_called_once_with(input_data, False)
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

    # Test to_dict Method
    def test_to_dict_success(self, mock_assistant):
        """Test successful to_dict method."""
        result = mock_assistant.to_dict()

        assert result == {
            "assistant_id": "test_id",
            "name": "test_assistant",
            "oi_span_type": "AGENT",
            "type": "test_type",
            "workflow": {
                "workflow": "data",
            },
        }
        mock_assistant.workflow.to_dict.assert_called_once()

    def test_to_dict_workflow_exception_propagated(self, mock_assistant):
        """Test that workflow to_dict exceptions are propagated."""
        mock_assistant.workflow.to_dict.side_effect = RuntimeError(
            "Serialization error"
        )

        with pytest.raises(RuntimeError, match="Serialization error"):
            mock_assistant.to_dict()

    # Test generate_manifest Method
    def test_generate_manifest_success(self, mock_assistant, tmp_path):
        """Test successful manifest generation."""
        output_dir = str(tmp_path)

        result_path = mock_assistant.generate_manifest(output_dir)

        # Verify the method returns correct path
        expected_path = os.path.join(output_dir, "test_assistant_manifest.json")
        assert (
            result_path is None
        )  # Method doesn't return path, but we can check file exists

        # Verify file was created and contains correct data
        assert os.path.exists(expected_path)

        with open(expected_path, "r") as f:
            manifest_data = json.load(f)

        assert manifest_data == {
            "assistant_id": "test_id",
            "name": "test_assistant",
            "oi_span_type": "AGENT",
            "type": "test_type",
            "workflow": {
                "workflow": "data",
            },
        }
        mock_assistant.workflow.to_dict.assert_called()

    def test_generate_manifest_with_default_directory(self, mock_assistant):
        """Test manifest generation with default directory."""
        with patch("builtins.open", create=True) as mock_open:
            with patch("json.dumps", return_value='{"workflow": "data"}') as mock_dumps:
                mock_assistant.generate_manifest()

                # Verify file was opened with correct path
                expected_path = os.path.join(".", "test_assistant_manifest.json")
                mock_open.assert_called_once_with(expected_path, "w")

                # Verify JSON serialization
                mock_dumps.assert_called_once_with(
                    {
                        "assistant_id": "test_id",
                        "name": "test_assistant",
                        "oi_span_type": "AGENT",
                        "type": "test_type",
                        "workflow": {
                            "workflow": "data",
                        },
                    },
                    indent=4,
                )

    def test_generate_manifest_custom_directory(self, mock_assistant, tmp_path):
        """Test manifest generation with custom directory."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        mock_assistant.generate_manifest(str(custom_dir))

        expected_path = custom_dir / "test_assistant_manifest.json"
        assert expected_path.exists()

        with open(expected_path, "r") as f:
            manifest_data = json.load(f)

        assert manifest_data == {
            "assistant_id": "test_id",
            "name": "test_assistant",
            "oi_span_type": "AGENT",
            "type": "test_type",
            "workflow": {
                "workflow": "data",
            },
        }

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

    def test_generate_manifest_file_write_error(self, mock_assistant):
        """Test manifest generation with file write error."""
        with patch("builtins.open", side_effect=IOError("Permission denied")):
            with pytest.raises(IOError, match="Permission denied"):
                mock_assistant.generate_manifest()

    def test_generate_manifest_json_serialization_error(self, mock_assistant):
        """Test manifest generation with JSON serialization error."""
        # Make to_dict return something that can't be serialized
        mock_assistant.workflow.to_dict.return_value = {"key": object()}

        with pytest.raises(TypeError):
            mock_assistant.generate_manifest()

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

    def test_assistant_name_affects_manifest_filename(self, mock_workflow, tmp_path):
        """Test that assistant name affects manifest filename."""
        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="special_assistant_name", workflow=mock_workflow)

            assistant.generate_manifest(str(tmp_path))

            expected_file = tmp_path / "special_assistant_name_manifest.json"
            assert expected_file.exists()

    # Test from_dict Method
    @pytest.mark.asyncio
    async def test_from_dict_basic(self):
        """Test basic deserialization from dictionary."""
        from grafi.nodes.node import Node
        from grafi.tools.tool import Tool
        from grafi.tools.tool_factory import ToolFactory
        from grafi.topics.expressions.topic_expression import TopicExpr
        from grafi.topics.topic_impl.input_topic import InputTopic
        from grafi.topics.topic_impl.output_topic import OutputTopic
        from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

        # Create a simple mock tool for testing
        class SimpleMockTool(Tool):
            oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

            async def invoke(self, invoke_context, input_data):
                yield [Message(role="assistant", content="mock response")]

            @classmethod
            async def from_dict(cls, data):
                return cls(
                    tool_id=data.get("tool_id", "default-id"),
                    name=data.get("name", "SimpleMockTool"),
                    type=data.get("type", "SimpleMockTool"),
                    oi_span_type=data.get(
                        "oi_span_type", OpenInferenceSpanKindValues.TOOL
                    ),
                )

        # Register the mock tool
        ToolFactory.register_tool_class("SimpleMockTool", SimpleMockTool)

        try:
            # Create a complete workflow
            input_topic = InputTopic(name="test_input")
            output_topic = OutputTopic(name="test_output")
            mock_tool = SimpleMockTool()
            node = Node(
                name="test_node",
                tool=mock_tool,
                subscribed_expressions=[TopicExpr(topic=input_topic)],
                publish_to=[output_topic],
            )
            workflow = EventDrivenWorkflow(nodes={"test_node": node})

            # Create an assistant with the workflow
            with patch.object(Assistant, "_construct_workflow"):
                original = Assistant(
                    assistant_id="test_id",
                    name="test_assistant",
                    type="test_type",
                    oi_span_type=OpenInferenceSpanKindValues.AGENT,
                    workflow=workflow,
                )

            # Serialize to dict
            data = original.to_dict()

            # Deserialize back
            restored = await Assistant.from_dict(data)

            # Verify key properties match
            assert isinstance(restored, Assistant)
            assert restored.name == "test_assistant"
            assert restored.type == "test_type"
            assert restored.oi_span_type == OpenInferenceSpanKindValues.AGENT
            assert restored.workflow is not None
            assert isinstance(restored.workflow, EventDrivenWorkflow)
        finally:
            # Clean up
            ToolFactory.unregister_tool_class("SimpleMockTool")

    @pytest.mark.asyncio
    async def test_from_dict_roundtrip(self):
        """Test serialization and deserialization roundtrip."""
        from grafi.nodes.node import Node
        from grafi.tools.tool import Tool
        from grafi.tools.tool_factory import ToolFactory
        from grafi.topics.expressions.topic_expression import TopicExpr
        from grafi.topics.topic_impl.input_topic import InputTopic
        from grafi.topics.topic_impl.output_topic import OutputTopic
        from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

        # Create a simple mock tool for testing
        class RoundtripMockTool(Tool):
            oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

            async def invoke(self, invoke_context, input_data):
                yield [Message(role="assistant", content="roundtrip response")]

            @classmethod
            async def from_dict(cls, data):
                return cls(
                    tool_id=data.get("tool_id", "default-id"),
                    name=data.get("name", "RoundtripMockTool"),
                    type=data.get("type", "RoundtripMockTool"),
                    oi_span_type=data.get(
                        "oi_span_type", OpenInferenceSpanKindValues.TOOL
                    ),
                )

        # Register the mock tool
        ToolFactory.register_tool_class("RoundtripMockTool", RoundtripMockTool)

        try:
            # Create a complete workflow
            input_topic = InputTopic(name="roundtrip_input")
            output_topic = OutputTopic(name="roundtrip_output")
            mock_tool = RoundtripMockTool()
            node = Node(
                name="roundtrip_node",
                tool=mock_tool,
                subscribed_expressions=[TopicExpr(topic=input_topic)],
                publish_to=[output_topic],
            )
            workflow = EventDrivenWorkflow(nodes={"roundtrip_node": node})

            # Create an assistant with the workflow
            with patch.object(Assistant, "_construct_workflow"):
                original = Assistant(
                    assistant_id="roundtrip_id",
                    name="roundtrip_assistant",
                    type="roundtrip_type",
                    oi_span_type=OpenInferenceSpanKindValues.CHAIN,
                    workflow=workflow,
                )

            # Serialize to dict
            data = original.to_dict()

            # Deserialize back
            restored = await Assistant.from_dict(data)

            # Verify structure matches
            assert isinstance(restored, Assistant)
            assert restored.name == original.name
            assert restored.type == original.type
            assert restored.oi_span_type == original.oi_span_type
            assert isinstance(restored.workflow, EventDrivenWorkflow)

            # Verify workflow structure
            assert len(restored.workflow.nodes) == len(original.workflow.nodes)
            assert "roundtrip_node" in restored.workflow.nodes
            assert "roundtrip_input" in restored.workflow._topics
            assert "roundtrip_output" in restored.workflow._topics
        finally:
            # Clean up
            ToolFactory.unregister_tool_class("RoundtripMockTool")

    @pytest.mark.asyncio
    async def test_from_dict_with_defaults(self):
        """Test from_dict with missing fields uses defaults."""

        # Minimal data with only workflow
        data = {
            "workflow": {
                "name": "EventDrivenWorkflow",
                "type": "EventDrivenWorkflow",
                "oi_span_type": "AGENT",
                "nodes": {},
                "topics": {},
            }
        }

        # This should fail because EventDrivenWorkflow needs input/output topics
        with pytest.raises(Exception):  # Will raise WorkflowError
            await Assistant.from_dict(data)


class TestAsyncOutputQueue:
    """Tests for AsyncOutputQueue race condition handling."""

    @pytest.mark.asyncio
    async def test_anext_waits_for_activity_count_stabilization(self):
        """
        Test that __anext__ doesn't prematurely terminate when activity count changes.

        This tests the race condition fix where the output queue could terminate
        before downstream nodes finish processing.
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Simulate: node enters, adds item to queue, leaves
        # Then another node should enter before we terminate

        async def simulate_node_activity():
            """Simulate node activity that should prevent premature termination."""
            # First node processes
            await tracker.enter("node_1")
            await output_queue.queue.put(Mock(name="event_1"))
            await tracker.leave("node_1")

            # Yield control - simulates realistic timing where next node
            # starts within the same event loop cycle
            await asyncio.sleep(0)

            # Second node picks up and processes
            await tracker.enter("node_2")
            await output_queue.queue.put(Mock(name="event_2"))
            await tracker.leave("node_2")

        # Start the activity simulation
        activity_task = asyncio.create_task(simulate_node_activity())

        # Iterate over the queue
        events = []
        async for event in output_queue:
            events.append(event)
            if len(events) >= 2:
                break

        await activity_task

        # Should have received both events
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_anext_terminates_when_truly_idle(self):
        """
        Test that __anext__ correctly terminates when no more activity.
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Single node processes and finishes
        async def simulate_single_node():
            await tracker.enter("node_1")
            await output_queue.queue.put(Mock(name="event_1"))
            await tracker.leave("node_1")

        activity_task = asyncio.create_task(simulate_single_node())

        events = []
        async for event in output_queue:
            events.append(event)

        await activity_task

        # Should terminate after receiving the single event
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_activity_count_prevents_premature_exit(self):
        """
        Test specifically that activity count tracking prevents race condition.

        Scenario:
        1. Node A finishes and tracker goes idle
        2. __anext__ sees idle but activity count changed
        3. Node B starts before __anext__ decides to terminate
        4. All events are properly yielded
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        events_received = []
        iteration_complete = asyncio.Event()

        async def consumer():
            async for event in output_queue:
                events_received.append(event)
            iteration_complete.set()

        async def producer():
            # Node A processes
            await tracker.enter("node_a")
            await output_queue.queue.put(Mock(name="event_a"))
            await tracker.leave("node_a")

            # Critical timing window - yield to let consumer check idle state
            await asyncio.sleep(0)

            # Node B starts before consumer terminates (if fix works)
            await tracker.enter("node_b")
            await output_queue.queue.put(Mock(name="event_b"))
            await tracker.leave("node_b")

        consumer_task = asyncio.create_task(consumer())
        producer_task = asyncio.create_task(producer())

        # Wait for producer to finish
        await producer_task

        # Wait a bit for consumer to process
        try:
            await asyncio.wait_for(iteration_complete.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

        # With the fix, we should receive both events
        assert len(events_received) == 2, (
            f"Expected 2 events but got {len(events_received)}. "
            "Race condition may have caused premature termination."
        )
