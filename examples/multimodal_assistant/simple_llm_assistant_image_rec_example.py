# We will test the SimpleLLMAssistant class in this file.

import base64
import os
import uuid
from pathlib import Path

from examples.multimodal_assistant.simple_llm_assistant import SimpleLLMAssistant
from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def load_image_as_base64(image_path: Path) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# Load the image from the same directory
image_path = Path(__file__).parent / "graphite_powered_by_binome.png"
graphite_image_base64 = load_image_as_base64(image_path)


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_image_llm_assistant() -> None:
    execution_context = get_execution_context()
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
    output = assistant.execute(execution_context, input_data)

    print(output)
    assert output is not None
    assert "GRAPHITE" in str(output[0].content)
    assert len(event_store.get_events()) == 12


test_simple_image_llm_assistant()
