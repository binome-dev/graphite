import asyncio
from typing import AsyncIterator
from typing import Callable
from typing import List
from typing import Optional
from typing import Self

from loguru import logger
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_async_event import OutputAsyncEvent
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.topic_base import AGENT_RESERVED_TOPICS
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_base import TopicBaseBuilder


AGENT_OUTPUT_TOPIC = "agent_output_topic"
AGENT_RESERVED_TOPICS.extend([AGENT_OUTPUT_TOPIC])


# OutputTopic handles sync and async publishing of messages to the agent output topic.
class OutputTopic(TopicBase):
    """
    A topic implementation for output events.
    """

    name: str = AGENT_OUTPUT_TOPIC
    event_queue: asyncio.Queue[OutputAsyncEvent] = Field(default_factory=asyncio.Queue)
    active_generators: List[asyncio.Task] = Field(default_factory=list)
    publish_event_handler: Optional[Callable[[OutputTopicEvent], None]] = Field(
        default=None
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def builder(cls) -> "OutputTopicBuilder":
        """
        Returns a builder for OutputTopic.
        """
        return OutputTopicBuilder(cls)

    def reset(self) -> None:
        """Reset the topic to its initial state."""
        # Cancel all active generators
        super().reset()
        for task in self.active_generators:
            if not task.done():
                task.cancel()

        self.active_generators.clear()
        self.event_queue = asyncio.Queue()

    def publish_data(
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> Optional[OutputTopicEvent]:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = OutputTopicEvent(
                invoke_context=invoke_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=self.total_published,
            )
            # Add event to cache and update total_published
            self.add_event(event)
            if self.publish_event_handler:
                self.publish_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    def add_generator(
        self,
        generator: MsgsAGen,
        data: Messages,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        consumed_events: Optional[List[ConsumeFromTopicEvent]] = None,
    ) -> None:
        """Add a Messages async generator to the topic."""
        if consumed_events is None:
            consumed_events = []

        # Start processing the generator immediately
        task = asyncio.create_task(
            self._process_generator(
                generator=generator,
                data=data,
                invoke_context=invoke_context,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                consumed_events=consumed_events,
            )
        )
        self.active_generators.append(task)
        logger.info(f"[{self.name}] Added generator from {publisher_name}")

    async def _process_generator(
        self,
        generator: MsgsAGen,
        data: Messages,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> None:
        """Process a Messages generator and put OutputAsyncEvents in the queue."""
        try:
            result: Messages = data
            if not data:
                result_content = ""
                async for messages in generator:
                    if self.condition(messages):
                        event = OutputAsyncEvent(
                            invoke_context=invoke_context,
                            topic_name=self.name,
                            publisher_name=publisher_name,
                            publisher_type=publisher_type,
                            data=messages,
                            consumed_event_ids=[
                                consumed_event.event_id
                                for consumed_event in consumed_events
                            ],
                            offset=0,
                        )

                        for message in messages:
                            if message.content is not None and isinstance(
                                message.content, str
                            ):
                                result_content += message.content

                        await self.event_queue.put(event)
                    # logger.debug(f"[{self.name}] Event queued from {publisher_name}")

                result = [Message(role="assistant", content=result_content)]
            else:
                if self.condition(data):
                    event = OutputAsyncEvent(
                        invoke_context=invoke_context,
                        topic_name=self.name,
                        publisher_name=publisher_name,
                        publisher_type=publisher_type,
                        data=result,
                        consumed_event_ids=[
                            consumed_event.event_id
                            for consumed_event in consumed_events
                        ],
                        offset=0,
                    )

                    await self.event_queue.put(event)

            if self.condition(result):
                output_topic_event = OutputTopicEvent(
                    invoke_context=invoke_context,
                    topic_name=self.name,
                    publisher_name=publisher_name,
                    publisher_type=publisher_type,
                    data=result,
                    consumed_event_ids=[
                        consumed_event.event_id for consumed_event in consumed_events
                    ],
                    offset=0,
                )

                container.event_store.record_event(output_topic_event)

        except asyncio.CancelledError:
            logger.info(f"[{self.name}] Generator {publisher_name} cancelled")
        except Exception as e:
            logger.error(
                f"[{self.name}] Error processing generator {publisher_name}: {e}"
            )

    async def get_events(self) -> AsyncIterator[OutputAsyncEvent]:
        """Get events as they become available."""
        while self.active_generators or not self.event_queue.empty():
            try:
                # Wait for an event with a short timeout
                event = await asyncio.wait_for(self.event_queue.get(), timeout=0.1)
                yield event

            except asyncio.TimeoutError:
                # Check if any generators are still running
                self.active_generators = [
                    task for task in self.active_generators if not task.done()
                ]
                if not self.active_generators:
                    break
                continue

        # Get any remaining events
        while not self.event_queue.empty():
            try:
                event = self.event_queue.get_nowait()
                yield event

            except asyncio.QueueEmpty:
                break

    async def wait_for_completion(self) -> None:
        """Wait for all generators to complete."""
        if self.active_generators:
            await asyncio.gather(*self.active_generators, return_exceptions=True)

    def to_dict(self):
        return {**super().to_dict()}


class OutputTopicBuilder(TopicBaseBuilder[OutputTopic]):
    """
    Builder for creating instances of Topic.
    """

    def publish_event_handler(
        self, publish_event_handler: Callable[[OutputTopicEvent], None]
    ) -> Self:
        self.kwargs["publish_event_handler"] = publish_event_handler
        return self


agent_output_topic = OutputTopic(name=AGENT_OUTPUT_TOPIC)
