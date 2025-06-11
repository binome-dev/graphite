# Builder Pattern

The Builder Pattern is a core design pattern used throughout Graphite to provide a fluent, type-safe, and consistent way to construct complex objects such as Assistants, Tools, Nodes, Workflows, and Topics. This pattern enables clean, readable object creation with method chaining while ensuring proper validation and configuration.

## Overview

Graphite implements the Builder Pattern using a nested class approach where each main component has an associated `Builder` class. This design provides:

- **Fluent Interface**: Method chaining for readable configuration
- **Type Safety**: Compile-time type checking with proper return types
- **Immutability**: Objects are constructed once and remain immutable
- **Validation**: Centralized validation logic in the `build()` method
- **Consistency**: Uniform construction pattern across all components

## Core Architecture

### Base Builder Classes

Graphite provides base builder classes that establish the foundation for all component builders:

#### BaseBuilder (Generic)

The generic `BaseBuilder` class provides the fundamental building blocks:

```python
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class BaseBuilder(Generic[T]):
    """Generic builder that can build *any* Pydantic model."""

    _obj: T

    def __init__(self, cls: type[T]) -> None:
        self._obj = cls.model_construct()

    def build(self) -> T:
        """Return the fully configured product."""
        return self._obj
```

#### Component-Specific Base Builders

Each major component category has its own base builder:

- **AssistantBaseBuilder**: For all Assistant types
- **ToolBuilder**: For all Tool implementations
- **NodeBuilder**: For all Node types
- **WorkflowBuilder**: For all Workflow types
- **TopicBaseBuilder**: For all Topic implementations

### Builder Implementation Pattern

All builders in Graphite follow this consistent structure:

```python
class ComponentName(ComponentParent):
    # Component fields...

    @classmethod
    def builder(cls) -> "ComponentNameBuilder":  # Return the Builder class.
        """Method to create a new builder instance."""
        return ComponentNameBuilder(cls)

    # Component methods

# Add type if this will be inherited by other classes.
T_C = TypeVar("T_C", bound=ComponentName)

# Builder
class ComponentNameBuilder(ParentBuilder[ComponentName]):
    """ Builder class for component construction."""

    def property_name(self, value: PropertyType) -> Self:
        """Set a property and return self for chaining."""
        self._obj.property_name = value
        return self

    def build(self) -> "ComponentName":
        """Build and return the final component."""
        # Perform any necessary post-construction setup
        return self._obj
```

## Builder Hierarchy

### Assistant Builders

All Assistant classes inherit from `AssistantBaseBuilder` and provide assistant-specific configuration:

```python
class AssistantBaseBuilder(BaseBuilder[T_A]):
    """Base builder for all Assistant types."""

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self._obj.oi_span_type = oi_span_type
        return self

    def name(self, name: str) -> Self:
        self._obj.name = name
        return self

    def type(self, type_name: str) -> Self:
        self._obj.type = type_name
        return self

    def event_store(self, event_store_class: Type[EventStore], event_store: EventStore) -> Self:
        container.register_event_store(event_store_class, event_store)
        return self

    def build(self) -> T_A:
        """Build the Assistant instance."""
        self._obj._construct_workflow()
        return self._obj
```

### Tool Builders

Tool builders provide configuration for various tool types:

```python
class ToolBuilder(BaseBuilder[T_T]):
    """Base builder for all Tool types."""

    def name(self, name: str) -> Self:
        self._obj.name = name
        return self

    def type(self, type_name: str) -> Self:
        self._obj.type = type_name
        return self

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        self._obj.oi_span_type = oi_span_type
        return self
```

### Node Builders

Node builders handle the complex configuration of workflow nodes including subscriptions and publishing:

```python
class NodeBuilder(BaseBuilder[T_N]):
    """Base builder for all Node types."""

    def name(self, name: str) -> Self:
        self._obj.name = name
        return self

    def command(self, command: Command) -> Self:
        self._obj.command = command
        return self

    def subscribe(self, subscribe_to: Union[TopicBase, SubExpr]) -> Self:
        """Configure topic subscriptions."""
        if isinstance(subscribe_to, TopicBase):
            self._obj.subscribed_expressions.append(TopicExpr(topic=subscribe_to))
        elif isinstance(subscribe_to, SubExpr):
            self._obj.subscribed_expressions.append(subscribe_to)
        return self

    def publish_to(self, topic: TopicBase) -> Self:
        self._obj.publish_to.append(topic)
        return self

    def build(self) -> T_N:
        # Extract topics from subscription expressions
        topics = {
            topic.name: topic
            for expr in self._obj.subscribed_expressions
            for topic in extract_topics(expr)
        }
        self._obj._subscribed_topics = topics
        return self._obj
```

## Development Guide

### Adding Builder Pattern to New Components

When creating new components that should support the builder pattern, follow these steps:

#### 1. Define the Component Class

```python
from typing import Self
from pydantic import BaseModel, Field

class MyComponent(BaseModel):
    """Your component description."""

    name: str
    property_a: str = Field(default="default_value")
    property_b: Optional[int] = Field(default=None)

    @classmethod
    def builder(cls) -> "MyComponentBuilder":
        """Factory method to create builder."""
        return MyComponentBuilder(cls)
```

#### 2. Choose the Appropriate Parent Builder

Select the correct parent builder based on your component type:

- **AssistantBaseBuilder**: For assistant implementations
- **ToolBuilder**: For tool implementations  
- **NodeBuilder**: For node implementations
- **WorkflowBuilder**: For workflow implementations
- **BaseBuilder**: For generic components

#### 3. Implement the Builder Class

```python
# Add type if this will be inherited by other classes.
T_M = TypeVar("T_M", bound=MyComponent)

class MyComponentBuilder(ParentBuilder[T_M]):  # Choose appropriate parent
    """Builder for MyComponent."""

    def property_a(self, value: str) -> Self:
        """Set property_a."""
        self._obj.property_a = value
        return self

    def property_b(self, value: int) -> Self:
        """Set property_b."""
        self._obj.property_b = value
        return self

    def build(self) -> "MyComponent":
        """Build the component with validation."""
        # Add any custom validation or setup logic here
        if not self._obj.name:
            raise ValueError("name is required")

        # Perform any necessary post-construction setup
        self._obj._setup()

        return self._obj
```

#### 5. Add Validation Logic

Implement validation in the `build()` method:

```python
def build(self) -> "MyComponent":
    """Build with comprehensive validation."""

    # Required field validation
    if not self._obj.name:
        raise ValueError("name is required")

    # Business logic validation
    if self._obj.property_b and self._obj.property_b < 0:
        raise ValueError("property_b must be non-negative")

    # Cross-field validation
    if self._obj.property_a == "special" and not self._obj.property_b:
        raise ValueError("property_b required when property_a is 'special'")

    # Post-construction setup
    self._obj._initialize()

    return self._obj
```

## Summary

The Builder Pattern in Graphite provides a consistent, type-safe, and fluent way to construct complex objects. By following the established patterns and best practices outlined in this guide, you can:

- Create readable, maintainable object construction code
- Ensure proper validation and error handling
- Maintain consistency across the codebase
- Provide excellent developer experience with IDE support and type safety

The pattern is extensively used throughout Graphite for Assistants, Tools, Nodes, Workflows, and Topics, making it essential to understand and follow when extending the framework.
