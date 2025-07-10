# CLAUDE.md - LLM Guidance for Graphite Repository

## Repository Overview
This is **Graphite** (published as `grafi` on PyPI) - an event-driven framework for building AI agents using modular, composable workflows. The framework emphasizes observability, idempotency, auditability, and restorability for enterprise-grade AI applications.

## Development Commands

### Setup
```bash
# Install dependencies
poetry install

# Install with development dependencies
poetry install --with dev
```

### Code Quality
```bash
# Run linting
ruff check .

# Run type checking
mypy .

# Run formatting
ruff format .

# Run tests
pytest

# Run tests with coverage
pytest --cov=grafi
```

### Pre-commit
```bash
# Install pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files
```

## Architecture Overview

### Core Components
- **Assistants**: High-level orchestration layer managing AI agent workflows
- **Nodes**: Discrete workflow components with event subscriptions
- **Tools**: Functions that transform input data to output
- **Workflow**: Pub/sub orchestration with in-memory queuing

### Key Patterns
- **Event-driven Architecture**: All components communicate through events
- **Event Sourcing**: Events stored in durable event store as single source of truth
- **Command Pattern**: Clear separation between request initiators and executors
- **Pub/Sub**: Lightweight FIFO message queuing for component interactions

## Important File Locations

### Core Framework
- `grafi/` - Main framework code
- `grafi/agents/` - Built-in agents (ReAct, etc.)
- `grafi/events/` - Event sourcing implementation
- `grafi/workflows/` - Workflow orchestration
- `grafi/tools/` - Built-in tools and utilities

### Tests
- `tests/` - Unit tests
- `tests_integration/` - Integration tests
- `tests_integration/react_assistant/` - ReAct agent examples

### Documentation
- `docs/` - Documentation source
- `README.md` - Main documentation
- `pyproject.toml` - Project configuration

## Development Guidelines

### Code Style
- Follow PEP 8 with 88 character line limit
- Use type hints for all functions
- Use double quotes for strings
- Format with `ruff format`

### Event-Driven Patterns
- All state changes should emit events
- Use event decorators for automatic capture
- Maintain event ordering and idempotency
- Store events in durable event store

### Testing
- Write unit tests for all new functionality
- Include integration tests for workflows
- Test event sourcing and recovery scenarios
- Mock external dependencies appropriately

## Common Tasks

### Creating New Agents
1. Extend base agent classes in `grafi/assistants/`
2. implement designed workflow with node and tools
3. Define tool integrations
4. Add comprehensive tests

### Adding New Tools
1. Create tool in `grafi/tools/`
2. Every subfolder has a definition of a tool, check if tools matches to the correct category
2. Implement tool interface
3. Add event capturing decorators
4. Include usage examples

### Workflow Development
1. Define workflow nodes and connections
2. Set up pub/sub topics
3. Build Nodes that execute Tools
4. Test recovery scenarios

## Dependencies
- **Core**: pydantic, openai, loguru, jsonpickle
- **Observability**: arize-otel, openinference-instrumentation-openai
- **Dev**: pytest, ruff, mypy, pre-commit
- **Optional**: chromadb, llama-index, tavily-python, anthropic

## Best Practices

### Event Design
- Events should be immutable
- Include all necessary context
- Use consistent event schemas
- Consider event versioning

### Error Handling
- Implement proper error recovery
- Use event sourcing for state restoration
- Log errors with context
- Provide meaningful error messages

### Performance
- Use async/await patterns where appropriate
- Implement proper resource cleanup
- Consider memory usage with large event stores
- Profile critical paths

## Security Considerations
- Validate all inputs
- Sanitize event data
- Implement proper authentication
- Audit sensitive operations

## Getting Help
- Check existing tests for usage patterns
- Review integration examples
- Consult framework documentation
- Look at built-in agent implementations