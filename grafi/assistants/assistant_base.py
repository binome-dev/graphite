from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel, ConfigDict, Field

from grafi.common.containers.container import container, event_store
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

    workflow: Workflow = Field(default=None)

    class Builder:
        """Inner builder class for Assistant construction."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "AssistantBase":
            raise NotImplementedError

        def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues):
            self._assistant.oi_span_type = oi_span_type
            return self

        def name(self, name: str):
            self._assistant.name = name
            return self

        def type(self, type_name: str):
            self._assistant.type = type_name
            return self

        def event_store(self, event_store: EventStore):
            container.event_store = event_store
            return self

        def build(self) -> "AssistantBase":
            raise NotImplementedError

    @property
    def unfinished_requests(self) -> List[str]:
        """
        Return all unfinished requests by reading from the event store.

        Returns:
            List[str]: A list of assistant_request_id for unfinished requests.
        """
        return event_store.get_unfinished_requests(self.type, self.name)
