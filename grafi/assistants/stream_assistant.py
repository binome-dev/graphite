from typing import AsyncGenerator, List

from grafi.assistants.assistant import Assistant
from grafi.common.containers.container import event_store
from grafi.common.decorators.record_assistant_a_stream import record_assistant_a_stream
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


class StreamAssistant(Assistant):
    """
    An abstract assistant class that uses OpenAI's language model to process input and generate stream responses.

    """

    def execute(self, execution_context, input_data):
        raise ValueError(
            "This method is not supported for SimpleStreamAssistant. Use a_execute instead."
        )

    @record_assistant_a_stream
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: List[Message]
    ) -> AsyncGenerator[Message, None]:
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

            consumed_event: List[ConsumeFromTopicEvent] = self._get_consumed_events()

            output: AsyncGenerator[Message, None] = None
            if len(consumed_event) > 0:
                output = consumed_event[0].data

            return output
        finally:
            if consumed_event:
                event_store.record_events(consumed_event)
