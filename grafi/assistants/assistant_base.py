from typing import Self
from typing import Type
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict

from grafi.common.containers.container import container
from grafi.common.event_stores.event_store import EventStore
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
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

    def _construct_workflow(self) -> "AssistantBase":
        """Construct the workflow for the assistant."""
        raise NotImplementedError("Subclasses must implement '_construct_workflow'.")

    def execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> Messages:
        """Execute the assistant's workflow with the provided input data."""
        raise NotImplementedError("Subclasses must implement 'execute'.")

    async def a_execute(
        self,
        execution_context: ExecutionContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """Execute the assistant's workflow with the provided input data asynchronously."""
        raise NotImplementedError("Subclasses must implement 'a_execute'.")


T_A = TypeVar("T_A", bound=AssistantBase)


class AssistantBaseBuilder(BaseBuilder[T_A]):
    """Inner builder class for Assistant construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self._obj.oi_span_type = oi_span_type
        return self

    def name(self, name: str) -> Self:
        self._obj.name = name
        return self

    def type(self, type_name: str) -> Self:
        self._obj.type = type_name
        return self

    def event_store(
        self, event_store_class: Type[EventStore], event_store: EventStore
    ) -> Self:
        container.register_event_store(event_store_class, event_store)
        return self

    def build(self) -> T_A:
        """Build the SimpleStreamAssistant instance."""
        self._obj._construct_workflow()
        return self._obj
