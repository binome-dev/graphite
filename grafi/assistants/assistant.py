import json
import os
from typing import Any
from typing import AsyncGenerator
from typing import Literal
from typing import Union
from typing import overload

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_assistant_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.runtime.deltas import Delta
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class Assistant(AssistantBase):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    Attributes:
        name (str): The name of the assistant
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: Literal[False] = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]: ...

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]: ...

    @record_assistant_invoke
    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Run the assistant's workflow on ``input_data``, yielding its outputs
        as they are committed, and, if ``stream``, each :class:`Delta` its tools
        emit as they emit it, such as an LLM's tokens."""
        async with owned_iterator(
            self.workflow.invoke(input_data, is_sequential, stream=stream)
        ) as outputs:
            async for output in outputs:
                yield output

    def to_dict(self) -> dict[str, Any]:
        """Convert the workflow to a dictionary."""
        return {
            **super().to_dict(),
        }

    def generate_manifest(self, output_dir: str = ".") -> str:
        """
        Generate a manifest file for the assistant.

        Args:
            output_dir (str): Directory where the manifest file will be saved

        Returns:
            str: Path to the generated manifest file
        """
        manifest_seed = self.to_dict()

        # Add dependencies between node and topics
        manifest_dict = manifest_seed

        output_path = os.path.join(output_dir, f"{self.name}_manifest.json")
        with open(output_path, "w") as f:
            f.write(json.dumps(manifest_dict, indent=4))

        return output_path

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "Assistant":
        """
        Load an assistant from a manifest dictionary.

        Args:
            manifest_dict (dict[str, Any]): Dictionary containing the assistant manifest

        Returns:
            Assistant: The deserialized assistant instance

        Raises:
            NotImplementedError: Subclasses must implement this method
        """

        # Create a new instance
        instance = cls.model_construct()
        instance.name = data.get("name", "Assistant")
        instance.type = data.get("type", "assistant")
        instance.oi_span_type = OpenInferenceSpanKindValues(
            data.get("oi_span_type", "AGENT")
        )
        instance.workflow = await EventDrivenWorkflow.from_dict(
            data.get("workflow", {})
        )

        return instance
