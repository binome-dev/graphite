from typing import Self
from typing import Type
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict

from grafi.common.containers.container import container
from grafi.common.event_stores.event_store import EventStore
from grafi.common.models.default_id import default_id
from grafi.workflows.workflow import Workflow


class AssistantBase(BaseModel):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    Attributes:
        name (str): The name of the assistant
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    assistant_id: str = default_id
    name: str
    type: str
    oi_span_type: OpenInferenceSpanKindValues

    workflow: Workflow

    class Builder:
        """Inner builder class for Assistant construction."""

        _assistant: "AssistantBase"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "AssistantBase":
            return AssistantBase.model_construct()

        def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
            self._assistant.oi_span_type = oi_span_type
            return self

        def name(self, name: str) -> Self:
            self._assistant.name = name
            return self

        def type(self, type_name: str) -> Self:
            self._assistant.type = type_name
            return self

        def event_store(
            self, event_store_class: Type[EventStore], event_store: EventStore
        ) -> Self:
            container.register_event_store(event_store_class, event_store)
            return self

        def build(self) -> "AssistantBase":
            raise NotImplementedError


A = TypeVar("A", bound="AssistantBase")  # the AssistantBase subclass
