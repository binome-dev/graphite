import heapq
from typing import Any
from typing import Dict
from typing import List
from typing import Set
from typing import Union

from pydantic import BaseModel
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.event_id import EventId


class EventGraphNode(BaseModel):
    event_id: EventId
    event: TopicEvent
    upstream_events: List[EventId] = Field(default=[])
    downstream_events: List[EventId] = Field(default=[])

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event.to_dict(),
            "upstream_events": self.upstream_events,
            "downstream_events": self.downstream_events,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventGraphNode":
        return cls(
            event_id=data["event_id"],
            event=ConsumeFromTopicEvent.from_dict(data["event"]),
            upstream_events=data["upstream_events"],
            downstream_events=data["downstream_events"],
        )


class EventGraph(BaseModel):
    nodes: Dict[EventId, EventGraphNode] = Field(default={})
    root_nodes: List[EventGraphNode] = Field(default=[])

    def _add_event(self, event: TopicEvent) -> EventGraphNode:
        """Add a new node to the graph if it doesn't exist"""
        if event.event_id not in self.nodes:
            self.nodes[event.event_id] = EventGraphNode(
                event_id=event.event_id, event=event
            )
        return self.nodes[event.event_id]

    def build_graph(
        self,
        consume_events: List[ConsumeFromTopicEvent],
        topic_events: Dict[str, Union[ConsumeFromTopicEvent, PublishToTopicEvent]],
    ) -> None:
        """
        Build the event graph from a list of consume events and topic events.

        Args:
            consume_events: List of ConsumeFromTopicEvent to start building from
            topic_events: Dictionary mapping topic names to TopicEvents
        """
        # Clear existing graph
        self.nodes.clear()
        self.root_nodes.clear()

        # Create a mapping of "topic_name::offset" -> publish event
        topic_offset_to_publish = {
            f"{event.topic_name}::{event.offset}": event
            for event in topic_events.values()
            if isinstance(event, PublishToTopicEvent)
        }

        # Track visited events to avoid cycles
        visited: Set[EventId] = set()

        def build_node_relations(consume_event: ConsumeFromTopicEvent) -> None:
            if consume_event.event_id in visited:
                return

            visited.add(consume_event.event_id)

            current_node = self._add_event(consume_event)

            # Find the corresponding publish event
            publish_key = f"{consume_event.topic_name}::{consume_event.offset}"
            publish_event = topic_offset_to_publish.get(publish_key)

            if publish_event:
                # Process consumed events of the publish event
                for consumed_id in publish_event.consumed_event_ids:
                    consumed_event = topic_events.get(consumed_id)
                    if isinstance(consumed_event, ConsumeFromTopicEvent):
                        child_node = self._add_event(consumed_event)
                        current_node.upstream_events.append(child_node.event_id)
                        build_node_relations(consumed_event)

        # Build the graph starting from each consume event
        for event in consume_events:
            node = self._add_event(event)
            self.root_nodes.append(node)
            build_node_relations(event)

        # Add downstream events
        for node in self.nodes.values():
            for up_id in node.upstream_events:
                self.nodes[up_id].downstream_events.append(node.event_id)

    def get_root_event_nodes(self) -> List[EventGraphNode]:
        """Get all root nodes in the graph"""
        return self.root_nodes

    def get_topology_sorted_events(self) -> List[EventGraphNode]:
        """Get all events in the graph in topological order"""
        # Keep track of visited nodes and sorted nodes
        # n = len(self.nodes)

        # Compute in-degrees
        in_degree: Dict[EventId, int] = {}
        for node in self.nodes.values():
            in_degree[node.event_id] = 0  # initialize

        # from root nodes, reversely explore the graph to compute in-degrees

        for node in self.nodes.values():
            for up_id in node.upstream_events:
                in_degree[up_id] += 1

        # 3) Initialize a min-heap with (timestamp, event_id) for nodes with in_degree == 0
        min_heap: List[tuple] = []
        for node in self.nodes.values():
            if in_degree[node.event_id] == 0:
                # We push a tuple (timestamp, event_id) so that
                # - primary sort is by timestamp reversely
                # - secondary sort (tiebreak) is by event_id
                heapq.heappush(
                    min_heap, (-node.event.timestamp.timestamp(), node.event_id)
                )

        result: List[EventGraphNode] = []
        count_processed = 0

        # 4) Process nodes in ascending (-timestamp, event_id) order
        while min_heap:
            ts, ev_id = heapq.heappop(min_heap)
            current_node = self.nodes[ev_id]
            result.append(current_node)
            count_processed += 1

            # 5) Decrement in-degree of upstream nodes
            for up_id in current_node.upstream_events:
                in_degree[up_id] -= 1
                # If a upstream node now has in-degree 0, push into heap
                if in_degree[up_id] == 0:
                    upstream_node = self.nodes[up_id]
                    heapq.heappush(
                        min_heap,
                        (
                            -upstream_node.event.timestamp.timestamp(),
                            upstream_node.event_id,
                        ),
                    )

        ordered_result = list(reversed(result))

        return ordered_result

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "root_nodes": [node.to_dict() for node in self.root_nodes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventGraph":
        return cls(
            nodes={k: EventGraphNode.from_dict(v) for k, v in data["nodes"].items()},
            root_nodes=[EventGraphNode.from_dict(node) for node in data["root_nodes"]],
        )
