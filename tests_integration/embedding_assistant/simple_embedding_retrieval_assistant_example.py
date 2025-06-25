import os
import shutil
import uuid
from pathlib import Path
from typing import List
from typing import Mapping
from typing import Union

import chromadb
from chromadb import Collection
from llama_index.embeddings.openai import OpenAIEmbedding

from grafi.common.containers.container import container
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from tests_integration.embedding_assistant.simple_embedding_retrieval_assistant import (
    SimpleEmbeddingRetrievalAssistant,
)


api_key = os.getenv("OPENAI_API_KEY", "")

CURRENT_DIR = Path(__file__).parent
PERSIST_DIR = CURRENT_DIR / "storage"

Scalar = Union[str, int, float, bool]
Meta = Mapping[str, Scalar]

event_store = container.event_store

# Delete the PERSIST_DIR and all files in it
if os.path.exists(PERSIST_DIR):
    shutil.rmtree(PERSIST_DIR)
    print(f"Deleted {PERSIST_DIR} and all its contents")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def get_embedding_model() -> OpenAIEmbedding:
    return OpenAIEmbedding(api_key=api_key)


def create_collection(document_path: Path = CURRENT_DIR / "data") -> Collection:
    # Create a persistent client
    client = chromadb.PersistentClient(path=str(PERSIST_DIR))

    # Try to get or create the collection
    try:
        collection = client.get_collection("aws-ec2")
        print("Using existing collection: aws-ec2")
    except Exception as e:
        print(f"{e}")  # Not sure what error to expect here
        collection = client.create_collection("aws-ec2")
        print("Created new collection: aws-ec2")

        # Get embedding model
        embed_model = get_embedding_model()

        # Read files from document_path
        if document_path.exists() and document_path.is_dir():
            documents = []
            metadatas: List[Meta] = []
            ids = []

            for i, file_path in enumerate(document_path.glob("*.*")):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:  # Skip empty documents
                            documents.append(content)
                            metadatas.append({"source": str(file_path.name)})
                            ids.append(f"doc_{i}")
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")

            # Add documents to collection if there are any
            if documents:
                # Embed documents
                embeddings = [embed_model.get_text_embedding(doc) for doc in documents]

                # Add documents with embeddings to the collection
                collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                    embeddings=embeddings,
                )
                print(f"Added {len(documents)} documents to the collection")

    return collection


def test_simple_embedding_retrieval_tool() -> None:
    invoke_context = get_invoke_context()
    simple_rag_assistant = SimpleEmbeddingRetrievalAssistant(
        name="SimpleEmbeddingRetrievalAssistant",
        api_key=api_key,
        embedding_model=get_embedding_model(),
        collection=create_collection(),
    )

    result: Messages = simple_rag_assistant.invoke(
        invoke_context,
        [
            Message(
                role="user",
                content="What is a service provided by Amazon Web Services that offers on-demand, scalable computing capacity in the cloud.",
            )
        ],
    )

    assert "Amazon EC2" in str(result[0].content)
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 12


test_simple_embedding_retrieval_tool()
