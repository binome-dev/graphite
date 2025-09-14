"""
This file is part of the Graphite project.

Copyright (c) 2023-2025 Binome Dev and contributors

This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file, You can obtain one at
https://mozilla.org/MPL/2.0/.
"""

from typing import List
import asyncio
from uuid import uuid4
from collections.abc import AsyncGenerator


from grafi.common.events.topic_events.consume_from_topic_event import ConsumeFromTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message, MsgsAGen
from grafi.workflows.decorators import publish_to, subscribe_to, node, workflow
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


@workflow
class SingleNodeWorkflow(EventDrivenWorkflow):
    """
    Example workflow that uses the decorators to define nodes and their interactions. This consist of a single node.
    """

    @node
    @publish_to("output_topic")
    @subscribe_to("input_topic")
    async def hello(self, invoke_context: InvokeContext, node_input: List[Message]) -> MsgsAGen:
        assert(len(node_input) == 1)
        assert(node_input[0].content == "Test message")
        output_data = [Message(
                role="user",
                content="hi",
            )]
        yield output_data


@workflow
class MultiNodeWorkflow(EventDrivenWorkflow):
    """
    Example workflow that uses the decorators to define nodes and their interactions. This consist of a single node.
    """

    @node
    @publish_to("foo_bar_topic")
    @subscribe_to("input_topic")
    async def hello(self, invoke_context: InvokeContext, node_input: List[Message]) -> MsgsAGen:
        print("In hello 2")
        assert(len(node_input) == 1)
        assert(node_input[0].content == "Test message")
        output_data = [Message(
                role="user",
                content="Got test message",
            )]
        yield output_data
    
    @node
    @publish_to("output_topic")
    @subscribe_to("foo_bar_topic")
    async def bye(self, invoke_context: InvokeContext, node_input: List[Message]) -> MsgsAGen:
        print("In bye 3")
        assert(len(node_input) == 1)
        assert(node_input[0].content == "Got test message")

        output_data = [Message(
                role="user",
                content="hi",
            )]
        yield output_data

async def main():
    input_messages = [
        Message(
            role="user",
            content="Test message",
        )
    ]

    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid4().hex,
        assistant_request_id=uuid4().hex,
    )

    event = PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_messages,
        )

    # One node from input to output
#    wkflow = SingleNodeWorkflow.generate()
#    has_messages = False
#    async for output in wkflow.a_invoke(event):
#        has_messages = True
#        assert(len(output.data) == 1)
#        assert(output.data[0].content == "hi")
#    assert(has_messages)

    # Two nodes, from input to foo_bar to output
    wkflow = MultiNodeWorkflow.generate()
    print(wkflow)
    has_messages = False
    async for output in wkflow.a_invoke(event):
        print(output)
        has_messages = True
        assert(len(output.data) == 1)
        assert(output.data[0].content == "hi")
    assert(has_messages)

if __name__  == "__main__":
    asyncio.run(main())