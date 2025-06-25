# We will test the SimpleLLMAssistant class in this file.

import base64
import os
import uuid
from pathlib import Path

from grafi.common.containers.container import container
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.multimodal_assistant.simple_llm_assistant import (
    SimpleLLMAssistant,
)


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def load_image_as_base64(image_path: Path) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# Load the image from the same directory
image_path = Path(__file__).parent / "graphite_powered_by_binome.png"
graphite_image_base64 = load_image_as_base64(image_path)


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_image_llm_assistant() -> None:
    invoke_context = get_invoke_context()
    assistant = (
        SimpleLLMAssistant.builder()
        .name("SimpleLLMImageAssistant")
        .api_key(api_key)
        .build()
    )
    event_store.clear_events()

    input_data = [
        Message(
            content=[
                {"type": "text", "text": "what's in this image?"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{graphite_image_base64}",
                    },
                },
            ],
            role="user",
        )
    ]
    output = assistant.invoke(invoke_context, input_data)

    print(output)
    assert output is not None
    assert "GRAPHITE" in str(output[0].content)
    assert len(event_store.get_events()) == 12


test_simple_image_llm_assistant()
