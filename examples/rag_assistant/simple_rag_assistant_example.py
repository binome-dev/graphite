import os
import shutil
import uuid
from pathlib import Path

from simple_rag_assistant import SimpleRagAssistant

from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

api_key = os.getenv("OPENAI_API_KEY")

event_store = container.event_store

try:
    from llama_index.core import (
        SimpleDirectoryReader,
        StorageContext,
        VectorStoreIndex,
        load_index_from_storage,
    )
except ImportError:
    raise ImportError(
        "`llama_index` not installed. Please install using `pip install llama-index-core llama-index-readers-file llama-index-embeddings-openai llama-index-llms-openai`"
    )

CURRENT_DIR = Path(__file__).parent
PERSIST_DIR = CURRENT_DIR / "storage"


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def initialize_index(document_path: str = CURRENT_DIR / "data") -> VectorStoreIndex:
    if not os.path.exists(PERSIST_DIR):
        documents = SimpleDirectoryReader(document_path).load_data()
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=PERSIST_DIR)
    else:
        storage_context = StorageContext.from_defaults(persist_dir=PERSIST_DIR)
        index = load_index_from_storage(storage_context)
    return index


def test_rag_tool():
    index = initialize_index()
    execution_context = get_execution_context()
    simple_rag_assistant = (
        SimpleRagAssistant.Builder()
        .name("SimpleRagAssistant")
        .index(index)
        .api_key(api_key)
        .build()
    )

    result = simple_rag_assistant.execute(
        execution_context,
        input_data=[Message(role="user", content="What is AWS EC2?")],
    )

    print(result)
    assert "EC2" in result[0].content
    assert "computing" in result[0].content
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 11

    # Delete the PERSIST_DIR and all files in it
    if os.path.exists(PERSIST_DIR):
        shutil.rmtree(PERSIST_DIR)
        print(f"Deleted {PERSIST_DIR} and all its contents")


test_rag_tool()
