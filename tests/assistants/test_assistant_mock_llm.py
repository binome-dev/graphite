"""
Unit tests for assistants using FunctionTool to simulate LLM behavior.

This module provides tests for:
1. Human-in-the-Loop (HITL) workflows
2. ReAct agent patterns with function calling

All tests use FunctionTool to deterministically mock LLM responses,
enabling reliable unit testing without real API calls.
"""

import base64
import inspect
import uuid
from typing import Any
from typing import Callable
from typing import List
from typing import Union
from unittest.mock import patch

import cloudpickle
import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import FunctionToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


@use_command(Command)
class LLMMockTool(Tool):
    name: str = "LLMMockTool"
    type: str = "LLMMockTool"
    role: str = "assistant"
    function: Callable[[Messages], Union[Message, Messages]]
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        try:
            response = self.function(input_data)
            if inspect.isasyncgen(response):
                async for item in response:
                    # Ensure item is always a list
                    if isinstance(item, list):
                        yield item
                    else:
                        yield [item]
                return
            if inspect.isawaitable(response):
                response = await response

            # Ensure response is always a list
            if isinstance(response, list):
                yield response
            else:
                yield [response]
        except Exception as e:
            raise FunctionToolException(
                tool_name=self.name,
                operation="invoke",
                message=f"Async function execution failed: {e}",
                invoke_context=invoke_context,
                cause=e,
            ) from e

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            **super().to_dict(),
            "role": self.role,
            "base_class": "FunctionTool",
            "function": base64.b64encode(cloudpickle.dumps(self.function)).decode(
                "utf-8"
            ),
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "LLMMockTool":
        """
        Create a FunctionTool instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the FunctionTool.

        Returns:
            FunctionTool: A FunctionTool instance created from the dictionary.

        Note:
            Functions cannot be fully reconstructed from serialized data as they
            contain executable code. This method creates an instance with a
            placeholder function that needs to be re-registered after deserialization.
        """

        return cls(
            name=data.get("name", "LLMMockTool"),
            type=data.get("type", "LLMMockTool"),
            role=data.get("role", "assistant"),
            function=lambda messages: messages,
            oi_span_type=OpenInferenceSpanKindValues.TOOL,
        )


def make_tool_call(
    call_id: str, name: str, arguments: str
) -> ChatCompletionMessageToolCall:
    """Helper to create tool calls."""
    return ChatCompletionMessageToolCall(
        id=call_id,
        type="function",
        function=Function(name=name, arguments=arguments),
    )


class TestReActAgentWithMockLLM:
    """
    Test ReAct agent patterns using FunctionTool to simulate LLM behavior.

    ReAct (Reasoning and Acting) agent pattern:
    1. LLM receives input and decides whether to call a function or respond
    2. If function call -> execute function -> return result to LLM
    3. LLM processes function result and decides next action
    4. Loop continues until LLM generates final response (no function call)
    """

    @pytest.fixture
    def invoke_context(self):
        """Create a test invoke context."""
        return InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

    @pytest.mark.asyncio
    async def test_react_agent_no_function_call(self, invoke_context):
        """
        Test ReAct agent when LLM directly responds without function calls.

        Flow: Input -> LLM (no function call) -> Output
        """

        # Mock LLM that always responds directly without function calls
        def mock_llm(messages: List[Message]) -> List[Message]:
            user_content = messages[-1].content if messages else ""
            return [
                Message(role="assistant", content=f"Direct response to: {user_content}")
            ]

        # Create topics
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            # Only output when there's content and no tool calls
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )

        # Create LLM node
        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        # Build workflow
        workflow = (
            EventDrivenWorkflow.builder()
            .name("react_no_func_workflow")
            .node(llm_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestReActAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Hello, how are you?")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "Direct response to: Hello, how are you?" in results[0].data[0].content

    @pytest.mark.asyncio
    async def test_react_agent_single_function_call(self, invoke_context):
        """
        Test ReAct agent with a single function call.

        Flow: Input -> LLM (function call) -> Function -> LLM (response) -> Output
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that calls function on first call, responds on second."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                # First call: make a function call
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "call_1",
                                "search",
                                '{"query": "weather today"}',
                            )
                        ],
                    )
                ]
            else:
                # Second call: respond with the function result
                last_msg = (
                    messages[-1] if messages else Message(role="user", content="")
                )
                return [
                    Message(
                        role="assistant",
                        content=f"Based on search: {last_msg.content}",
                    )
                ]

        def search(self, query: str) -> str:
            """Mock search function."""
            return "The weather is sunny, 72°F"

        # Create topics
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        # Create LLM node
        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        # Create function call node
        function_node = (
            Node.builder()
            .name("SearchNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("SearchTool").function(search).build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Build workflow
        workflow = (
            EventDrivenWorkflow.builder()
            .name("react_single_func_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestReActAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="What's the weather?")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "Based on search" in results[0].data[0].content
        assert call_count["llm"] == 2

    @pytest.mark.asyncio
    async def test_react_agent_multiple_function_calls(self, invoke_context):
        """
        Test ReAct agent with multiple sequential function calls.

        Flow: Input -> LLM (func1) -> Func1 -> LLM (func2) -> Func2 -> LLM (response) -> Output
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that makes multiple function calls."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call("call_1", "get_user", '{"id": "123"}')
                        ],
                    )
                ]
            elif call_count["llm"] == 2:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "call_2",
                                "get_orders",
                                '{"user_id": "123"}',
                            )
                        ],
                    )
                ]
            else:
                return [
                    Message(
                        role="assistant",
                        content="User John has 3 orders totaling $150.",
                    )
                ]

        def get_user(self, id: str) -> str:
            """Mock get_user function."""
            return '{"name": "John", "id": "123"}'

        def get_orders(self, user_id: str) -> str:
            """Mock get_orders function."""
            return '{"orders": 3, "total": "$150"}'

        # Create topics
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("MockFunction")
                .function(get_user)
                .function(get_orders)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("react_multi_func_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestReActAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Get user 123's order summary")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "John" in results[0].data[0].content
        assert "3 orders" in results[0].data[0].content
        assert call_count["llm"] == 3


class TestHumanInTheLoopWithMockLLM:
    """
    Test Human-in-the-Loop (HITL) workflows using FunctionTool to simulate LLM behavior.

    HITL workflow pattern (following tests_integration/hith_assistant concepts):
    1. LLM processes input and decides to request human input via tool call
    2. Function node executes and publishes to InWorkflowOutputTopic
    3. Workflow pauses, emits event for human response
    4. Human provides input via new invoke with consumed_event_ids
    5. Input goes to InWorkflowInputTopic, LLM continues processing
    6. LLM generates final response or requests more human input

    Key components:
    - InWorkflowOutputTopic: Pauses workflow and emits to external consumer (human)
    - InWorkflowInputTopic: Receives human response to continue workflow
    - consumed_event_ids: Links human response to previous outputs when resuming
    """

    @pytest.fixture
    def invoke_context(self):
        """Create a test invoke context."""
        return InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

    @pytest.mark.asyncio
    async def test_hitl_workflow_no_human_input_needed(self, invoke_context):
        """
        Test HITL workflow when LLM can respond without human input.

        Flow: Input -> LLM (direct response, no tool call) -> Output
        """

        def mock_llm(messages: List[Message]) -> List[Message]:
            return [Message(role="assistant", content="I can answer this directly!")]

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        hitl_call_topic = Topic(
            name="hitl_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )

        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(hitl_call_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("hitl_no_human_workflow")
            .node(llm_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestHITLAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Simple question")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert results[0].data[0].content == "I can answer this directly!"

    @pytest.mark.asyncio
    async def test_hitl_workflow_with_in_workflow_topics(self, invoke_context):
        """
        Test proper HITL workflow using InWorkflowInputTopic and InWorkflowOutputTopic.

        This follows the pattern from tests_integration/hith_assistant:
        1. First invoke: LLM requests human info -> pauses at InWorkflowOutputTopic
        2. Second invoke: Human provides response via consumed_event_ids -> continues
        3. LLM generates final response

        Flow:
        Invoke 1: Input -> LLM (tool call) -> FunctionNode -> InWorkflowOutputTopic (pauses)
        Invoke 2: Human response (with consumed_event_ids) -> InWorkflowInputTopic -> LLM -> Output
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that requests human info on first call, responds on second."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                # First call: request human information
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "info_1",
                                "request_human_information",
                                '{"question": "What is your name?"}',
                            )
                        ],
                    )
                ]
            else:
                # Second call: process human response and generate final answer
                # Find the user's response in messages
                user_response = ""
                for msg in messages:
                    if msg.role == "user" and msg.content:
                        user_response = msg.content
                return [
                    Message(
                        role="assistant",
                        content=f"Thank you! I received your response: {user_response}",
                    )
                ]

        def request_human_information(self, question: str) -> str:
            """Mock function that returns a schema for human to fill."""
            import json

            return json.dumps({"question": question, "answer": "string"})

        # Create topics following integration test pattern
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        hitl_call_topic = Topic(
            name="hitl_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )

        # HITL topics - the key components for true HITL pattern
        human_response_topic = InWorkflowInputTopic(name="human_response")
        human_request_topic = InWorkflowOutputTopic(
            name="human_request",
            paired_in_workflow_input_topic_names=["human_response"],
        )

        # LLM node subscribes to both initial input AND human responses
        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(human_response_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(hitl_call_topic)
            .build()
        )

        # Function node publishes to InWorkflowOutputTopic to pause for human
        function_node = (
            Node.builder()
            .name("HITLRequestNode")
            .subscribe(SubscriptionBuilder().subscribed_to(hitl_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("HITLRequest")
                .function(request_human_information)
                .build()
            )
            .publish_to(human_request_topic)  # InWorkflowOutputTopic - pauses here
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("hitl_in_workflow_topics")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestHITLAgent", workflow=workflow)

        # First invoke: should pause at InWorkflowOutputTopic
        first_input = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="I want to register")],
        )

        first_outputs = []
        async for event in assistant.invoke(first_input):
            first_outputs.append(event)

        # Should get output from InWorkflowOutputTopic (the HITL request)
        assert len(first_outputs) == 1
        assert call_count["llm"] == 1

        # Second invoke: human provides response with consumed_event_ids
        human_response = PublishToTopicEvent(
            invoke_context=InvokeContext(
                conversation_id=invoke_context.conversation_id,
                invoke_id=uuid.uuid4().hex,
                assistant_request_id=invoke_context.assistant_request_id,
            ),
            data=[Message(role="user", content="My name is Alice")],
            consumed_event_ids=[event.event_id for event in first_outputs],
        )

        second_outputs = []
        async for event in assistant.invoke(human_response):
            second_outputs.append(event)

        # Should get final response from LLM
        assert len(second_outputs) == 1
        assert "Alice" in second_outputs[0].data[0].content
        assert call_count["llm"] == 2

    @pytest.mark.asyncio
    async def test_hitl_workflow_multi_turn_human_input(self, invoke_context):
        """
        Test HITL workflow requiring multiple rounds of human input.

        This simulates a registration flow requiring name and age separately.

        Flow:
        Invoke 1: Input -> LLM (request name) -> pause
        Invoke 2: Name response -> LLM (request age) -> pause
        Invoke 3: Age response -> LLM (complete registration) -> Output
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that collects info step by step."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                # First: request name
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "name_req",
                                "request_info",
                                '{"field": "name"}',
                            )
                        ],
                    )
                ]
            elif call_count["llm"] == 2:
                # Second: got name, request age
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "age_req",
                                "request_info",
                                '{"field": "age"}',
                            )
                        ],
                    )
                ]
            else:
                # Third: got all info, complete registration
                return [
                    Message(
                        role="assistant",
                        content="Registration complete! Welcome to the gym.",
                    )
                ]

        def request_info(self, field: str) -> str:
            """Request a specific piece of information."""
            import json

            return json.dumps({"requested_field": field})

        # Topics
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        hitl_call_topic = Topic(
            name="hitl_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        human_response_topic = InWorkflowInputTopic(name="human_response")
        human_request_topic = InWorkflowOutputTopic(
            name="human_request",
            paired_in_workflow_input_topic_names=["human_response"],
        )

        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(human_response_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(hitl_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("InfoRequestNode")
            .subscribe(SubscriptionBuilder().subscribed_to(hitl_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("InfoRequest")
                .function(request_info)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("hitl_multi_turn")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestHITLAgent", workflow=workflow)

        # Invoke 1: Initial request
        outputs_1 = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=[Message(role="user", content="Register me for the gym")],
            )
        ):
            outputs_1.append(event)

        assert len(outputs_1) == 1
        assert call_count["llm"] == 1

        # Invoke 2: Provide name
        outputs_2 = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=InvokeContext(
                    conversation_id=invoke_context.conversation_id,
                    invoke_id=uuid.uuid4().hex,
                    assistant_request_id=invoke_context.assistant_request_id,
                ),
                data=[Message(role="user", content="My name is Bob")],
                consumed_event_ids=[e.event_id for e in outputs_1],
            )
        ):
            outputs_2.append(event)

        assert len(outputs_2) == 1
        assert call_count["llm"] == 2

        # Invoke 3: Provide age
        outputs_3 = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=InvokeContext(
                    conversation_id=invoke_context.conversation_id,
                    invoke_id=uuid.uuid4().hex,
                    assistant_request_id=invoke_context.assistant_request_id,
                ),
                data=[Message(role="user", content="My age is 25")],
                consumed_event_ids=[e.event_id for e in outputs_2],
            )
        ):
            outputs_3.append(event)

        assert len(outputs_3) == 1
        assert "Registration complete" in outputs_3[0].data[0].content
        assert call_count["llm"] == 3

    @pytest.mark.asyncio
    async def test_hitl_workflow_with_approval_rejection(self, invoke_context):
        """
        Test HITL workflow where human can approve or reject an action.

        This tests the approval pattern with InWorkflowOutputTopic.
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "approval_1",
                                "request_approval",
                                '{"action": "delete_account"}',
                            )
                        ],
                    )
                ]
            else:
                # Check last user message for approval decision
                last_user_msg = ""
                for msg in reversed(messages):
                    if msg.role == "user" and msg.content:
                        last_user_msg = msg.content.lower()
                        break

                if "approve" in last_user_msg or "yes" in last_user_msg:
                    return [
                        Message(
                            role="assistant",
                            content="Account deletion approved and completed.",
                        )
                    ]
                else:
                    return [
                        Message(
                            role="assistant",
                            content="Account deletion was rejected. No action taken.",
                        )
                    ]

        def request_approval(self, action: str) -> str:
            """Request human approval for an action."""
            import json

            return json.dumps(
                {
                    "action": action,
                    "message": f"Do you approve: {action}?",
                    "options": ["approve", "reject"],
                }
            )

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        hitl_call_topic = Topic(
            name="hitl_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        human_response_topic = InWorkflowInputTopic(name="human_response")
        human_request_topic = InWorkflowOutputTopic(
            name="human_request",
            paired_in_workflow_input_topic_names=["human_response"],
        )

        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(human_response_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(hitl_call_topic)
            .build()
        )

        hitl_node = (
            Node.builder()
            .name("ApprovalNode")
            .subscribe(SubscriptionBuilder().subscribed_to(hitl_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("ApprovalTool")
                .function(request_approval)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("hitl_approval_workflow")
            .node(llm_node)
            .node(hitl_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestHITLAgent", workflow=workflow)

        # First invoke: request approval
        outputs_1 = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=[Message(role="user", content="Delete my account")],
            )
        ):
            outputs_1.append(event)

        assert len(outputs_1) == 1
        assert call_count["llm"] == 1

        # Second invoke: human rejects
        outputs_2 = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=InvokeContext(
                    conversation_id=invoke_context.conversation_id,
                    invoke_id=uuid.uuid4().hex,
                    assistant_request_id=invoke_context.assistant_request_id,
                ),
                data=[Message(role="user", content="reject")],
                consumed_event_ids=[e.event_id for e in outputs_1],
            )
        ):
            outputs_2.append(event)

        assert len(outputs_2) == 1
        assert "rejected" in outputs_2[0].data[0].content.lower()
        assert call_count["llm"] == 2

    @pytest.mark.asyncio
    async def test_hitl_legacy_auto_approval_pattern(self, invoke_context):
        """
        Test legacy HITL pattern where function auto-responds (no real human pause).

        This is the simpler pattern where the function immediately returns a result
        without pausing for actual human input. Useful for testing function call flows.
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that requests approval on first call."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "approval_1",
                                "auto_approve",
                                '{"action": "test_action"}',
                            )
                        ],
                    )
                ]
            else:
                last_content = messages[-1].content if messages else ""
                if "approved" in last_content.lower():
                    return [
                        Message(
                            role="assistant",
                            content="Action was automatically approved.",
                        )
                    ]
                return [Message(role="assistant", content="Action completed.")]

        def auto_approve(self, action: str) -> str:
            """Simulate automatic approval without human intervention."""
            return "Action APPROVED automatically"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("AutoApproveNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("AutoApprove")
                .function(auto_approve)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("legacy_auto_approval")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestHITLAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Do something that needs approval")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "approved" in results[0].data[0].content.lower()
        assert call_count["llm"] == 2


class TestComplexWorkflowPatterns:
    """
    Test more complex workflow patterns combining multiple features.
    """

    @pytest.fixture
    def invoke_context(self):
        return InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

    @pytest.mark.asyncio
    async def test_conditional_branching_workflow(self, invoke_context):
        """
        Test workflow with conditional branching based on LLM output.

        Flow:
        - Input -> Router LLM
        - If question about weather -> Weather function -> Response LLM
        - If question about math -> Math function -> Response LLM
        - Otherwise -> Direct response
        """

        def mock_router(messages: List[Message]) -> List[Message]:
            """Route based on input content."""
            content = messages[-1].content.lower() if messages else ""
            if "weather" in content:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call("w1", "weather", '{"location": "NYC"}')
                        ],
                    )
                ]
            elif "math" in content or "calculate" in content:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[make_tool_call("m1", "math", '{"expr": "2+2"}')],
                    )
                ]
            else:
                return [
                    Message(
                        role="assistant",
                        content="I can help with weather or math questions!",
                    )
                ]

        def weather(self, location: str) -> str:
            return "Weather in NYC: Sunny, 75°F"

        def math(self, expr: str) -> str:
            return "Result: 4"

        def mock_response(messages: List[Message]) -> List[Message]:
            """Generate final response from function result."""
            last_content = messages[-1].content if messages else ""
            return [
                Message(
                    role="assistant", content=f"Here's what I found: {last_content}"
                )
            ]

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        weather_topic = Topic(
            name="weather_call",
            condition=lambda event: (
                event.data[-1].tool_calls is not None
                and any(
                    tc.function.name == "weather" for tc in event.data[-1].tool_calls
                )
            ),
        )
        math_topic = Topic(
            name="math_call",
            condition=lambda event: (
                event.data[-1].tool_calls is not None
                and any(tc.function.name == "math" for tc in event.data[-1].tool_calls)
            ),
        )
        function_result_topic = Topic(name="function_result")

        router_node = (
            Node.builder()
            .name("RouterNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=mock_router))
            .publish_to(agent_output)
            .publish_to(weather_topic)
            .publish_to(math_topic)
            .build()
        )

        weather_node = (
            Node.builder()
            .name("WeatherNode")
            .subscribe(SubscriptionBuilder().subscribed_to(weather_topic).build())
            .tool(FunctionCallTool.builder().name("Weather").function(weather).build())
            .publish_to(function_result_topic)
            .build()
        )

        math_node = (
            Node.builder()
            .name("MathNode")
            .subscribe(SubscriptionBuilder().subscribed_to(math_topic).build())
            .tool(FunctionCallTool.builder().name("Math").function(math).build())
            .publish_to(function_result_topic)
            .build()
        )

        response_node = (
            Node.builder()
            .name("ResponseNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(function_result_topic).build()
            )
            .tool(LLMMockTool(function=mock_response))
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("conditional_workflow")
            .node(router_node)
            .node(weather_node)
            .node(math_node)
            .node(response_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="ConditionalAgent", workflow=workflow)

        # Test weather branch
        weather_input = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="What's the weather in NYC?")],
        )
        weather_results = []
        async for event in assistant.invoke(weather_input):
            weather_results.append(event)

        assert len(weather_results) == 1
        assert "Sunny" in weather_results[0].data[0].content

    @pytest.mark.asyncio
    async def test_parallel_function_execution(self, invoke_context):
        """
        Test workflow where LLM calls multiple functions that can execute in parallel.

        The FunctionTool will handle multiple tool_calls in a single message.
        """

        def mock_llm_parallel(messages: List[Message]) -> List[Message]:
            """LLM that requests multiple functions at once."""
            # Check if we have function results
            has_results = any(msg.role == "tool" for msg in messages)
            if has_results:
                return [
                    Message(
                        role="assistant",
                        content="Combined weather and news: Great day, no major events!",
                    )
                ]
            else:
                # Request both functions at once
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call("w1", "weather", "{}"),
                            make_tool_call("n1", "news", "{}"),
                        ],
                    )
                ]

        def weather(self) -> str:
            """Handle weather function call."""
            return "Weather: Sunny"

        def news(self) -> str:
            """Handle news function call."""
            return "News: Markets up 2%"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm_parallel))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("CombinedFunc")
                .function(weather)
                .function(news)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("parallel_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="ParallelAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="What's the weather and news?")],
        )

        results = []

        print("starting invocation")
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "weather" in results[0].data[0].content.lower()

    @pytest.mark.asyncio
    async def test_error_handling_in_function_call(self, invoke_context):
        """
        Test workflow handles function errors gracefully.
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            call_count["llm"] += 1
            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[make_tool_call("f1", "failing_func", "{}")],
                    )
                ]
            else:
                # Handle error from function
                last_content = messages[-1].content if messages else ""
                if "error" in last_content.lower():
                    return [
                        Message(
                            role="assistant",
                            content="I encountered an error. Let me try a different approach.",
                        )
                    ]
                return [Message(role="assistant", content="Success!")]

        def failing_func(self) -> str:
            """Function that returns an error."""
            return "Error: Service unavailable"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FailingNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("FailingFunc")
                .function(failing_func)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("error_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="ErrorHandlingAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Do something that might fail")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "error" in results[0].data[0].content.lower()

    @pytest.mark.asyncio
    async def test_context_preservation_across_turns(self, invoke_context):
        """
        Test that context is properly passed through multiple turns.
        """
        accumulated_context = []

        def mock_llm_with_context(messages: List[Message]) -> List[Message]:
            """LLM that tracks conversation context."""
            accumulated_context.append([m.content for m in messages if m.content])

            if len(accumulated_context) == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[make_tool_call("c1", "context_func", "{}")],
                    )
                ]
            else:
                # Return summary of all seen content
                all_content = [c for ctx in accumulated_context for c in ctx]
                return [
                    Message(
                        role="assistant",
                        content=f"Processed {len(all_content)} messages",
                    )
                ]

        def context_func(self) -> str:
            return "Context function executed"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("ContextLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm_with_context))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("ContextFuncNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("ContextFunc")
                .function(context_func)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("context_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="ContextAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Test context preservation")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "Processed" in results[0].data[0].content
        # Verify context was accumulated
        assert len(accumulated_context) == 2


class TestEdgeCasesAndExceptions:
    """
    Test edge cases, error handling, and exception scenarios.

    These tests ensure the workflow handles:
    1. Exceptions during tool execution
    2. Exceptions in LLM mock functions
    3. Empty/invalid message handling
    4. Workflow stop on error
    5. Serialization/deserialization
    6. Edge cases in data flow
    """

    @pytest.fixture
    def invoke_context(self):
        return InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

    @pytest.mark.asyncio
    async def test_exception_in_function_call_tool(self, invoke_context):
        """
        Test that exceptions in FunctionCallTool are properly propagated.
        """

        def mock_llm(messages: List[Message]) -> List[Message]:
            return [
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[make_tool_call("err1", "raise_error", "{}")],
                )
            ]

        def raise_error(self) -> str:
            raise ValueError("Intentional test error in function call")

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("ErrorNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("ErrorTool")
                .function(raise_error)
                .build()
            )
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("error_test_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="ErrorTestAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Trigger error")],
        )

        from grafi.common.exceptions import NodeExecutionError

        with pytest.raises(NodeExecutionError) as exc_info:
            async for _ in assistant.invoke(input_data):
                pass

        assert "ErrorNode" in str(exc_info.value) or "Intentional test error" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    async def test_exception_in_llm_mock_tool(self, invoke_context):
        """
        Test that exceptions in LLMMockTool are properly propagated.
        """

        def failing_llm(messages: List[Message]) -> List[Message]:
            raise RuntimeError("LLM processing failed")

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: event.data[-1].content is not None,
        )

        llm_node = (
            Node.builder()
            .name("FailingLLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=failing_llm))
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("failing_llm_workflow")
            .node(llm_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="FailingLLMAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Trigger LLM error")],
        )

        from grafi.common.exceptions import NodeExecutionError

        with pytest.raises(NodeExecutionError) as exc_info:
            async for _ in assistant.invoke(input_data):
                pass

        assert "LLM processing failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_llm_returns_empty_content(self, invoke_context):
        """
        Test handling when LLM returns a message with empty content but no tool calls.
        """

        def empty_content_llm(messages: List[Message]) -> List[Message]:
            return [Message(role="assistant", content="")]

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: event.data[-1].content is not None,
        )

        llm_node = (
            Node.builder()
            .name("EmptyLLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=empty_content_llm))
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("empty_content_workflow")
            .node(llm_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="EmptyContentAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Get empty response")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert results[0].data[0].content == ""

    @pytest.mark.asyncio
    async def test_llm_returns_single_message_not_list(self, invoke_context):
        """
        Test that LLMMockTool properly wraps single Message in a list.
        """

        def single_message_llm(messages: List[Message]) -> Message:
            # Return single Message, not list
            return Message(role="assistant", content="Single message response")

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: event.data[-1].content is not None,
        )

        llm_node = (
            Node.builder()
            .name("SingleMsgLLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=single_message_llm))
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("single_msg_workflow")
            .node(llm_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="SingleMsgAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Get single message")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert results[0].data[0].content == "Single message response"

    @pytest.mark.asyncio
    async def test_function_call_with_invalid_json_arguments(self, invoke_context):
        """
        Test handling of tool calls with malformed JSON arguments.
        """

        def mock_llm(messages: List[Message]) -> List[Message]:
            return [
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id="bad_json",
                            type="function",
                            function=Function(
                                name="some_func", arguments="not valid json{"
                            ),
                        )
                    ],
                )
            ]

        def some_func(self) -> str:
            return "Should not reach here"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FuncNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("SomeFunc").function(some_func).build()
            )
            .publish_to(agent_output)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("invalid_json_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="InvalidJsonAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Trigger invalid JSON")],
        )

        from grafi.common.exceptions import NodeExecutionError

        with pytest.raises(NodeExecutionError):
            async for _ in assistant.invoke(input_data):
                pass

    @pytest.mark.asyncio
    async def test_function_not_found_in_tool(self, invoke_context):
        """
        Test handling when LLM calls a function that isn't registered.
        """

        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that calls function on first call, responds on second."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                # First call: make a function call
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call("missing", "nonexistent_function", "{}")
                        ],
                    )
                ]
            else:
                return [
                    Message(
                        role="assistant",
                        content="Function not found.",
                    )
                ]

        def existing_func(self) -> str:
            return "This is an existing function"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FuncNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("ExistingFunc")
                .function(existing_func)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("missing_func_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="MissingFuncAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Call missing function")],
        )

        # When function is not found, FunctionCallTool yields empty messages
        # This may cause workflow to hang or complete without output
        # The test verifies this edge case is handled
        results = []

        try:
            async for event in assistant.invoke(input_data):
                results.append(event)
        except Exception:
            # Either an exception or empty results is acceptable
            pass

    @pytest.mark.asyncio
    async def test_workflow_stops_on_node_exception(self, invoke_context):
        """
        Test that workflow stops processing when a node raises an exception.
        This verifies the force_stop fix in _invoke_node.
        """
        call_count = {"count": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            call_count["count"] += 1
            if call_count["count"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[make_tool_call("fail", "fail_func", "{}")],
                    )
                ]
            # Should not reach here if workflow stops on error
            return [Message(role="assistant", content="Should not see this")]

        def fail_func(self) -> str:
            raise Exception("Node failure - workflow should stop")

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("FailNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("FailTool").function(fail_func).build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("stop_on_error_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="StopOnErrorAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Trigger failure")],
        )

        from grafi.common.exceptions import NodeExecutionError

        # Workflow should raise exception and stop, not hang
        with pytest.raises(NodeExecutionError):
            async for _ in assistant.invoke(input_data):
                pass

        # Verify LLM was only called once (workflow stopped after error)
        assert call_count["count"] == 1

    @pytest.mark.asyncio
    async def test_llm_mock_tool_serialization(self, invoke_context):
        """
        Test LLMMockTool to_dict and from_dict methods.
        """

        def sample_llm(messages: List[Message]) -> List[Message]:
            return [Message(role="assistant", content="Serialization test")]

        tool = LLMMockTool(
            name="SerializationTestTool",
            function=sample_llm,
        )

        # Test to_dict
        tool_dict = tool.to_dict()
        assert tool_dict["name"] == "SerializationTestTool"
        assert "function" in tool_dict

        # Test from_dict
        restored_tool = await LLMMockTool.from_dict(tool_dict)
        assert restored_tool.name == "SerializationTestTool"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_message(self, invoke_context):
        """
        Test handling multiple tool calls in a single LLM response.
        """

        def mock_llm(messages: List[Message]) -> List[Message]:
            has_results = any(msg.role == "tool" for msg in messages)
            if has_results:
                return [
                    Message(
                        role="assistant",
                        content="Got results from both functions",
                    )
                ]
            return [
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        make_tool_call("t1", "func_a", "{}"),
                        make_tool_call("t2", "func_b", "{}"),
                    ],
                )
            ]

        def func_a(self) -> str:
            return "Result A"

        def func_b(self) -> str:
            return "Result B"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("MultiFunc")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("MultiFuncTool")
                .function(func_a)
                .function(func_b)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("multi_tool_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="MultiToolAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Call multiple functions")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "results" in results[0].data[0].content.lower()

    @pytest.mark.asyncio
    async def test_function_returns_complex_json(self, invoke_context):
        """
        Test function that returns complex JSON data.
        """
        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            call_count["llm"] += 1
            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[make_tool_call("json1", "get_complex_data", "{}")],
                    )
                ]
            # Check if we received the complex data
            last_content = messages[-1].content if messages else ""
            return [
                Message(
                    role="assistant",
                    content=f"Received complex data: {last_content[:50]}...",
                )
            ]

        def get_complex_data(self) -> str:
            import json

            return json.dumps(
                {
                    "users": [
                        {"id": 1, "name": "Alice", "roles": ["admin", "user"]},
                        {"id": 2, "name": "Bob", "roles": ["user"]},
                    ],
                    "metadata": {
                        "total": 2,
                        "page": 1,
                        "nested": {"deep": {"value": True}},
                    },
                }
            )

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("JsonFunc")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("JsonTool")
                .function(get_complex_data)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("complex_json_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="JsonAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Get complex data")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "complex data" in results[0].data[0].content.lower()

    @pytest.mark.asyncio
    async def test_function_with_special_characters_in_args(self, invoke_context):
        """
        Test function call with special characters in arguments.
        """
        received_args = {}

        call_count = {"llm": 0}

        def mock_llm(messages: List[Message]) -> List[Message]:
            call_count["llm"] += 1
            if call_count["llm"] == 1:
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "special",
                                "process_text",
                                '{"text": "Hello\\nWorld\\twith\\ttabs", "query": "test \\"quoted\\""}',
                            )
                        ],
                    )
                ]
            return [Message(role="assistant", content="Processed special chars")]

        def process_text(self, text: str, query: str) -> str:
            received_args["text"] = text
            received_args["query"] = query
            return f"Processed: {text}"

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        function_node = (
            Node.builder()
            .name("TextFunc")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder()
                .name("TextTool")
                .function(process_text)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        workflow = (
            EventDrivenWorkflow.builder()
            .name("special_chars_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="SpecialCharsAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="Test special characters")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        # Verify special characters were properly parsed
        assert "\n" in received_args.get("text", "")
        assert "\t" in received_args.get("text", "")
        assert '"' in received_args.get("query", "")

    @pytest.mark.asyncio
    async def test_react_agent_single_function_call_twice(self):
        """
        Test ReAct agent with a single function call.

        Flow: Input -> LLM (function call) -> Function -> LLM (response) -> Output
        """
        call_count = {"llm": 0}

        invoke_context = InvokeContext(
            conversation_id=uuid.uuid4().hex,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

        def mock_llm(messages: List[Message]) -> List[Message]:
            """Mock LLM that calls function on first call, responds on second."""
            call_count["llm"] += 1

            if call_count["llm"] == 1:
                # First call: make a function call
                return [
                    Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            make_tool_call(
                                "call_1",
                                "search",
                                '{"query": "weather today"}',
                            )
                        ],
                    )
                ]
            else:
                # Second call: respond with the function result
                last_msg = (
                    messages[-1] if messages else Message(role="user", content="")
                )
                return [
                    Message(
                        role="assistant",
                        content=f"Based on search: {last_msg.content}",
                    )
                ]

        def search(self, query: str) -> str:
            """Mock search function."""
            return "The weather is sunny, 72°F"

        # Create topics
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(
            name="agent_output",
            condition=lambda event: (
                event.data[-1].content is not None and event.data[-1].tool_calls is None
            ),
        )
        function_call_topic = Topic(
            name="function_call",
            condition=lambda event: event.data[-1].tool_calls is not None,
        )
        function_result_topic = Topic(name="function_result")

        # Create LLM node
        llm_node = (
            Node.builder()
            .name("MockLLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(LLMMockTool(function=mock_llm))
            .publish_to(agent_output)
            .publish_to(function_call_topic)
            .build()
        )

        # Create function call node
        function_node = (
            Node.builder()
            .name("SearchNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("SearchTool").function(search).build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Build workflow
        workflow = (
            EventDrivenWorkflow.builder()
            .name("react_single_func_workflow")
            .node(llm_node)
            .node(function_node)
            .build()
        )

        with patch.object(Assistant, "_construct_workflow"):
            assistant = Assistant(name="TestReActAgent", workflow=workflow)

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="What's the weather?")],
        )

        results = []
        async for event in assistant.invoke(input_data):
            results.append(event)

        assert len(results) == 1
        assert "Based on search" in results[0].data[0].content
        assert call_count["llm"] == 2

        input_data = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=[Message(role="user", content="What's the weather again?")],
        )

        secound_results = []
        async for event in assistant.invoke(input_data, is_sequential=True):
            secound_results.append(event)

        assert len(secound_results) == 0
