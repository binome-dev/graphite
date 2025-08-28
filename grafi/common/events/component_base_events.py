"""
Simplified event base classes with clear hierarchy.
Reduces code duplication and provides consistent patterns for all events.
"""

from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar
from abc import ABC, abstractmethod

from pydantic import Field

from grafi.common.events.event import Event, EventType
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext


# ============================================================================
# COMPONENT EVENT BASE
# ============================================================================


class ComponentEvent(Event, ABC):
    """
    Base class for all component-related events (Node, Tool, Workflow, Assistant).
    Provides common component event_context fields.
    """

    id: str = default_id
    name: str
    type: str

    def component_dict(self) -> Dict[str, Any]:
        """Get component event_context as dict."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "invoke_context": self.invoke_context.model_dump(),
        }

    def to_dict_base(self) -> Dict[str, Any]:
        """Base dict for component events."""
        return {
            **self.event_dict(),
            "event_context": self.component_dict(),
        }


# ============================================================================
# LIFECYCLE EVENT TYPES (Invoke, Respond, Failed)
# ============================================================================

T_Input = TypeVar("T_Input")
T_Output = TypeVar("T_Output")


class InvokeEvent(ComponentEvent, Generic[T_Input], ABC):
    """Base class for all invoke events."""

    input_data: T_Input

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.to_dict_base(),
            "data": {
                "input_data": self._serialize_input(self.input_data),
            },
        }

    @abstractmethod
    def _serialize_input(self, data: T_Input) -> Any:
        """Serialize input data to dict/json."""
        pass

    @classmethod
    @abstractmethod
    def _deserialize_input(cls, data: Any) -> T_Input:
        """Deserialize input data from dict/json."""
        pass


class RespondEvent(ComponentEvent, Generic[T_Input, T_Output], ABC):
    """Base class for all respond events."""

    input_data: T_Input
    output_data: T_Output

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.to_dict_base(),
            "data": {
                "input_data": self._serialize_input(self.input_data),
                "output_data": self._serialize_output(self.output_data),
            },
        }

    @abstractmethod
    def _serialize_input(self, data: T_Input) -> Any:
        """Serialize input data to dict/json."""
        pass

    @abstractmethod
    def _serialize_output(self, data: T_Output) -> Any:
        """Serialize output data to dict/json."""
        pass

    @classmethod
    @abstractmethod
    def _deserialize_input(cls, data: Any) -> T_Input:
        """Deserialize input data from dict/json."""
        pass

    @classmethod
    @abstractmethod
    def _deserialize_output(cls, data: Any) -> T_Output:
        """Deserialize output data from dict/json."""
        pass


class FailedEvent(ComponentEvent, Generic[T_Input], ABC):
    """Base class for all failed events."""

    input_data: T_Input
    error: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.to_dict_base(),
            "data": {
                "input_data": self._serialize_input(self.input_data),
                "error": str(self.error),
            },
        }

    @abstractmethod
    def _serialize_input(self, data: T_Input) -> Any:
        """Serialize input data to dict/json."""
        pass

    @classmethod
    @abstractmethod
    def _deserialize_input(cls, data: Any) -> T_Input:
        """Deserialize input data from dict/json."""
        pass


# ============================================================================
# SPECIALIZED COMPONENT BASES
# ============================================================================


class NodeEventBase(ComponentEvent):
    """Base for Node events with additional node-specific fields."""

    subscribed_topics: List[str] = Field(default_factory=list)
    publish_to_topics: List[str] = Field(default_factory=list)

    def component_dict(self) -> Dict[str, Any]:
        base = super().component_dict()
        base.update(
            {
                "subscribed_topics": self.subscribed_topics,
                "publish_to_topics": self.publish_to_topics,
            }
        )
        return base


class ToolEventBase(ComponentEvent):
    """Base for Tool events."""


class WorkflowEventBase(ComponentEvent):
    """Base for Workflow events."""


class AssistantEventBase(ComponentEvent):
    """Base for Assistant events with model info."""

    model: Optional[str] = None

    def component_dict(self) -> Dict[str, Any]:
        base = super().component_dict()
        if self.model:
            base["model"] = self.model
        return base


# ============================================================================
# FACTORY FUNCTIONS FOR CREATING TYPED EVENTS
# ============================================================================


def create_component_events(
    base_class: Type[ComponentEvent],
    component_name: str,
    input_type: Type,
    output_type: Type,
    serialize_input_fn: callable,
    serialize_output_fn: callable,
    deserialize_input_fn: callable,
    deserialize_output_fn: callable,
) -> Tuple[Type[InvokeEvent], Type[RespondEvent], Type[FailedEvent]]:
    """
    Factory to create a set of Invoke, Respond, and Failed events for a component.

    Returns:
        Tuple of (InvokeEvent, RespondEvent, FailedEvent) classes
    """

    class ComponentInvokeEvent(InvokeEvent[input_type], base_class):
        event_type: EventType = EventType[f"{component_name.upper()}_INVOKE"]

        def _serialize_input(self, data):
            return serialize_input_fn(data)

        @classmethod
        def _deserialize_input(cls, data):
            return deserialize_input_fn(data)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]):
            base_fields = cls.event_base(data)
            event_context = data["event_context"]
            return cls(
                **base_fields,
                invoke_context=InvokeContext.model_validate(
                    event_context["invoke_context"]
                ),
                id=event_context["id"],
                name=event_context["name"],
                type=event_context["type"],
                input_data=cls._deserialize_input(data["data"]["input_data"]),
                **{
                    k: v
                    for k, v in event_context.items()
                    if k
                    not in ["id", "name", "type", "invoke_context", "component_type"]
                },
            )

    class ComponentRespondEvent(RespondEvent[input_type, output_type], base_class):
        event_type: EventType = EventType[f"{component_name.upper()}_RESPOND"]

        def _serialize_input(self, data):
            return serialize_input_fn(data)

        def _serialize_output(self, data):
            return serialize_output_fn(data)

        @classmethod
        def _deserialize_input(cls, data):
            return deserialize_input_fn(data)

        @classmethod
        def _deserialize_output(cls, data):
            return deserialize_output_fn(data)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]):
            base_fields = cls.event_base(data)
            event_context = data["event_context"]
            return cls(
                **base_fields,
                invoke_context=InvokeContext.model_validate(
                    event_context["invoke_context"]
                ),
                id=event_context["id"],
                name=event_context["name"],
                type=event_context["type"],
                input_data=cls._deserialize_input(data["data"]["input_data"]),
                output_data=cls._deserialize_output(data["data"]["output_data"]),
                **{
                    k: v
                    for k, v in event_context.items()
                    if k
                    not in ["id", "name", "type", "invoke_context", "component_type"]
                },
            )

    class ComponentFailedEvent(FailedEvent[input_type], base_class):
        event_type: EventType = EventType[f"{component_name.upper()}_FAILED"]

        def _serialize_input(self, data):
            return serialize_input_fn(data)

        @classmethod
        def _deserialize_input(cls, data):
            return deserialize_input_fn(data)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]):
            base_fields = cls.event_base(data)
            event_context = data["event_context"]
            return cls(
                **base_fields,
                invoke_context=InvokeContext.model_validate(
                    event_context["invoke_context"]
                ),
                id=event_context["id"],
                name=event_context["name"],
                type=event_context["type"],
                input_data=cls._deserialize_input(data["data"]["input_data"]),
                error=data["data"]["error"],
                **{
                    k: v
                    for k, v in event_context.items()
                    if k
                    not in ["id", "name", "type", "invoke_context", "component_type"]
                },
            )

    return ComponentInvokeEvent, ComponentRespondEvent, ComponentFailedEvent
