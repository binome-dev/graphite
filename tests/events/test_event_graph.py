import uuid
from datetime import datetime

import pytest

from grafi.common.events.event_graph import EventGraph
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


@pytest.fixture
def mock_events():
    """Creates mock consume and publish events for testing"""
    # Create mock invoke context and messages (minimally required for events)

    exec_context = get_invoke_context()
    test_message = [Message(role="assistant", content="test content")]

    # Create consume events
    consume_1 = ConsumeFromTopicEvent(
        event_id="event_1",
        topic_name="topic1",
        offset=0,
        consumer_name="consumer1",
        consumer_type="test",
        invoke_context=exec_context,
        data=test_message,
        timestamp=datetime(2023, 1, 1, 12, 0),
    )

    consume_2 = ConsumeFromTopicEvent(
        event_id="event_3",
        topic_name="topic2",
        offset=0,
        consumer_name="consumer2",
        consumer_type="test",
        invoke_context=exec_context,
        data=test_message,
        timestamp=datetime(2023, 1, 1, 14, 0),
    )

    # Create publish event that depends on consume_1
    publish = PublishToTopicEvent(
        event_id="event_2",
        topic_name="topic1",
        offset=0,
        publisher_name="publisher1",
        publisher_type="test",
        consumed_event_ids=["event_3"],
        invoke_context=exec_context,
        data=test_message,
        timestamp=datetime(2023, 1, 1, 13, 0),
    )

    return {
        "consume_events": [consume_1, consume_2],
        "topic_events": {
            "event_1": consume_1,
            "event_2": publish,
            "event_3": consume_2,
        },
    }


def test_build_graph(mock_events):
    """Test event graph construction"""
    graph = EventGraph()
    graph.build_graph(mock_events["consume_events"], mock_events["topic_events"])

    assert len(graph.nodes) == 2  # Ensure all nodes were added
    assert len(graph.root_nodes) == 2  # Ensure correct root nodes
    assert (
        mock_events["consume_events"][0].event_id in graph.nodes
    )  # Check node existence
    assert (
        mock_events["consume_events"][1].event_id in graph.nodes
    )  # Check another node


def test_upstream_downstream_relationships(mock_events):
    """Test that upstream and downstream relationships are correctly established"""
    graph = EventGraph()
    graph.build_graph(mock_events["consume_events"], mock_events["topic_events"])

    # Check if event_1 (consume) is upstream of event_2 (publish)
    event_1_node = graph.nodes[mock_events["consume_events"][0].event_id]
    event_3_node = graph.nodes["event_3"]

    print(event_1_node)
    print(event_3_node)

    assert event_1_node.downstream_events == []
    assert event_1_node.upstream_events == [event_3_node.event_id]


def test_topology_sort(mock_events):
    """Test if events are sorted correctly in topological order"""
    graph = EventGraph()
    graph.build_graph(mock_events["consume_events"], mock_events["topic_events"])

    sorted_nodes = graph.get_topology_sorted_events()
    sorted_ids = [node.event_id for node in sorted_nodes]

    # Ensure correct order based on timestamps
    assert sorted_ids == ["event_3", "event_1"]


def test_to_dict_and_from_dict(mock_events):
    """Test serialization and deserialization"""
    graph = EventGraph()
    graph.build_graph(mock_events["consume_events"], mock_events["topic_events"])

    graph_dict = graph.to_dict()
    new_graph = EventGraph.from_dict(graph_dict)

    assert graph_dict == new_graph.to_dict()  # Ensure correct serialization
    assert len(new_graph.nodes) == len(graph.nodes)  # Ensure all nodes are restored
