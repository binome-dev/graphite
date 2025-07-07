from typing import Any
from typing import Self
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict

from grafi.common.containers.container import container
from grafi.common.event_stores.event_store import EventStore
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
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
    name: str = "Assistant"
    type: str = "assistant"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.AGENT

    workflow: Workflow = Workflow()

    def model_post_init(self, _context: Any) -> None:
        self._construct_workflow()

    def _construct_workflow(self) -> "AssistantBase":
        """Construct the workflow for the assistant."""
        raise NotImplementedError("Subclasses must implement '_construct_workflow'.")

    def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        """Invoke the assistant's workflow with the provided input data."""
        raise NotImplementedError("Subclasses must implement 'invoke'.")

    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """Invoke the assistant's workflow with the provided input data asynchronously."""
        raise NotImplementedError("Subclasses must implement 'a_invoke'.")

    def to_dict(self) -> dict[str, Any]:
        """Convert the assistant to a dictionary representation."""
        return {
            "assistant_id": self.assistant_id,
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "workflow": self.workflow.to_dict(),
        }


T_A = TypeVar("T_A", bound=AssistantBase)


class AssistantBaseBuilder(BaseBuilder[T_A]):
    """Inner builder class for Assistant construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        self.kwargs["type"] = type_name
        return self

    def event_store(self, event_store: EventStore) -> Self:
        container.register_event_store(event_store)
        return self
