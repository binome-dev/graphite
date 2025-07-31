import inspect
from typing import Any
from typing import Callable
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.topics.topic_event_cache import TopicEventCache


AGENT_INPUT_TOPIC_TYPE = "AgentInput"
AGENT_OUTPUT_TOPIC_TYPE = "AgentOutput"
IN_WORKFLOW_INPUT_TOPIC_TYPE = "InWorkflowInput"
IN_WORKFLOW_OUTPUT_TOPIC_TYPE = "InWorkflowOutput"

# Topic cache configuration
DEFAULT_MAX_CACHE_SIZE = 1000  # Maximum number of events to keep in cache


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system.
    Manages both publishing and consumption of message event IDs using a FIFO cache.
    - name: string (the topic's name)
    - condition: function to determine if a message should be published
    - event_cache: FIFO cache for recently accessed events
    - total_published: total number of events published to this topic
    """

    name: str = Field(default="")
    type: str = Field(default="Topic")
    condition: Callable[[Messages], bool] = Field(default=lambda _: True)
    event_cache: TopicEventCache = Field(default_factory=TopicEventCache)
    publish_event_handler: Optional[Callable] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def publish_data(
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        """
        Publish data to the topic if it meets the condition.
        """
        raise NotImplementedError(
            "Method 'publish_data' must be implemented in subclasses."
        )

    async def a_publish_data(
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        """
        Publish data to the topic if it meets the condition.
        """
        raise NotImplementedError(
            "Method 'publish_data' must be implemented in subclasses."
        )

    def can_consume(self, consumer_name: str) -> bool:
        """
        Checks whether the given node can consume any new/unread messages
        from this topic (i.e., if there are event IDs that the node hasn't
        already consumed).
        """
        return self.event_cache.can_consume(consumer_name)

    def consume(
        self, consumer_name: str
    ) -> List[PublishToTopicEvent | OutputTopicEvent]:
        """
        Retrieve new/unconsumed messages for the given node by fetching them
        from the cache or event store. Once retrieved, the node's
        consumption offset is updated so these messages won't be retrieved again.

        :param consumer_name: A unique identifier for the consuming node.
        :return: A list of new messages that were not yet consumed by this node.
        """

        # Get the new events using the offset range
        new_events = self.event_cache.fetch(consumer_name)

        # Filter to only return PublishToTopicEvent instances for backward compatibility
        return [
            event
            for event in new_events
            if isinstance(event, (PublishToTopicEvent, OutputTopicEvent))
        ]

    async def a_consume(
        self, consumer_name: str, timeout: Optional[float] = None
    ) -> List[TopicEvent]:
        """
        Asynchronously retrieve new/unconsumed messages for the given node by fetching them
        """
        return await self.event_cache.a_fetch(consumer_name, timeout=timeout)

    async def a_commit(self, consumer_name: str, offset: int) -> None:
        await self.event_cache.a_commit_to(consumer_name, offset)

    def reset(self) -> None:
        """
        Reset the topic to its initial state.
        """
        self.event_cache = TopicEventCache(self.name)

    async def a_reset(self) -> None:
        """
        Asynchronously reset the topic to its initial state.
        """
        self.event_cache.reset()
        self.event_cache = TopicEventCache(self.name)

    def restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Restore a topic from a topic event.
        """
        if isinstance(topic_event, PublishToTopicEvent) or isinstance(
            topic_event, OutputTopicEvent
        ):
            self.event_cache.put(topic_event)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            self.event_cache.fetch(
                cid=topic_event.consumer_name, offset=topic_event.offset + 1
            )
            self.event_cache.commit_to(topic_event.consumer_name, topic_event.offset)

    async def a_restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Asynchronously restore a topic from a topic event.
        """
        if isinstance(topic_event, PublishToTopicEvent) or isinstance(
            topic_event, OutputTopicEvent
        ):
            await self.event_cache.a_put(topic_event)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            # Fetch the events for the consumer and commit the offset
            await self.event_cache.a_fetch(
                cid=topic_event.consumer_name, offset=topic_event.offset + 1
            )
            await self.event_cache.a_commit_to(
                topic_event.consumer_name, topic_event.offset
            )

    def add_event(self, event: TopicEvent) -> TopicEvent:
        """f
        Add an event to the topic cache and update total_published.
        This method should be used by subclasses when publishing events.
        """
        if isinstance(event, (PublishToTopicEvent, OutputTopicEvent)):
            return self.event_cache.put(event)

    async def a_add_event(self, event: TopicEvent) -> TopicEvent:
        """
        Asynchronously add an event to the topic cache and update total_published.
        This method should be used by subclasses when publishing events.
        """
        if isinstance(event, (PublishToTopicEvent, OutputTopicEvent)):
            return await self.event_cache.a_put(event)

    def serialize_callable(self) -> dict:
        """
        Serialize the condition field. If it's a function, return the function name.
        If it's a lambda, return the source code.
        """
        if callable(self.condition):
            if inspect.isfunction(self.condition):
                if self.condition.__name__ == "<lambda>":
                    # It's a lambda, extract source code
                    try:
                        source = inspect.getsource(self.condition).strip()
                    except (OSError, TypeError):
                        source = "<unable to retrieve source>"
                    return {"type": "lambda", "code": source}
                else:
                    # It's a regular function, return its name
                    return {"type": "function", "name": self.condition.__name__}
            elif inspect.isbuiltin(self.condition):
                return {"type": "builtin", "name": self.condition.__name__}
            elif hasattr(self.condition, "__call__"):
                # Handle callable objects
                return {
                    "type": "callable_object",
                    "class_name": self.condition.__class__.__name__,
                }
        return {"type": "unknown"}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary representation.
        """
        return {
            "name": self.name,
            "type": self.type,
            "condition": self.serialize_callable(),
        }


T_T = TypeVar("T_T", bound=TopicBase)


class TopicBaseBuilder(BaseBuilder[T_T]):
    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        self.kwargs["type"] = type_name
        return self

    def condition(self, condition: Callable[[Messages], bool]) -> Self:
        self.kwargs["condition"] = condition
        return self
