import json
import os
from typing import Any
from typing import AsyncGenerator
from typing import List

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.decorators.record_assistant_a_invoke import record_assistant_a_invoke
from grafi.common.decorators.record_assistant_invoke import record_assistant_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


class Assistant(AssistantBase):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    Attributes:
        name (str): The name of the assistant
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    @record_assistant_invoke
    def invoke(self, input_event: PublishToTopicEvent) -> List[ConsumeFromTopicEvent]:
        """
        Process the input data through the LLM workflow, make function calls, and return the generated response.
        Args:
            invoke_context (InvokeContext): Context containing invoke information
            input_data (Messages): List of input messages to be processed

        Returns:
            Messages: List of generated response messages, sorted by timestamp

        Raises:
            ValueError: If the OpenAI API key is not provided and not found in environment variables
        """

        # Invoke the workflow with the input data
        events = self.workflow.invoke(input_event)

        return events

    @record_assistant_a_invoke
    async def a_invoke(
        self, input_event: PublishToTopicEvent
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """
        Process the input data through the LLM workflow, make function calls, and return the generated response.
        Args:
            invoke_context (InvokeContext): Context containing invoke information
            input_data (Messages): List of input messages to be processed

        Returns:
            Messages: List of generated response messages, sorted by timestamp

        Raises:
            ValueError: If the OpenAI API key is not provided and not found in environment variables
        """

        # Invoke the workflow with the input data
        async for output in self.workflow.a_invoke(input_event):
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
