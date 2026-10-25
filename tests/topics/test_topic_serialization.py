"""
Tests for saving topics and loading them back: a topic's JSON form names its
class, and ``TopicBase.model_validate`` builds that class (it replaced
TopicFactory).
"""

from typing import Type

import pytest
from pydantic import ValidationError

from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


class CustomTopic(Topic):
    """A user's topic, with a field of its own."""

    retention: int = 3


@pytest.mark.parametrize(
    ("topic_class", "class_path", "topic_type"),
    [
        (Topic, "grafi.topics.topic_impl.topic:Topic", TopicType.DEFAULT_TOPIC_TYPE),
        (
            InputTopic,
            "grafi.topics.topic_impl.input_topic:InputTopic",
            TopicType.AGENT_INPUT_TOPIC_TYPE,
        ),
        (
            OutputTopic,
            "grafi.topics.topic_impl.output_topic:OutputTopic",
            TopicType.AGENT_OUTPUT_TOPIC_TYPE,
        ),
        (
            InWorkflowInputTopic,
            "grafi.topics.topic_impl.in_workflow_input_topic:InWorkflowInputTopic",
            TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE,
        ),
    ],
)
def test_topic_round_trip_restores_subclass(
    topic_class: Type[TopicBase], class_path: str, topic_type: TopicType
):
    """Each topic class saves its import path and loads back as itself."""
    original = topic_class(name="some_topic")

    data = original.model_dump(mode="json")

    assert data == {"class": class_path, "name": "some_topic", "type": topic_type.value}
    assert next(iter(data)) == "class"  # The class comes first.

    restored = TopicBase.model_validate(data)

    assert type(restored) is topic_class
    assert restored.name == "some_topic"
    assert restored.type == topic_type


def test_in_workflow_output_topic_round_trip_keeps_paired_names():
    """InWorkflowOutputTopic's paired input topic names survive a round trip."""
    original = InWorkflowOutputTopic(
        name="roundtrip_topic",
        paired_in_workflow_input_topic_names=["topic1", "topic2"],
    )

    data = original.model_dump(mode="json")

    assert data == {
        "class": (
            "grafi.topics.topic_impl.in_workflow_output_topic:InWorkflowOutputTopic"
        ),
        "name": "roundtrip_topic",
        "type": "InWorkflowOutputTopic",
        "paired_in_workflow_input_topic_names": ["topic1", "topic2"],
    }

    restored = TopicBase.model_validate(data)

    assert isinstance(restored, InWorkflowOutputTopic)
    assert restored.name == original.name
    assert restored.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
    assert restored.paired_in_workflow_input_topic_names == ["topic1", "topic2"]
    assert restored.model_dump(mode="json") == data


def test_dump_excludes_event_queue():
    """A topic's events are never saved; a loaded topic gets a fresh queue."""
    original = Topic(name="queue_topic")

    for data in (original.model_dump(), original.model_dump(mode="json")):
        assert "event_queue" not in data

    restored = TopicBase.model_validate(original.model_dump(mode="json"))

    assert isinstance(restored.event_queue, InMemTopicEventQueue)
    assert restored.event_queue is not original.event_queue


def test_user_topic_subclass_loads_as_itself():
    """A topic subclass loads as itself, with its own fields."""
    data = CustomTopic(name="custom", retention=7).model_dump(mode="json")

    assert data["class"] == f"{__name__}:CustomTopic"
    assert data["retention"] == 7

    restored = TopicBase.model_validate(data)

    assert type(restored) is CustomTopic
    assert restored.retention == 7


def test_topic_without_class_loads_as_called_class():
    """Without a class, the class called is built from the fields."""
    restored = InputTopic.model_validate({"name": "plain"})

    assert type(restored) is InputTopic
    assert restored.type == TopicType.AGENT_INPUT_TOPIC_TYPE


def test_topic_loads_with_topic_type_enum():
    """The type field accepts TopicType values too."""
    restored = TopicBase.model_validate(
        {
            "class": "grafi.topics.topic_impl.topic:Topic",
            "name": "test_topic",
            "type": TopicType.DEFAULT_TOPIC_TYPE,
        }
    )

    assert isinstance(restored, Topic)
    assert restored.type == TopicType.DEFAULT_TOPIC_TYPE


def test_topic_unknown_type_fails():
    """An unknown topic type is an error."""
    with pytest.raises(ValidationError, match="type"):
        TopicBase.model_validate(
            {
                "class": "grafi.topics.topic_impl.topic:Topic",
                "name": "test_topic",
                "type": "UnknownTopicType",
            }
        )


def test_class_of_another_kind_fails():
    """The class must be a subclass of the class it is loaded through."""
    with pytest.raises(ManifestError, match="is not a subclass of TopicBase"):
        TopicBase.model_validate({"class": "grafi.nodes.node:Node", "name": "n"})

    # A sibling topic class is not an InputTopic either.
    data = OutputTopic(name="out").model_dump(mode="json")
    with pytest.raises(ManifestError, match="is not a subclass of InputTopic"):
        InputTopic.model_validate(data)


def test_class_from_untrusted_module_fails():
    """Loading never imports a module that is not trusted."""
    with pytest.raises(UntrustedImportError, match="outside the trusted modules"):
        TopicBase.model_validate({"class": "untrusted_mod.topics:Evil", "name": "n"})


def test_class_that_cannot_be_imported_fails():
    """A class path that does not import is an error."""
    with pytest.raises(ManifestError, match="Cannot import"):
        TopicBase.model_validate(
            {"class": "grafi.topics.topic_impl.topic:NoSuchTopic", "name": "n"}
        )


def test_topic_manifest_round_trip():
    """A topic's manifest envelope names its kind, and loads back."""
    original = InWorkflowOutputTopic(
        name="approval_request", paired_in_workflow_input_topic_names=["approve"]
    )

    manifest = original.to_manifest()

    assert manifest["apiVersion"] == "grafi/v2"
    assert manifest["kind"] == "Topic"
    assert manifest["spec"] == original.model_dump(mode="json")

    restored = TopicBase.from_manifest(manifest)

    assert isinstance(restored, InWorkflowOutputTopic)
    assert restored.paired_in_workflow_input_topic_names == ["approve"]


def test_topic_manifest_of_another_kind_fails():
    """A manifest claiming another kind is refused."""
    manifest = {**Topic(name="t").to_manifest(), "kind": "Node"}

    with pytest.raises(
        ManifestError,
        match="The manifest's kind is 'Node', but its spec is of kind 'Topic'.",
    ):
        TopicBase.from_manifest(manifest)


def test_topic_manifest_without_a_kind_fails():
    """The kind is checked before anything is built, and is required."""
    manifest = Topic(name="t").to_manifest()
    del manifest["kind"]

    with pytest.raises(ManifestError, match="The manifest's kind is None"):
        TopicBase.from_manifest(manifest)


def test_topic_manifest_spec_must_name_its_class():
    manifest = Topic(name="t").to_manifest()
    del manifest["spec"]["class"]

    with pytest.raises(ManifestError, match="with its class"):
        TopicBase.from_manifest(manifest)


def test_python_dump_names_the_class_itself_and_round_trips():
    """A python-mode dump holds the class, not its path, and loads back."""
    original = CustomTopic(name="custom", retention=7)

    data = original.model_dump()

    assert data == {
        "class": CustomTopic,
        "name": "custom",
        "type": TopicType.DEFAULT_TOPIC_TYPE,
        "retention": 7,
    }
    restored = TopicBase.model_validate(data)
    assert type(restored) is CustomTopic
    assert restored.retention == 7


def test_unknown_field_fails():
    """A field the topic does not have is refused, not ignored."""
    data = Topic(name="t").model_dump(mode="json")

    with pytest.raises(ValidationError, match="retention"):
        TopicBase.model_validate({**data, "retention": 3})


def test_constructing_with_another_class_fails():
    """Constructing a topic from data naming another class is refused."""
    data = OutputTopic(name="out").model_dump(mode="json")

    with pytest.raises(ManifestError, match="load it with Topic.model_validate"):
        Topic(**data)
