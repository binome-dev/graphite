"""
Simplified event base classes with clear hierarchy.

Reduces code duplication and provides consistent patterns for all events.
"""

from typing import Any
from typing import Dict
from typing import Generic
from typing import List
from typing import Optional
from typing import Tuple
from typing import Type
from typing import TypeVar

from pydantic import Field

from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.models.default_id import default_id

# ============================================================================
# COMPONENT EVENT BASE
# ============================================================================


class ComponentEvent(Event):
    """
    Base class for all component-related events (Node, Tool, Workflow, Assistant):
    the component's id, name and type.
    """

    id: str = default_id
    name: str
    type: str


# ============================================================================
# LIFECYCLE EVENT TYPES (Invoke, Respond, Failed)
# ============================================================================

T_Input = TypeVar("T_Input")
T_Output = TypeVar("T_Output")


class InvokeEvent(ComponentEvent, Generic[T_Input]):
    """Base class for all invoke events."""

    input_data: T_Input


class RespondEvent(ComponentEvent, Generic[T_Input, T_Output]):
    """Base class for all respond events."""

    input_data: T_Input
    output_data: T_Output


class FailedEvent(ComponentEvent, Generic[T_Input]):
    """Base class for all failed events: the error, as text, and its structured
    details when they were captured."""

    input_data: T_Input
    error: str
    error_details: Optional[Dict[str, Any]] = None


# ============================================================================
# SPECIALIZED COMPONENT BASES
# ============================================================================


class NodeEventBase(ComponentEvent):
    """Base for Node events with additional node-specific fields."""

    subscribed_topics: List[str] = Field(default_factory=list)
    publish_to_topics: List[str] = Field(default_factory=list)


class ToolEventBase(ComponentEvent):
    """Base for Tool events."""


class WorkflowEventBase(ComponentEvent):
    """Base for Workflow events."""


class AssistantEventBase(ComponentEvent):
    """Base for Assistant events with model info."""

    model: Optional[str] = None


# ============================================================================
# FACTORY FUNCTIONS FOR CREATING TYPED EVENTS
# ============================================================================


def create_component_events(
    base_class: Type[ComponentEvent],
    component_name: str,
    input_type: Any,  # A type, or a typing form such as List[...] or Optional[...].
    output_type: Any,
    module: str = __name__,
) -> Tuple[Type[InvokeEvent], Type[RespondEvent], Type[FailedEvent]]:
    """
    Factory to create a set of Invoke, Respond, and Failed events for a component.
    Each class fixes its ``event_type``, and belongs to ``module``, where it is
    defined.

    Returns:
        Tuple of (InvokeEvent, RespondEvent, FailedEvent) classes
    """

    def event_class(lifecycle: str, base: Type[ComponentEvent]) -> Any:
        event_type = EventType[f"{component_name.upper()}_{lifecycle}"]
        name = f"{event_type.value}Event"  # Such as NodeInvokeEvent.
        namespace = {
            "__annotations__": {"event_type": EventType},
            "__module__": module,
            "__qualname__": name,
            "event_type": event_type,
        }
        return type(name, (base, base_class), namespace)

    return (
        event_class("INVOKE", InvokeEvent[input_type]),
        event_class("RESPOND", RespondEvent[input_type, output_type]),
        event_class("FAILED", FailedEvent[input_type]),
    )
