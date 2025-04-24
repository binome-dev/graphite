import inspect
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Self

from pydantic import BaseModel
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages


AGENT_INPUT_TOPIC = "agent_input_topic"
HUMAN_REQUEST_TOPIC = "human_request_topic"

AGENT_RESERVED_TOPICS = [
    AGENT_INPUT_TOPIC,
    HUMAN_REQUEST_TOPIC,
]


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system.
    Manages both publishing and consumption of message event IDs.
    - name: string (the topic's name)
    - condition: function to determine if a message should be published
    - event_store: reference to the event store to fetch messages
    - topic_events: list of all published event IDs that met the condition
    - consumption_offsets: a mapping from node name -> how many events that node has consumed
    """

    name: str = Field(default="")
    condition: Callable[[Messages], bool] = Field(default=lambda _: True)
    consumption_offsets: Dict[str, int] = {}
    topic_events: List[TopicEvent] = []
    publish_event_handler: Optional[Callable] = None

    class Builder:

        _topic: "TopicBase"

        def __init__(self) -> None:
            self._topic = self._init_tool()

        def _init_tool(self) -> "TopicBase":
            return TopicBase.model_construct()

        def name(self, name: str) -> Self:
            if name in AGENT_RESERVED_TOPICS:
                raise ValueError(f"Topic name '{name}' is reserved for the agent.")
            self._topic.name = name
            return self

        def condition(self, condition: Callable[[Messages], bool]) -> Self:
            self._topic.condition = condition
            return self

        def build(self) -> "TopicBase":
            return self._topic

    def publish_data(
        self,
        execution_context: ExecutionContext,
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
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        total_published = len(self.topic_events)
        return already_consumed < total_published

    def consume(self, consumer_name: str) -> List[PublishToTopicEvent]:
        """
        Retrieve new/unconsumed messages for the given node by fetching them
        from the event store based on event IDs. Once retrieved, the node's
        consumption offset is updated so these messages won't be retrieved again.

        :param node_id: A unique identifier for the consuming node.
        :return: A list of new messages that were not yet consumed by this node.
        """
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        total_published = len(self.topic_events)

        if already_consumed >= total_published:
            return []

        # Get the new event IDs
        new_events = self.topic_events[already_consumed:]

        # Update the offset
        self.consumption_offsets[consumer_name] = total_published

        return new_events

    def reset(self) -> None:
        """
        Reset the topic to its initial state.
        """
        self.topic_events = []
        self.consumption_offsets = {}

    def restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Restore a topic from a list of topic events.
        """
        if isinstance(topic_event, PublishToTopicEvent) or isinstance(
            topic_event, OutputTopicEvent
        ):
            self.topic_events.append(topic_event)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            self.consumption_offsets[topic_event.consumer_name] = topic_event.offset + 1

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "condition": self.serialize_callable()}

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
