"""
Tests for TopicFactory - Factory class for deserializing topics.
"""

import base64

import cloudpickle
import pytest

from grafi.topics.topic_factory import TopicFactory
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


def test_topic_factory_default_topic():
    """Test factory creates default Topic correctly."""
    condition = lambda x: True
    data = {
        "name": "test_topic",
        "type": "Topic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, Topic)
    assert topic.name == "test_topic"
    assert topic.type == TopicType.DEFAULT_TOPIC_TYPE


def test_topic_factory_input_topic():
    """Test factory creates InputTopic correctly."""
    condition = lambda x: True
    data = {
        "name": "input_topic",
        "type": "AgentInputTopic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, InputTopic)
    assert topic.name == "input_topic"
    assert topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE


def test_topic_factory_output_topic():
    """Test factory creates OutputTopic correctly."""
    condition = lambda x: True
    data = {
        "name": "output_topic",
        "type": "AgentOutputTopic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, OutputTopic)
    assert topic.name == "output_topic"
    assert topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE


def test_topic_factory_in_workflow_input_topic():
    """Test factory creates InWorkflowInputTopic correctly."""
    condition = lambda x: True
    data = {
        "name": "in_workflow_input",
        "type": "InWorkflowInputTopic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, InWorkflowInputTopic)
    assert topic.name == "in_workflow_input"
    assert topic.type == TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE


def test_topic_factory_in_workflow_output_topic():
    """Test factory creates InWorkflowOutputTopic correctly."""
    condition = lambda x: True
    data = {
        "name": "in_workflow_output",
        "type": "InWorkflowOutputTopic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
        "paired_in_workflow_input_topic_names": ["approval", "rejection"],
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, InWorkflowOutputTopic)
    assert topic.name == "in_workflow_output"
    assert topic.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
    assert topic.paired_in_workflow_input_topic_names == ["approval", "rejection"]


def test_topic_factory_with_topic_type_enum():
    """Test factory works with TopicType enum values."""
    condition = lambda x: True
    data = {
        "name": "test_topic",
        "type": TopicType.DEFAULT_TOPIC_TYPE,
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    topic = TopicFactory.from_dict(data)

    assert isinstance(topic, Topic)
    assert topic.name == "test_topic"


def test_topic_factory_unknown_type_string():
    """Test factory raises ValueError for unknown type string."""
    condition = lambda x: True
    data = {
        "name": "test_topic",
        "type": "UnknownTopicType",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    with pytest.raises(ValueError, match="Unknown topic type string"):
        TopicFactory.from_dict(data)


def test_topic_factory_missing_type():
    """Test factory raises KeyError when type is missing."""
    condition = lambda x: True
    data = {
        "name": "test_topic",
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    with pytest.raises(KeyError, match="Missing required key 'type'"):
        TopicFactory.from_dict(data)


def test_topic_factory_invalid_type():
    """Test factory raises ValueError for invalid type format."""
    condition = lambda x: True
    data = {
        "name": "test_topic",
        "type": 12345,  # Invalid type
        "condition": base64.b64encode(cloudpickle.dumps(condition)).decode("utf-8"),
    }

    with pytest.raises(ValueError, match="Invalid topic type"):
        TopicFactory.from_dict(data)


def test_topic_factory_roundtrip():
    """Test serialization and deserialization roundtrip."""
    # Create original topic
    original = InWorkflowOutputTopic(
        name="roundtrip_topic",
        paired_in_workflow_input_topic_names=["topic1", "topic2"],
    )

    # Serialize to dict
    data = original.to_dict()

    # Deserialize back
    restored = TopicFactory.from_dict(data)

    # Verify
    assert isinstance(restored, InWorkflowOutputTopic)
    assert restored.name == original.name
    assert restored.type == original.type
    assert (
        restored.paired_in_workflow_input_topic_names
        == original.paired_in_workflow_input_topic_names
    )


def test_topic_factory_get_registered_types():
    """Test getting registered types returns expected registry."""
    registered = TopicFactory.get_registered_types()

    assert TopicType.DEFAULT_TOPIC_TYPE in registered
    assert TopicType.AGENT_INPUT_TOPIC_TYPE in registered
    assert TopicType.AGENT_OUTPUT_TOPIC_TYPE in registered
    assert TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE in registered
    assert TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE in registered

    assert registered[TopicType.DEFAULT_TOPIC_TYPE] == Topic
    assert registered[TopicType.AGENT_INPUT_TOPIC_TYPE] == InputTopic
    assert registered[TopicType.AGENT_OUTPUT_TOPIC_TYPE] == OutputTopic
    assert registered[TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE] == InWorkflowInputTopic
    assert registered[TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE] == InWorkflowOutputTopic
