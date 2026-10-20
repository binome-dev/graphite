from typing import Any
from typing import AsyncGenerator
from typing import ClassVar
from typing import Optional
from typing import Self
from typing import TypeVar
from typing import Union

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.manifest import Component
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.runtime.deltas import Delta
from grafi.workflows.workflow import Workflow


class AssistantBase(Component):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    An assistant builds its workflow with ``_construct_workflow()``, unless it
    is given one, as when it is loaded from a manifest, which holds it. Fields
    an assistant only builds its workflow from are best ``Field(exclude=True)``:
    the saved workflow is what loads, and editing them in a manifest would
    change nothing.

    Attributes:
        name (str): The name of the assistant
        workflow (Workflow): The workflow the assistant runs.
    """

    manifest_kind: ClassVar[Optional[str]] = "Assistant"

    assistant_id: str = default_id
    name: str = Field(default="Assistant")
    type: str = Field(default="assistant")
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )

    workflow: Workflow = Field(default_factory=Workflow)

    def model_post_init(self, _context: Any) -> None:
        if "workflow" not in self.model_fields_set:
            self._construct_workflow()

    def _construct_workflow(self) -> "AssistantBase":
        """Construct the workflow for the assistant.

        Subclasses override this to build ``self.workflow`` and return ``self``.
        The base is a no-op for a bare assistant with a default workflow.
        """
        return self

    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Run the assistant on ``input_data``, yielding its outputs, and, if
        ``stream``, the deltas its tools emit as they emit them."""
        # ``yield`` makes this an async generator (matching the concrete
        # subclasses and Workflow.invoke), so callers can ``async for`` over it.
        yield None  # type: ignore
        raise NotImplementedError("Subclasses must implement 'invoke'.")

    def stop_workflow(self) -> None:
        """Stop every run in flight of this assistant's workflow, including
        other requests' runs; see ``EventDrivenWorkflow.stop()``."""
        if hasattr(self.workflow, "stop"):
            self.workflow.stop()
        else:
            # Fallback for workflows that don't support stop method
            logger.warning(
                f"Workflow {self.workflow.__class__.__name__} does not support stop method"
            )


T_A = TypeVar("T_A", bound=AssistantBase)


class AssistantBaseBuilder(BaseBuilder[T_A]):
    """Inner builder class for Assistant construction."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        """Set the OpenInference span type for observability.

        Args:
            oi_span_type: The span type for tracing (typically AGENT).

        Returns:
            Self for method chaining.
        """
        self.kwargs["oi_span_type"] = oi_span_type
        return self

    def name(self, name: str) -> Self:
        """Set the assistant's display name.

        Args:
            name: Human-readable identifier for the assistant.

        Returns:
            Self for method chaining.
        """
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        """Set the assistant's type identifier.

        Args:
            type_name: Type classification for the assistant.

        Returns:
            Self for method chaining.
        """
        self.kwargs["type"] = type_name
        return self
