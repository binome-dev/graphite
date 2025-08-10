"""
This file is part of the Graphite project.

Copyright (c) 2023-2025 Binome Dev and contributors

This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file, You can obtain one at
https://mozilla.org/MPL/2.0/.
"""

import asyncio
from collections.abc import AsyncGenerator
import inspect
from typing import Callable, Concatenate, List, ParamSpec, TypeVar
from uuid import uuid4

from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message, Messages, MsgsAGen
from grafi.common.topics.input_topic import InputTopic
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.tools.llms.llm import LLM
from grafi.tools.tool import Tool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import Workflow
from openinference.semconv.trace import OpenInferenceSpanKindValues


class CallableTool(Tool):
    _a_invoke_impl: Callable[[InvokeContext, List[Message]], MsgsAGen] = None

    def __init__(self, tool_invoke: Callable[[InvokeContext, Messages], MsgsAGen], **kwargs):
        super().__init__(name = "CallableTool",  oi_span_type=OpenInferenceSpanKindValues.TOOL, type="CallableTool",  **kwargs)
        self._a_invoke_impl = tool_invoke

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        if self._a_invoke_impl is None:
            raise NotImplementedError("Must provide `_a__invoke_impl` Callable.")
        yield self._a_invoke_impl(self, invoke_context, input_data)
    
    def invoke(self, invoke_context, input_data) -> Messages:
        inner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(inner_loop)
        results = inner_loop.run_until_complete(self._a_invoke_impl(invoke_context, input_data))
        inner_loop.close()
        return results
    
class CallableNode(Node):
    """A node that wraps a callable tool."""

    def __init__(self, **kwargs):
        condition = kwargs.pop("condition", None)
        super().__init__(**kwargs) 
        self._node_condition = condition
        

    @classmethod
    def builder(cls) -> NodeBaseBuilder:
        """Return a builder for CallableNode."""
        return NodeBaseBuilder(cls)
    
    def can_invoke_with_topics(self, topic_with_messahes) -> bool:
        if (self._node_condition is None):
            return super().can_invoke_with_topics(topic_with_messahes)

        all_subscibed_topics = {topic.name: False for topic in self.subscribed_topics}
        available_topics = all_subscibed_topics | {topic.name: True for topic in topic_with_messahes}
        return eval(self._node_condiiton, __builtins__ ={}, globals=None, locals=available_topics)
    
    def can_invoke(self) -> bool:
            # Evaluate each expression; if any is satisfied, we can invoke.
        return self.can_invoke_with_topics([topic.name for topic in self.subscribed_topics if topic.can_consume(self.name)])

def node(func):
    """
    Decorator to mark a function as a node in the Graphite system.
    This decorator can be used to wrap functions that should be treated as nodes.
    """
    _R = TypeVar("_R", bound=MsgsAGen)
    _P = ParamSpec("_P")

    _node_id = uuid4().hex


    def __wrapper(func: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]) -> Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:        # Generate the node information that wraps this and register it with the wrapping workflow.
        if hasattr(func, "__workflow_node") and func.__workflow_node.get("node_id"):
            raise ValueError(  
                f"Function {func.__name__} is already registered as a node with id {func.__workflow_node['node_id']}. "
                "Please ensure that the node decorator is applied only once."
            )

        # Don't expect any ordering on annotations, decorators will only set certain attributes and are composable.
        func.__workflow_node = (func.__workflow_node or {}) | {
            "node_tool_class": CallableTool,
            "node_name": func.__name__,
            "node_id": _node_id,
            "node_type": "CallableToolNode",
            "tool_invoke": func,
        }
        return func

    return __wrapper(func)


def condition(topic_expression: str):
    def __wrapper(func: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]) -> Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:
        if hasattr(func, "__workflow_node") and func.__workflow_node.get("node_condition"):
            raise ValueError(
                f"Function {func.__name__} is already registered with a condition. "
                "Please ensure that the condition decorator is applied only once."
            )

        # Don't expect any ordering on annotations, decorators will only set certain attributes and are composable.
        func.__workflow_node = (func.__workflow_node or {}) | {
            "node_condition": topic_expression,
        }
        return func
    return __wrapper

def publish_to(*args: str):
    """
    Decorator to mark a function as a node in the Graphite system.
    This decorator can be used to wrap functions that should be treated as nodes.
    """
    _R = TypeVar("_R", bound=MsgsAGen)
    _P = ParamSpec("_P")
 
    def __wrapper(func: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]) -> Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:        # Generate the node information that wraps this and register it with the wrapping workflow.
        if (len(args) == 0):
            raise ValueError("At least one topic must be specified for publishing.")

        registered_topics = []
        if hasattr(func, "__workflow_node"):
            registered_topics += func.__workflow_node.get("node_publish_to", [])
        registered_topics += [*args]

        if (len(registered_topics) != len(set(registered_topics))):
            raise ValueError("Duplicate topics found in the publish_to decorator arguments.")
        # Don't expect any ordering on annotations, decorators will only set certain attributes and are composable.
        func.__workflow_node = getattr(func, "__workflow_node", {})| {
            "node_publish_to": registered_topics,
        }
        return func
    return __wrapper


def subscribe_to(*args: str):
    """
    Decorator to mark a function as a node in the Graphite system.
    This decorator can be used to wrap functions that should be treated as nodes.
    """
    _R = TypeVar("_R", bound=MsgsAGen)
    _P = ParamSpec("_P")
 
    def __wrapper(func: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]) -> Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:        # Generate the node information that wraps this and register it with the wrapping workflow.
        if (len(args) == 0):
            raise ValueError("At least one topic must be specified for publishing.")

        registered_topics = []
        if hasattr(func, "__workflow_node"):
            registered_topics += func.__workflow_node.get("node_subscribe_to", [])
        registered_topics += [*args]

        if (len(registered_topics) != len(set(registered_topics))):
            raise ValueError("Duplicate topics found in the subscribe_to decorator arguments.")

        # Don't expect any ordering on annotations, decorators will only set certain attributes and are composable.
        func.__workflow_node = (getattr(func, "__workflow_node", {})) | {
            "node_subscribe_to": registered_topics,
        }
        return func
    return __wrapper


_T = TypeVar("_T", bound=Workflow)

def workflow(workflow_cls:_T):
    """
    Decorator to mark a function as a workflow in the Graphite system.
    This decorator can be used to wrap functions that should be treated as workflows.
    """
    _R = TypeVar("_R", bound=MsgsAGen)
    _P = ParamSpec("_P")

    _workflow_id = uuid4().hex
    _name = workflow_cls.__name__
    _type = workflow_cls.__name__
    _oi__span_type = workflow_cls.oi_span_type if hasattr(workflow_cls, 'oi_span_type') else OpenInferenceSpanKindValues.AGENT

    @classmethod
    def generate(cls, **kwargs):
        builder = workflow_cls.builder().oi_span_type(_oi__span_type).name(_name).type(_type)
        methods = inspect.getmembers(workflow_cls, predicate=inspect.isfunction)
        
        topics = {}
        for name,method in methods:
            node_data = getattr(method, "__workflow_node", None)
            if node_data:
                publishes_to = node_data.get("node_publish_to")
                subscribes_to = node_data.get("node_subscribe_to")

                if not publish_to:
                    raise ValueError("Node {name} did not provide `publish_to` annotation.")
                
                if not subscribe_to:
                    raise ValueError("Node {name} did not provide `subscribe_to` annotation.")

                for topic_name in publishes_to + subscribes_to:
                    if topic_name == "output_topic":
                        # Special case for output_topic, which is always created
                        topics[topic_name] = OutputTopic(name=topic_name, condition=lambda x: True)
                    elif topic_name == "input_topic":
                        # Special case for output_topic, which is always created
                        topics[topic_name] = InputTopic(name=topic_name, condition=lambda x: True)
                    else:
                        topics[topic_name] = Topic(name=topic_name, condition=lambda x: True)
        for _, method in methods:
            node_data = getattr(method, "__workflow_node", None)
            if node_data:
                node_id = node_data["node_id"]
                node_name = node_data["node_name"]
                node_type = node_data["node_type"]
                tool_invoke = node_data["tool_invoke"]
                node_tool_class = node_data["node_tool_class"]
                publishes_to = node_data["node_publish_to"]
                subscribes_to = node_data["node_subscribe_to"]
                node_condition = node_data.get("node_condition", None)

                node_subscribe_topics = [topics[topic_name] for topic_name in subscribes_to]
                node_publish_topics = [topics[topic_name] for topic_name in publishes_to]
                tool = node_tool_class(tool_invoke=tool_invoke)

                # Build subscription, doesnt matter the pending op, we opverride that useless shit.
                subscriptions = []
                for subscribed_topic in node_subscribe_topics:
                    subscriptions += [SubscriptionBuilder().subscribed_to(subscribed_topic).build()]

                node = CallableNode(
                    node_id=node_id,
                    name = node_name,
                    type = node_type,
                    oi_span_type=_oi__span_type,
                    publish_to=node_publish_topics,
                    subscribed_expressions=subscriptions,
                    tool = tool,
                    condition=node_condition,
                )
                builder.node(node)
        return  builder.build()
    
    workflow_cls.generate = generate
    return workflow_cls
    

@workflow
class FooWorkflow(EventDrivenWorkflow):
    """
    Example workflow that uses the decorators to define nodes and their interactions.
    """

    @node
    @publish_to("output_topic")
    @subscribe_to("input_topic")
    def llm_BIATCH(self, invoke_context: InvokeContext, node_input: List[ConsumeFromTopicEvent]) -> MsgsAGen:
        # Node logic goes here
        print("NODE CALLED")
        print(node_input)

        output_data = [Message(
                role="user",
                content=":D",
                data = ["FOO BAR"]
            )]
        print("EXPECTED OUT")
        print(output_data)
        yield output_data

async def main():
    wkflow = FooWorkflow.generate()
    print("AFTER INSTANTIATION")
    print(wkflow.__dict__)
    input_data = [
        Message(
            role="user",
            content="Hello, my name is Grafi, how can I make your life harder?",
        )
    ]
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid4().hex,
        assistant_request_id=uuid4().hex,
    )

    async for output in wkflow.a_invoke(invoke_context,input_data):
        print("printing ouitput")
        print(output)

if __name__  == "__main__":
    asyncio.run(main())

#class LlmNodeWithLambda(LLM):
#
#def llm():
#    _R = TypeVar("R", boundParent=LLM)
#
#    """Decorator to mark a function as an LLM."""
#    def __wrapper(func: Callable[[], _R]) -> Callable[[], _R]:
#        # Generate the node information that wrap this and register it with the wrapping workflow.
#        func.__my_node_cfg_foo = {
#            
#
#        }
#        return func
#    return __wrapper