"""
This file is part of the Graphite project.

Copyright (c) 2023-2025 Binome Dev and contributors

This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file, You can obtain one at
https://mozilla.org/MPL/2.0/.
"""


from ast import ParamSpec
import asyncio
from collections.abc import Callable
import inspect
from typing import List, TypeVar
from uuid import uuid4

from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from openinference.semconv.trace import OpenInferenceSpanKindValues
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages, MsgsAGen
from grafi.common.topics.input_topic import InputTopic
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.nodes.node import Node
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.tools.tool import Tool


class CallableTool(Tool):
    """A Tool that wraps a callable function, that can be injected from a decorator context. This is an internal
       detail and not part of the public API.
    """

    # Wrapper around callable.
    _a_invoke_impl: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen] = None

    def __init__(self, tool_invoke: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen], **kwargs):
        super().__init__(name="CallableTool", oi_span_type=OpenInferenceSpanKindValues.TOOL, type="CallableTool", **kwargs)
        self._a_invoke_impl = tool_invoke


    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        if self._a_invoke_impl is None:
            raise NotImplementedError("Must provide `_a__invoke_impl` Callable.")
        async for res in self._a_invoke_impl(self, invoke_context, input_data):
            yield res

    def invoke(self, invoke_context, input_data) -> Messages:
        """ Synchronously call the a_invoke_imnpl."""

        async def a_invoke_bridge(invoke_context, input_data) -> Messages:
            """ Async wrapper around async invoke that accumulates all the results."""
            results = []
            async for res in self.a_invoke(invoke_context, input_data):
                results.extend(res)
            return results

        inner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(inner_loop)
        results = inner_loop.run_until_complete(a_invoke_bridge(invoke_context, input_data))
        inner_loop.close()
        return results
    
class CallableNode(Node):
    """A Node that wraps a callable tool, that can be injected from a decorator context. This is an internal
        detail and not part of the public API.

        Unlike common Node, `condition` is evaluated at the output generation time on the node side, allowing nodes to covnerge
        on the same topic, under different circumstances.
    """

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
    """Decorator to mark a function as a node within a workflow.
    
    This decorator can be used to wrap functions that should be treated as nodes, providing a more declarative style
    for defining a workflow.
    """
    _node_id = uuid4().hex


    def __wrapper(func: Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]) -> Callable[[InvokeContext, List[ConsumeFromTopicEvent]], MsgsAGen]:       
        """Generate the node information that wraps this and register it with the wrapping workflow.
        """
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

def trigger_when(topic_expression: str):
    """
    `trigger_when` defines the trigger condition for a node based on the topic names. Expressions are written as an expression that MUST
    evaluate to a boolean. Contextual variables are the topic names, which evaluate to True if there is a new message on that topic.
    """
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
    `node` decorated functions can be further decorated with this to specify the topics they publish to.
    """

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
    `node` decorated functions can be further decorated with this to specify the topics they subscribe to.
    """
 
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

def workflow(workflow_class):
    """
    This deocorator enhances the annotated class to behave as an event driven workflow and providing a class method that
    allows generating the workflow from the decorators applied to its methods.
    """
    
    _workflow_id = uuid4().hex
    _name = workflow_class.__name__
    _type = workflow_class.__name__
    _oi__span_type = workflow_class.oi_span_type if hasattr(workflow_class, 'oi_span_type') else OpenInferenceSpanKindValues.AGENT


    @classmethod
    def generate(cls, **kwargs):
        builder = workflow_class.builder().oi_span_type(_oi__span_type).name(_name).type(_type)
        methods = inspect.getmembers(workflow_class, predicate=inspect.isfunction)
        
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

                # Just meet the constructor requirements, the `CallableNode` will override the subscription evaluation.
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

    # Don't expect any ordering on annotations, decorators will only set certain attributes and are composable.
    workflow_class.__is_workflow = True
    workflow_class.__workflow_id = _workflow_id
    workflow_class.__workflow_name = _name
    workflow_class.__workflow_type = _type
    workflow_class.__workflow_oi_span_type = _oi__span_type
    workflow_class.generate = generate
    return workflow_class