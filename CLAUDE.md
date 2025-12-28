# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Graphite (PyPI: `grafi`) is an event-driven framework for building AI agents using modular, composable workflows. The framework emphasizes observability, idempotency, auditability, and restorability for enterprise-grade AI applications.

## Development Commands

```bash
# Install dependencies
poetry install --with dev

# Run linting and formatting
ruff check .
ruff format .

# Run type checking
mypy .

# Run all tests
pytest

# Run a single test file
pytest tests/path/to/test_file.py

# Run a specific test
pytest tests/path/to/test_file.py::test_function_name

# Run tests with coverage
pytest --cov=grafi

# Pre-commit hooks
pre-commit install
pre-commit run --all-files
```

## Architecture

The framework has three conceptual layers coordinated through pub/sub workflow orchestration:

### Layer Hierarchy

1. **Assistants** (`grafi/assistants/`) - Top-level orchestration managing complete request lifecycles. Assistants own a Workflow and delegate execution to it.

2. **Workflows** (`grafi/workflows/`) - Orchestrate interactions among Nodes using pub/sub with in-memory FIFO message queuing. `EventDrivenWorkflow` is the primary implementation.

3. **Nodes** (`grafi/nodes/`) - Discrete workflow components that subscribe to Topics, execute Tools, and publish results. A Node wraps a Tool and handles event subscriptions/publishing.

4. **Tools** (`grafi/tools/`) - Core execution units that transform input to output. Categories:
   - `llms/` - LLM integrations (OpenAI, Claude, Gemini, Ollama, DeepSeek, OpenRouter)
   - `function_calls/` - External API tools (Tavily, DuckDuckGo, Google Search, MCP)
   - `functions/` - Custom function tools

### Event System

All components communicate through events stored in durable event stores (`grafi/common/event_stores/`):
- `EventStore` - Abstract base for event persistence
- `EventStoreInMemory` - In-memory implementation
- `EventStorePostgres` - PostgreSQL implementation for production

Events flow through Topics (`grafi/topics/`):
- `InputTopic` - Entry point for workflow input
- `OutputTopic` - Terminal point with output conditions
- `Topic` - General-purpose with optional conditions

### Builder Pattern

All major components use a builder pattern for construction:
```python
Node.builder().name("MyNode").tool(my_tool).subscribe(topic).publish_to(output_topic).build()
```

### Subscription Expressions

Nodes can subscribe to multiple topics with boolean logic:
```python
SubscriptionBuilder().subscribed_to(topicA).or_().subscribed_to(topicB).build()
```

## Code Style

- Line length: 88 characters
- Use double quotes for strings
- Type hints required for all functions
- Use `typing_extensions.TypedDict` instead of `typing.TypedDict`

## Key Patterns

### Creating an Agent

See `grafi/agents/react_agent.py` for the canonical example. Key steps:
1. Define Topics (input, output, intermediate)
2. Create Nodes with Tools, subscriptions, and publish targets
3. Compose Nodes into a Workflow
4. Wrap in an Assistant with `_construct_workflow()` method

### Event Recovery

Workflows can resume from interruption by replaying events from the event store. See `tests_integration/react_assistant/react_assistant_recovery_example.py` for implementation.

### InvokeContext

Tracks request lifecycles with:
- `conversation_id` - Groups multiple invokes in a conversation
- `assistant_request_id` - Tracks requests at assistant level
- `invoke_id` - Individual request identifier
- `user_id` - User identifier
