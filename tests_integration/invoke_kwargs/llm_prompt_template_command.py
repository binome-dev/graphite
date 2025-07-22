from typing import List

from jinja2 import Template
from loguru import logger

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.tools.llms.llm_command import LLMCommand


class LLMPromptTemplateCommand(LLMCommand):
    def get_tool_input(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        """Prepare the input for the LLM command based on the node input and invoke context."""

        messages = super().get_tool_input(invoke_context, node_input)

        message = messages[-1] if messages else None

        if invoke_context.kwargs and "prompt_template" in invoke_context.kwargs:
            template_str = invoke_context.kwargs["prompt_template"]
            template: Template = Template(template_str)

            if message and message.content:
                # Render the Jinja template with the message content as input
                try:
                    rendered_prompt = template.render(input_text=message.content)

                    # Create a new message with the rendered template
                    new_message = Message(role="user", content=rendered_prompt)

                    logger.info(f"Rendered prompt template with input...")
                    return [new_message]
                except Exception as e:
                    logger.error(f"Error rendering template: {e}")
                    # Fallback to original message if template rendering fails
                    return messages

        return messages
