import json
import os
from typing import Any
from typing import List

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.containers.container import container
from grafi.common.decorators.record_assistant_a_execution import (
    record_assistant_a_execution,
)
from grafi.common.decorators.record_assistant_execution import (
    record_assistant_execution,
)
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import agent_output_topic


class Assistant(AssistantBase):
    """
    An abstract base class for assistants that use language models to process input and generate responses.

    Attributes:
        name (str): The name of the assistant
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    @record_assistant_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        """
        Process the input data through the LLM workflow, make function calls, and return the generated response.
        Args:
            execution_context (ExecutionContext): Context containing execution information
            input_data (Messages): List of input messages to be processed

        Returns:
            Messages: List of generated response messages, sorted by timestamp

        Raises:
            ValueError: If the OpenAI API key is not provided and not found in environment variables
        """
        try:
            # Execute the workflow with the input data
            self.workflow.execute(execution_context, input_data)

            output: Messages = []

            consumed_events: List[ConsumeFromTopicEvent] = self._get_consumed_events()

            for event in consumed_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                output.extend(messages)

            # Sort the list of messages by the timestamp attribute
            sorted_outputs = sorted(output, key=lambda msg: msg.timestamp)

            return sorted_outputs
        finally:
            if consumed_events:
                for event in consumed_events:
                    container.event_store.record_event(event)

    @record_assistant_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        """
        Process the input data through the LLM workflow, make function calls, and return the generated response.
        Args:
            execution_context (ExecutionContext): Context containing execution information
            input_data (Messages): List of input messages to be processed

        Returns:
            Messages: List of generated response messages, sorted by timestamp

        Raises:
            ValueError: If the OpenAI API key is not provided and not found in environment variables
        """
        consumed_events: List[ConsumeFromTopicEvent] = []
        try:
            # Execute the workflow with the input data
            await self.workflow.a_execute(execution_context, input_data)

            output: Messages = []

            consumed_events = self._get_consumed_events()

            for event in consumed_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                output.extend(messages)

            # Sort the list of messages by the timestamp attribute
            sorted_outputs = sorted(output, key=lambda msg: msg.timestamp)

            return sorted_outputs
        finally:
            if consumed_events:
                for event in consumed_events:
                    container.event_store.record_event(event)

    def _get_consumed_events(self) -> List[ConsumeFromTopicEvent]:
        consumed_events: List[ConsumeFromTopicEvent] = []
        if human_request_topic.can_consume(self.name):
            events = human_request_topic.consume(self.name)
            for event in events:
                if isinstance(event, OutputTopicEvent):
                    consumed_event = ConsumeFromTopicEvent(
                        topic_name=event.topic_name,
                        consumer_name=self.name,
                        consumer_type=self.type,
                        execution_context=event.execution_context,
                        offset=event.offset,
                        data=event.data,
                    )
                    consumed_events.append(consumed_event)

        if agent_output_topic.can_consume(self.name):
            events = agent_output_topic.consume(self.name)
            for event in events:
                consumed_event = ConsumeFromTopicEvent(
                    topic_name=event.topic_name,
                    consumer_name=self.name,
                    consumer_type=self.type,
                    execution_context=event.execution_context,
                    offset=event.offset,
                    data=event.data,
                )
                consumed_events.append(consumed_event)

        return consumed_events

    def to_dict(self) -> dict[str, Any]:
        """Convert the workflow to a dictionary."""
        return self.workflow.to_dict()

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
