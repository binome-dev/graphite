# We will test the SimpleLLMAssistant class in this file.

import os
import uuid

import markdown

from grafi.common.containers.container import container
from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import setup_tracing
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.invoke_kwargs.simple_llm_prompt_template_assistant import (
    SimpleLLMPromptTemplateAssistant,
)


container.register_tracer(setup_tracing(tracing_options=TracingOptions.IN_MEMORY))
event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:

    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
        kwargs={
            "prompt_template": """You are a skilled poet and literary analyst. Your task is to analyze the given input and create a 14-line sonnet based on your analysis.

## Input Analysis Instructions:
1. Carefully read and understand the provided input
2. Identify the main themes, emotions, imagery, and key concepts
3. Determine the appropriate tone and mood for the sonnet
4. Consider metaphors, symbolism, or literary devices that would enhance the poem

## Sonnet Requirements:
- Must be exactly 14 lines
- Follow traditional sonnet structure (Shakespearean or Petrarchan)
- Use appropriate rhyme scheme (ABAB CDCD EFEF GG for Shakespearean, or ABBAABBA CDECDE/CDCDCD for Petrarchan)
- Maintain consistent meter (preferably iambic pentameter)
- Include a clear thematic development with a turn (volta)
- End with a powerful concluding couplet or tercet

## Input to Analyze:
{{ input_text }}

## Analysis:
Please first provide a brief analysis of the input, identifying:
- Central themes: 
- Emotional tone: 
- Key imagery: 
- Poetic approach: 

## Generated Sonnet:
Based on your analysis, create a 14-line sonnet that captures the essence of the input:

```
[Your 14-line sonnet here]
```

## Explanation:
Briefly explain how your sonnet reflects the input and the literary devices used."""
        },
    )


def test_simple_llm_assistant() -> None:
    invoke_context = get_invoke_context()
    assistant = (
        SimpleLLMPromptTemplateAssistant.builder()
        .name("SimpleLLMPromptTemplateAssistant")
        .build()
    )
    event_store.clear_events()

    input_data = [
        Message(
            content="Graphite is a event driven agentic AI platform, it offers real time observability, comprehensive auditing, and high performance workflow.",
            role="user",
        )
    ]
    output = assistant.invoke(invoke_context, input_data)

    html = markdown.markdown(output[0].content)
    print(html)
    assert output is not None
    assert len(event_store.get_events()) == 12


test_simple_llm_assistant()
