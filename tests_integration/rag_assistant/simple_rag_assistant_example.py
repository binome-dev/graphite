import asyncio
import os
import shutil
import uuid
from pathlib import Path

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests_integration.rag_assistant.simple_rag_assistant import SimpleRagAssistant


api_key = os.getenv("OPENAI_API_KEY", "")

event_store = container.event_store

try:
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core import StorageContext
    from llama_index.core import VectorStoreIndex
    from llama_index.core import load_index_from_storage
except ImportError:
    raise ImportError(
        "`llama_index` not installed. Please install using `pip install llama-index-core llama-index-readers-file llama-index-embeddings-openai llama-index-llms-openai`"
    )

CURRENT_DIR = Path(__file__).parent
PERSIST_DIR = CURRENT_DIR / "storage"


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def initialize_index(
    document_path: str = str(CURRENT_DIR / "data"),
) -> VectorStoreIndex:
    if not os.path.exists(PERSIST_DIR):
        documents = SimpleDirectoryReader(document_path).load_data()
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=str(PERSIST_DIR))
        return index
    else:
        storage_context = StorageContext.from_defaults(persist_dir=str(PERSIST_DIR))
        base_index = load_index_from_storage(storage_context)
        return base_index


async def test_rag_tool() -> None:
    index = initialize_index()
    invoke_context = get_invoke_context()
    simple_rag_assistant = SimpleRagAssistant(
        name="SimpleRagAssistant",
        index=index,
        api_key=api_key,
    )

    result = await async_func_wrapper(
        simple_rag_assistant.a_invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=[Message(role="user", content="What is AWS EC2?")],
            ),
            is_sequential=True,
        )
    )

    print(result)
    assert "EC2" in str(result[0].data[0].content)
    assert "computing" in str(result[0].data[0].content)
    print(len(await event_store.a_get_events()))
    assert len(await event_store.a_get_events()) == 12

    # Delete the PERSIST_DIR and all files in it
    if os.path.exists(PERSIST_DIR):
        shutil.rmtree(PERSIST_DIR)
        print(f"Deleted {PERSIST_DIR} and all its contents")


asyncio.run(test_rag_tool())
