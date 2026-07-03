# embedding_assistant

Integration tests for a single-node RAG assistant that answers a query by retrieving AWS EC2 documents from a persistent ChromaDB vector store using OpenAI embeddings.

## Assistants

### `simple_embedding_retrieval_assistant.py` — `SimpleEmbeddingRetrievalAssistant`

Builds an `EventDrivenWorkflow` with one node that subscribes to the input topic, runs a `ChromadbRetrievalTool` (OpenAI embeddings + ChromaDB collection), and publishes the retrieved results to the output topic.

Topology:

```
(agent_input_topic) [input]
        |
        v
[EmbeddingRetrievalNode: ChromadbRetrievalTool]
        |
        v
(agent_output_topic) [output]
```

## Examples

- `simple_embedding_retrieval_assistant_example.py` — Builds/populates the `aws-ec2` ChromaDB collection from `data/`, invokes the assistant sequentially via `async_func_wrapper(..., is_sequential=True)` on an EC2 question, and asserts the result contains "Amazon EC2" and that exactly 12 events were recorded.
- `simple_embedding_retrieval_assistant_async_example.py` — Same setup but consumes the assistant's output as a streaming `async for` over `invoke(...)`, asserting each streamed output contains "Amazon EC2" and that exactly 12 events were recorded.

## Runner

- `run_embedding_assistant.py` — Discovers and runs every `*_example.py` in this directory as a subprocess (skipping `ollama`/`_local` tests unless `--no-pass-local`), then prints a passed/failed summary and exits non-zero on any failure.
