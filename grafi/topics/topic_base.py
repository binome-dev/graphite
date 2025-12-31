import base64
import inspect
from typing import Any
from typing import Callable
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

import cloudpickle
from loguru import logger
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.message import Messages
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_event_queue import TopicEventQueue
from grafi.topics.topic_types import TopicType


def serialize_condition(fn: Callable) -> str:
    try:
        # TODO: improve serialization to handle more cases
        src = inspect.getsource(fn).strip()

        # Case A: Field(default=lambda ...)
        if "Field(" in src and "default=" in src and "lambda" in src:
            s = src[src.index("lambda") :].strip()
            # remove trailing junk from Field(...), e.g. "lambda _: True)"
            s = s.rstrip().rstrip("),")
            return s

        # Case B: assignment to lambda
        if "=" in src and "lambda" in src:
            rhs = src.split("=", 1)[1].strip()
            if rhs.startswith("lambda"):
                return rhs.rstrip().rstrip("),")

        # Case C: lambda literal already
        if src.startswith("lambda"):
            return src.rstrip().rstrip("),")

        # Case D: def function
        return src
    except Exception:
        raise ValueError(
            f"Cannot serialize callable {fn}. "
            "Define it in a module, not dynamically."
        )


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system.
    Manages both publishing and consumption of message event IDs using a FIFO cache.
    - name: string (the topic's name)
    - condition: function to determine if a message should be published
    - event_queue: FIFO cache for recently accessed events
    - total_published: total number of events published to this topic
    """

    name: str = Field(default="")
    type: TopicType = Field(default=TopicType.DEFAULT_TOPIC_TYPE)
    condition: Callable[[PublishToTopicEvent], bool] = Field(default=lambda _: True)
    event_queue: TopicEventQueue = Field(default_factory=InMemTopicEventQueue)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> PublishToTopicEvent:
        """
        Publish data to the topic if it meets the condition.
        """
        try:
            condition_met = self.condition(publish_event)
        except Exception as e:
            # Condition evaluation failed (e.g., IndexError on empty data)
            # Treat as condition not met
            logger.debug(
                f"[{self.name}] Condition evaluation failed: {e}. "
                "Treating as condition not met."
            )
            condition_met = False

        if condition_met:
            event = publish_event.model_copy(
                update={
                    "name": self.name,
                    "type": self.type,
                },
                deep=True,
            )
            return await self.add_event(event)
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    async def can_consume(self, consumer_name: str) -> bool:
        """
        Checks whether the given node can consume any new/unread messages
        from this topic (i.e., if there are event IDs that the node hasn't
        already consumed).
        """
        return await self.event_queue.can_consume(consumer_name)

    async def consume(
        self, consumer_name: str, timeout: Optional[float] = None
    ) -> List[TopicEvent]:
        """
        Asynchronously retrieve new/unconsumed messages for the given node by fetching them
        """
        return await self.event_queue.fetch(consumer_name, timeout=timeout)

    async def commit(self, consumer_name: str, offset: int) -> None:
        await self.event_queue.commit_to(consumer_name, offset)

    async def reset(self) -> None:
        """
        Asynchronously reset the topic to its initial state.
        """
        await self.event_queue.reset()

    async def restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Asynchronously restore a topic from a topic event.
        """
        if isinstance(topic_event, PublishToTopicEvent):
            await self.event_queue.put(topic_event)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            # Fetch the events for the consumer and commit the offset
            await self.event_queue.fetch(
                consumer_id=topic_event.consumer_name, offset=topic_event.offset + 1
            )
            await self.event_queue.commit_to(
                topic_event.consumer_name, topic_event.offset
            )

    async def add_event(self, event: TopicEvent) -> TopicEvent:
        """
        Asynchronously add an event to the topic cache and update total_published.
        This method should be used by subclasses when publishing events.
        """
        if isinstance(event, PublishToTopicEvent):
            return await self.event_queue.put(event)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary representation.
        """
        try:
            code = serialize_condition(self.condition)
        except (OSError, TypeError):
            code = ""

        return {
            "name": self.name,
            "type": self.type.value,
            "condition": {
                "base64": base64.b64encode(cloudpickle.dumps(self.condition)).decode(
                    "utf-8"
                ),
                "code": code,
            },
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "TopicBase":
        """
        Create a TopicBase instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the TopicBase.

        Returns:
            TopicBase: A TopicBase instance created from the dictionary.
        """
        condition_data = data["condition"]
        if isinstance(condition_data, dict):
            encoded_condition = condition_data["base64"]
        else:
            encoded_condition = condition_data

        return cls(
            name=data["name"],
            type=data["type"],
            condition=cloudpickle.loads(
                base64.b64decode(encoded_condition.encode("utf-8"))
            ),
        )


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
