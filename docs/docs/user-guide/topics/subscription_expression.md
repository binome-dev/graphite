# Topic Subscription Expressions

The Graphite topic subscription expression system provides a Domain Specific Language (DSL) for creating complex subscription patterns. It allows components to subscribe to multiple topics using logical operators, enabling sophisticated message routing and consumption patterns.

## Overview

The subscription expression system enables:

- **Complex Subscriptions**: Subscribe to multiple topics with logical combinations
- **Expression Trees**: Build hierarchical subscription logic using AND/OR operations
- **Dynamic Evaluation**: Evaluate subscriptions against available messages
- **Topic Extraction**: Extract all referenced topics from complex expressions
- **Fluent API**: Build expressions using a chainable builder pattern

## Core Components

### Expression Types

#### SubExpr (Base Class)

Abstract base class for all subscription expressions.

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_dict` | `() -> dict[str, Any]` | Serialize expression to dictionary (abstract) |

#### TopicExpr

Represents a subscription to a single topic.

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `TopicBase` | The topic to subscribe to |

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_dict` | `() -> dict[str, Any]` | Serialize topic expression to dictionary |

#### CombinedExpr

Represents a logical combination of two expressions.

| Field | Type | Description |
|-------|------|-------------|
| `op` | `LogicalOp` | Logical operator (AND/OR) |
| `left` | `SubExpr` | Left expression operand |
| `right` | `SubExpr` | Right expression operand |

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_dict` | `() -> dict[str, Any]` | Serialize combined expression to dictionary |

### Logical Operators

#### LogicalOp Enum

Defines available logical operators for combining expressions.

| Value | Description |
|-------|-------------|
| `AND` | Both expressions must have new messages |
| `OR` | Either expression must have new messages |

### SubscriptionBuilder

Fluent API builder for constructing subscription expressions.

| Field | Type | Description |
|-------|------|-------------|
| `root_expr` | `Optional[SubExpr]` | Root expression being built |
| `pending_op` | `Optional[LogicalOp]` | Pending logical operator |

#### Builder Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `subscribed_to` | `(topic: TopicBase) -> SubscriptionBuilder` | Add topic to subscription |
| `and_` | `() -> SubscriptionBuilder` | Set AND operator for next topic |
| `or_` | `() -> SubscriptionBuilder` | Set OR operator for next topic |
| `build` | `() -> SubExpr` | Build final expression |

## Expression Evaluation

### Evaluation Function

The system provides a function to evaluate subscription expressions against available messages:

```python
def evaluate_subscription(expr: SubExpr, topics_with_new_msgs: List[str]) -> bool:
    """
    Evaluate the subscription expression given the list of topic names
    that have new (unread) messages.
    """
    if isinstance(expr, TopicExpr):
        return expr.topic.name in topics_with_new_msgs
    elif isinstance(expr, CombinedExpr):
        left_val = evaluate_subscription(expr.left, topics_with_new_msgs)
        right_val = evaluate_subscription(expr.right, topics_with_new_msgs)
        if expr.op == LogicalOp.AND:
            return left_val and right_val
        else:  # expr.op == LogicalOp.OR
            return left_val or right_val
    else:
        return False
```

### Evaluation Logic

- **TopicExpr**: Returns `True` if the topic name is in the list of topics with new messages
- **CombinedExpr with AND**: Returns `True` if both left and right expressions evaluate to `True`
- **CombinedExpr with OR**: Returns `True` if either left or right expression evaluates to `True`
- **Unknown Expression**: Returns `False` for safety

## Topic Extraction

### Extract Topics Function

Utility function to recursively extract all topics from an expression:

```python
def extract_topics(expr: SubExpr) -> List[TopicBase]:
    """Recursively collect topic names from a DSL expression tree."""
    if isinstance(expr, TopicExpr):
        return [expr.topic]
    elif isinstance(expr, CombinedExpr):
        return extract_topics(expr.left) + extract_topics(expr.right)
    return []
```

This function traverses the expression tree and collects all referenced topics, useful for:

- Setting up subscriptions
- Validating topic availability
- Dependency analysis

## Usage Examples

### Simple Topic Subscription

```python
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic

# Create topics
notifications = Topic(name="notifications")
alerts = Topic(name="alerts")

# Simple subscription to one topic
expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .build())
```

### AND Combination

```python
# Subscribe to both topics (both must have new messages)
expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .and_()
    .subscribed_to(alerts)
    .build())
```

### OR Combination

```python
# Subscribe to either topic (at least one must have new messages)
expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .or_()
    .subscribed_to(alerts)
    .build())
```

### Complex Expressions

```python
# Complex subscription: (notifications AND alerts) OR errors
errors = Topic(name="errors")

expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .and_()
    .subscribed_to(alerts)
    .or_()
    .subscribed_to(errors)
    .build())
```

### Multi-level Expressions

```python
# Create nested expressions manually for complex logic
# (notifications OR alerts) AND (errors OR warnings)
warnings = Topic(name="warnings")

# First sub-expression: notifications OR alerts
left_expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .or_()
    .subscribed_to(alerts)
    .build())

# Second sub-expression: errors OR warnings  
right_expr = (SubscriptionBuilder()
    .subscribed_to(errors)
    .or_()
    .subscribed_to(warnings)
    .build())

# Combine manually
from grafi.common.topics.topic_expression import CombinedExpr, LogicalOp
complex_expr = CombinedExpr(
    op=LogicalOp.AND,
    left=left_expr,
    right=right_expr
)
```

## Evaluation Examples

### Basic Evaluation

```python
from grafi.common.topics.topic_expression import evaluate_subscription

# Topics with new messages
topics_with_msgs = ["notifications", "errors"]

# Evaluate simple expression
simple_expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .build())

result = evaluate_subscription(simple_expr, topics_with_msgs)
# Returns True because "notifications" is in topics_with_msgs
```

### AND Evaluation

```python
# AND expression: both topics must have messages
and_expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .and_()
    .subscribed_to(alerts)
    .build())

# Only notifications has new messages
result = evaluate_subscription(and_expr, ["notifications"])
# Returns False because alerts doesn't have new messages

# Both have new messages
result = evaluate_subscription(and_expr, ["notifications", "alerts"])
# Returns True because both topics have new messages
```

### OR Evaluation

```python
# OR expression: either topic can have messages
or_expr = (SubscriptionBuilder()
    .subscribed_to(notifications)
    .or_()
    .subscribed_to(alerts)
    .build())

# Only notifications has new messages
result = evaluate_subscription(or_expr, ["notifications"])
# Returns True because at least one topic has new messages

# Neither has new messages
result = evaluate_subscription(or_expr, ["other_topic"])
# Returns False because neither topic has new messages
```

## Serialization

### Expression Serialization

All expressions can be serialized to dictionaries for persistence or transport:

```python
# Simple topic expression
topic_expr = TopicExpr(topic=notifications)
serialized = topic_expr.to_dict()
# Returns: {"topic": {"name": "notifications", "condition": {...}}}

# Combined expression
combined_expr = CombinedExpr(
    op=LogicalOp.AND,
    left=TopicExpr(topic=notifications),
    right=TopicExpr(topic=alerts)
)
serialized = combined_expr.to_dict()
# Returns: {
#   "op": "AND",
#   "left": {"topic": {"name": "notifications", ...}},
#   "right": {"topic": {"name": "alerts", ...}}
# }
```

## Error Handling

### Builder Validation

```python
def safe_subscription_build():
    """Example of proper error handling in subscription building."""
    try:
        builder = SubscriptionBuilder()

        # This will raise ValueError if topic is not TopicBase
        expr = builder.subscribed_to("invalid_topic").build()

    except ValueError as e:
        print(f"Invalid subscription: {e}")
        return None

    try:
        builder = SubscriptionBuilder()

        # This will raise ValueError - missing operator
        expr = (builder
            .subscribed_to(topic1)
            .subscribed_to(topic2)  # Missing .and_() or .or_()
            .build())

    except ValueError as e:
        print(f"Invalid subscription chain: {e}")
        return None
```

### Evaluation Safety

```python
def safe_evaluate(expr: SubExpr, topics_with_msgs: List[str]) -> bool:
    """Safely evaluate subscription with error handling."""
    try:
        return evaluate_subscription(expr, topics_with_msgs)
    except Exception as e:
        logger.error(f"Error evaluating subscription: {e}")
        return False
```

## Best Practices

### Subscription Design

1. **Keep It Simple**: Start with simple expressions and add complexity as needed
2. **Logical Grouping**: Group related topics with appropriate operators
3. **Performance Consideration**: Remember that AND operations are more restrictive
4. **Topic Dependencies**: Consider message flow and dependencies between topics

### Builder Usage

1. **Operator Placement**: Always place operators (`.and_()`, `.or_()`) between topics
2. **Error Handling**: Wrap builder operations in try-catch blocks
3. **Validation**: Validate topics exist before building subscriptions
4. **Reusability**: Extract common subscription patterns into helper functions

### Performance Optimization

1. **Topic Ordering**: Place frequently updated topics first in OR expressions
2. **Expression Structure**: Structure expressions to fail fast when possible
3. **Topic Extraction**: Cache extracted topics to avoid repeated extraction
4. **Evaluation Frequency**: Consider caching evaluation results for expensive expressions

### Testing Strategies

```python
def test_subscription_expression():
    """Test subscription expression building and evaluation."""
    # Create test topics
    topic1 = Topic(name="test1")
    topic2 = Topic(name="test2")

    # Test AND expression
    and_expr = (SubscriptionBuilder()
        .subscribed_to(topic1)
        .and_()
        .subscribed_to(topic2)
        .build())

    # Test with no messages
    assert not evaluate_subscription(and_expr, [])

    # Test with one message
    assert not evaluate_subscription(and_expr, ["test1"])

    # Test with both messages
    assert evaluate_subscription(and_expr, ["test1", "test2"])

    # Test OR expression
    or_expr = (SubscriptionBuilder()
        .subscribed_to(topic1)
        .or_()
        .subscribed_to(topic2)
        .build())

    # Test with one message
    assert evaluate_subscription(or_expr, ["test1"])
    assert evaluate_subscription(or_expr, ["test2"])
```

The topic subscription expression system provides a powerful and flexible way to define complex message consumption patterns in Graphite applications, enabling sophisticated event-driven architectures with precise control over when components should process messages.
