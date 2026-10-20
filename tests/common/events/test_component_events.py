"""Tests for the component lifecycle events (grafi.common.events.component_events):
twelve classes, each declared as a class, with its event type and the types of
what its component took and gave."""

import inspect
import typing
from typing import List
from typing import Optional
from typing import Type

import pytest

from grafi.common.events import component_events
from grafi.common.events.component_base import AssistantEventBase
from grafi.common.events.component_base import ComponentEvent
from grafi.common.events.component_base import FailedEvent
from grafi.common.events.component_base import InvokeEvent
from grafi.common.events.component_base import NodeEventBase
from grafi.common.events.component_base import RespondEvent
from grafi.common.events.component_base import ToolEventBase
from grafi.common.events.component_base import WorkflowEventBase
from grafi.common.events.component_events import AssistantFailedEvent
from grafi.common.events.component_events import AssistantInvokeEvent
from grafi.common.events.component_events import AssistantRespondEvent
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import NodeInvokeEvent
from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.component_events import WorkflowFailedEvent
from grafi.common.events.component_events import WorkflowInvokeEvent
from grafi.common.events.component_events import WorkflowRespondEvent
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.import_ref import reference_to
from grafi.common.models.message import Messages

# Each event class, with its event type and the base of its component.
EVENT_CLASSES = [
    (NodeInvokeEvent, EventType.NODE_INVOKE, NodeEventBase),
    (NodeRespondEvent, EventType.NODE_RESPOND, NodeEventBase),
    (NodeFailedEvent, EventType.NODE_FAILED, NodeEventBase),
    (ToolInvokeEvent, EventType.TOOL_INVOKE, ToolEventBase),
    (ToolRespondEvent, EventType.TOOL_RESPOND, ToolEventBase),
    (ToolFailedEvent, EventType.TOOL_FAILED, ToolEventBase),
    (WorkflowInvokeEvent, EventType.WORKFLOW_INVOKE, WorkflowEventBase),
    (WorkflowRespondEvent, EventType.WORKFLOW_RESPOND, WorkflowEventBase),
    (WorkflowFailedEvent, EventType.WORKFLOW_FAILED, WorkflowEventBase),
    (AssistantInvokeEvent, EventType.ASSISTANT_INVOKE, AssistantEventBase),
    (AssistantRespondEvent, EventType.ASSISTANT_RESPOND, AssistantEventBase),
    (AssistantFailedEvent, EventType.ASSISTANT_FAILED, AssistantEventBase),
]

LIFECYCLES = {"Invoke": InvokeEvent, "Respond": RespondEvent, "Failed": FailedEvent}


def _ids(case: object) -> str:
    return case.__name__ if inspect.isclass(case) else ""


def test_the_module_declares_the_twelve_event_classes() -> None:
    assert sorted(component_events.__all__) == sorted(
        cls.__name__ for cls, _, _ in EVENT_CLASSES
    )
    assert len(EVENT_CLASSES) == 12
    declared = [
        name
        for name, value in vars(component_events).items()
        if inspect.isclass(value) and value.__module__ == component_events.__name__
    ]
    assert sorted(declared) == sorted(component_events.__all__)


@pytest.mark.parametrize("cls, event_type, base", EVENT_CLASSES, ids=_ids)
def test_each_event_is_a_class_of_its_type_and_component(
    cls: Type[ComponentEvent], event_type: EventType, base: Type[ComponentEvent]
) -> None:
    assert inspect.isclass(cls)
    assert cls.__module__ == component_events.__name__
    assert cls.__qualname__ == cls.__name__  # At the top level, as declared.
    assert reference_to(cls) == f"{component_events.__name__}:{cls.__name__}"
    assert issubclass(cls, ComponentEvent) and issubclass(cls, base)
    lifecycle = next(k for k in LIFECYCLES if cls.__name__.endswith(f"{k}Event"))
    assert issubclass(cls, LIFECYCLES[lifecycle])
    assert cls.model_fields["event_type"].default is event_type
    assert cls.model_fields["event_type"].annotation is EventType


@pytest.mark.parametrize("cls, event_type, base", EVENT_CLASSES, ids=_ids)
def test_each_event_class_is_usable_as_an_annotation(
    cls: Type[ComponentEvent], event_type: EventType, base: Type[ComponentEvent]
) -> None:
    """A real class, not an alias made at import time: a function annotated
    with it, or a list of it, resolves its hints to the class itself."""

    def handle(event: cls, events: List[cls]) -> Optional[cls]:  # type: ignore[valid-type]
        return event

    hints = typing.get_type_hints(handle)

    assert hints["event"] is cls
    assert hints["events"] == List[cls]
    assert hints["return"] == Optional[cls]
    assert typing.get_type_hints(cls)["event_type"] is EventType


def test_node_events_take_consumed_events_and_give_a_publication() -> None:
    assert NodeInvokeEvent.model_fields["input_data"].annotation == (
        List[ConsumeFromTopicEvent]
    )
    assert NodeRespondEvent.model_fields["input_data"].annotation == (
        List[ConsumeFromTopicEvent]
    )
    assert NodeRespondEvent.model_fields["output_data"].annotation == (
        Optional[PublishToTopicEvent]
    )
    assert NodeFailedEvent.model_fields["input_data"].annotation == (
        List[ConsumeFromTopicEvent]
    )
    assert "output_data" not in NodeInvokeEvent.model_fields
    assert "output_data" not in NodeFailedEvent.model_fields
    assert NodeFailedEvent.model_fields["error"].annotation is str
    assert "subscribed_topics" in NodeRespondEvent.model_fields
    assert "publish_to_topics" in NodeRespondEvent.model_fields


def test_tool_events_take_and_give_messages() -> None:
    assert ToolInvokeEvent.model_fields["input_data"].annotation == Messages
    assert ToolRespondEvent.model_fields["input_data"].annotation == Messages
    assert ToolRespondEvent.model_fields["output_data"].annotation == Messages
    assert ToolFailedEvent.model_fields["input_data"].annotation == Messages


@pytest.mark.parametrize(
    "invoke, respond, failed",
    [
        (WorkflowInvokeEvent, WorkflowRespondEvent, WorkflowFailedEvent),
        (AssistantInvokeEvent, AssistantRespondEvent, AssistantFailedEvent),
    ],
    ids=["workflow", "assistant"],
)
def test_workflow_and_assistant_events_take_a_publication_and_give_consumptions(
    invoke: Type[ComponentEvent],
    respond: Type[ComponentEvent],
    failed: Type[ComponentEvent],
) -> None:
    assert invoke.model_fields["input_data"].annotation is PublishToTopicEvent
    assert respond.model_fields["input_data"].annotation is PublishToTopicEvent
    assert respond.model_fields["output_data"].annotation == (
        List[ConsumeFromTopicEvent]
    )
    assert failed.model_fields["input_data"].annotation is PublishToTopicEvent
    assert "subscribed_topics" not in respond.model_fields
