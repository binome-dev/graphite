# Builder Pattern

The Builder Pattern is a core design pattern used throughout Graphite to provide a fluent, type-safe, and consistent way to construct complex objects such as Assistants, Tools, Nodes, Workflows, and Topics. This pattern enables clean, readable object creation with method chaining while ensuring proper validation and configuration.

## Overview

Graphite implements the Builder Pattern using a composition-based approach where builders are separate classes that construct target objects using kwargs. This design provides:

- **Fluent Interface**: Method chaining for readable configuration
- **Type Safety**: Compile-time type checking with proper return types
- **Separation of Concerns**: Builders are independent of the target classes
- **Validation**: Centralized validation logic in the `build()` method
- **Consistency**: Uniform construction pattern across all components

## Core Architecture

### BaseBuilder (Generic)

The foundation of all builders in Graphite is the `BaseBuilder` class:

```python
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class BaseBuilder(Generic[T]):
    """Generic builder that can build *any* Pydantic model."""

    kwargs: dict[str, Any] = {}
    _cls: type[T]

    def __init__(self, cls: type[T]) -> None:
        self._cls = cls
        self.kwargs = {}

    def build(self) -> T:
        """Return the fully configured product."""
        return self._cls(**self.kwargs)
```

**Key Design Principles**:

- **kwargs-based**: Builders accumulate configuration in a `kwargs` dictionary
- **Generic**: Single base class handles all Pydantic model types
- **Immutable Target**: Objects are constructed once with all parameters
- **Type Safety**: Generic type parameter ensures type safety

## Implementation Guide

### Creating a New Builder

When implementing the builder pattern for a new component, follow these steps:

#### 1. Define Your Component Class

First, create your Pydantic model without any builder methods:

```python
from typing import Optional
from pydantic import BaseModel, Field

class DatabaseConnection(BaseModel):
    """Database connection configuration."""

    host: str
    port: int = Field(default=5432)
    database: str
    username: str
    password: Optional[str] = Field(default=None)
    ssl_enabled: bool = Field(default=True)
    timeout: int = Field(default=30)
```

#### 2. Create the Builder Class

Create a separate builder class that extends the appropriate base builder, and do not override the `build()` methods if no advanced type checks. For post initialization checks or operations, use pydantic `model_post_init()` instead.

```python
from typing import Self, TypeVar, Optional

T_DB = TypeVar("T_DB", bound=DatabaseConnection)

class DatabaseConnectionBuilder(BaseBuilder[T_DB]):
    """Builder for DatabaseConnection instances."""

    def host(self, host: str) -> Self:
        self.kwargs["host"] = host
        return self

    def port(self, port: int) -> Self:
        self.kwargs["port"] = port
        return self

    def database(self, database: str) -> Self:
        self.kwargs["database"] = database
        return self

    def username(self, username: str) -> Self:
        self.kwargs["username"] = username
        return self

    def password(self, password: str) -> Self:
        self.kwargs["password"] = password
        return self

    def ssl_enabled(self, enabled: bool) -> Self:
        self.kwargs["ssl_enabled"] = enabled
        return self

    def timeout(self, timeout: int) -> Self:
        self.kwargs["timeout"] = timeout
        return self

```

#### 3. Add Builder class to its object class

```python
from typing import Optional
from pydantic import BaseModel, Field

class DatabaseConnection(BaseModel):
    """Database connection configuration."""

    host: str
    port: int = Field(default=5432)
    database: str
    username: str
    password: Optional[str] = Field(default=None)
    ssl_enabled: bool = Field(default=True)
    timeout: int = Field(default=30)

    @classmethod
    def builder(cls) -> "DatabaseConnectionBuilder":
        """Return a builder for DatabaseConnectionBuilder."""
        return DatabaseConnectionBuilder(cls)
```

#### 4. Usage Examples

Here's how to use the builder:

```python
# Basic usage
db_config = (DatabaseConnection.builder()
    .host("localhost")
    .database("myapp")
    .username("user")
    .password("secret")
    .build())

# With optional parameters
db_config = (DatabaseConnection.builder()
    .host("prod-db.example.com")
    .port(3306)
    .database("production")
    .username("app_user")
    .password("secure_password")
    .ssl_enabled(True)
    .timeout(60)
    .build())

# Error handling
try:
    db_config = (DatabaseConnection.builder()
        .host("localhost")
        # Missing required database and username
        .build())
except ValueError as e:
    print(f"Configuration error: {e}")
```

### Advanced Builder Patterns

#### Builder with Complex Validation

For components with complex validation rules:

```python
class EmailServerBuilder(BaseBuilder[EmailServer]):
    """Builder for EmailServer with complex validation."""

    def build(self) -> EmailServer:
        """Build with comprehensive validation."""
        # Required field validation
        required_fields = ["host", "port", "sender_email"]
        for field in required_fields:
            if field not in self.kwargs:
                raise ValueError(f"{field} is required")

        # Conditional validation
        if self.kwargs.get("use_tls", False) and self.kwargs.get("port") == 25:
            raise ValueError("TLS cannot be used with port 25")

        # Cross-field validation
        if self.kwargs.get("auth_required", False):
            if not self.kwargs.get("username") or not self.kwargs.get("password"):
                raise ValueError("username and password required when auth_required=True")

        # Format validation
        email = self.kwargs.get("sender_email", "")
        if "@" not in email:
            raise ValueError("sender_email must be a valid email address")

        return super().build()
```

## Best Practices

### 1. Separation of Concerns

**Do**: Keep builders separate from the target classes

```python
# Good - Builder is separate
class MyComponent(BaseModel):
    name: str
    value: int

class MyComponentBuilder(BaseBuilder[MyComponent]):
    def name(self, name: str) -> Self:
        self.kwargs["name"] = name
        return self
```

**Don't**: Mix builder methods into the target class

```python
# Bad - Builder methods in target class
class MyComponent(BaseModel):
    name: str
    value: int

    def with_name(self, name: str) -> Self:  # Don't do this
        self.name = name
        return self
```

### 2. Validation in build()

Perform validation in the `build()` method if have to, pydantic will validate the required fields.

```python
def build(self) -> MyComponent:
    """Build with validation."""
    # Validate required fields
    if "name" not in self.kwargs:
        raise ValueError("name is required")

    # Validate business rules
    if self.kwargs.get("value", 0) < 0:
        raise ValueError("value must be non-negative")

    return super().build()
```

### 3. Type Safety

Use proper type annotations and generics:

```python
T_MC = TypeVar("T_MC", bound=MyComponent)

class MyComponentBuilder(BaseBuilder[T_MC]):
    def name(self, name: str) -> Self:  # Returns Self for chaining
        self.kwargs["name"] = name
        return self
```

### 4. Error Messages

Provide clear, actionable error messages:

```python
def build(self) -> MyComponent:
    if "host" not in self.kwargs:
        raise ValueError("host is required. Use .host('hostname') to set it.")

    if self.kwargs.get("port", 0) <= 0:
        raise ValueError("port must be positive. Use .port(8080) to set a valid port.")
```

## Integration with Existing Components

When working with Graphite's existing components, use their provided builders:

```python
# Assistant construction
assistant = (MyAssistant.builder()
    .name("Customer Support")
    .type("support")
    .oi_span_type(OpenInferenceSpanKindValues.AGENT)
    .event_store(InMemoryEventStore())
    .build())

# Workflow construction
workflow = (EventDrivenWorkflow.builder()
    .name("Processing Pipeline")
    .node(preprocessing_node)
    .node(llm_node)
    .node(postprocessing_node)
    .build())

# Topic construction
topic = (Topic.builder()
    .name("user_input")
    .condition(lambda msgs: len(msgs) > 0)
    .build())
```

## Summary

The Builder Pattern in Graphite provides a consistent, type-safe way to construct complex objects through:

- **Separation**: Builders are independent classes, not mixed into target objects
- **Parameter-based Construction**: All configuration accumulates in a parameters dictionary
- **Generic Base**: Single `BaseBuilder` class handles all model types
- **Validation**: Centralized validation logic in the `build()` method
- **Type Safety**: Proper generics and type annotations throughout

This pattern enables readable, maintainable object construction while ensuring proper validation and configuration management across the entire framework.
