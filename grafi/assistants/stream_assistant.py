from grafi.assistants.assistant import Assistant
from grafi.common.containers.container import container
from grafi.common.decorators.record_assistant_a_stream import record_assistant_a_stream
from grafi.common.events.topic_events.consume_from_stream_topic_event import (
    ConsumeFromStreamTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.stream_output_topic import agent_stream_output_topic


class StreamAssistant(Assistant):
    """
    An abstract assistant class that uses OpenAI's language model to process input and generate stream responses.

    """

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        raise ValueError(
            "This method is not supported for SimpleStreamAssistant. Use a_execute instead."
        )

    @record_assistant_a_stream
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        """
        Execute the assistant's workflow with the provided input data and return the generated response.

        This method retrieves messages from memory based on the execution context, constructs the
        workflow, processes the input data through the workflow, and returns the combined content
        of the generated messages.

        Args:
            execution_context (ExecutionContext): The context in which the assistant is executed.
            input_data (str): The input string to be processed by the language model.

        Returns:
            str: The combined content of the generated messages, sorted by timestamp.
        """
        try:
            # Execute the workflow with the input data
            await self.workflow.a_execute(execution_context, input_data)

            consumed_event: ConsumeFromStreamTopicEvent = (
                await self._get_stream_consumed_events()
            )

            output: MsgsAGen = consumed_event.data

            return output
        finally:
            if consumed_event:
                container.event_store.record_event(consumed_event)

    async def _get_stream_consumed_events(self) -> ConsumeFromStreamTopicEvent:

        if agent_stream_output_topic.can_consume(self.name):
            event = agent_stream_output_topic.consume(self.name)
            if event is None:
                raise ValueError(
                    f"Stream event not found for {self.name} in {agent_stream_output_topic.name}"
                )

            consumed_event = ConsumeFromStreamTopicEvent(
                topic_name=event.topic_name,
                consumer_name=self.name,
                consumer_type=self.type,
                execution_context=event.execution_context,
                offset=event.offset,
                data=event.data,
            )
            return consumed_event
