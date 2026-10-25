# Output Topics

Output topics are where a workflow's outputs are published: the workflow reads
them itself, and hands each publication to its caller. A node publishes to one
through its routes, like to any topic; nothing else publishes to it.

An output reaches the caller only once the step that published it is stored.
Streaming partial output, such as an LLM's tokens, does not go through topics:
a caller streaming the run gets it as deltas, which are never published (see
[Runtime](../runtime.md#streaming)).

## Overview

- **OutputTopic**: the workflow's final output, to the user.
- **InWorkflowOutputTopic**: a request for an answer, such as a human's
  approval, sent while the workflow runs; the answer comes back on the
  `InWorkflowInputTopic`s it is paired with (see
  [Input Topics](input_topics.md)).

Both are `Topic`s (see [Topic](topic.md)): a node publishes to them through its
routes, its manifest naming them, and a workflow saves them once, with its
manifest.

## OutputTopic

`grafi.topics.topic_impl.output_topic.OutputTopic`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The topic's name, such as `"agent_output_topic"` |
| `type` | `TopicType` | `TopicType.AGENT_OUTPUT_TOPIC_TYPE` |

A publication to it is a final output: the workflow yields it to its caller,
as a `ConsumeFromTopicEvent`, once its step is stored.

```python
from grafi.nodes.node import Node
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic

agent_input_topic = InputTopic(name="agent_input_topic")
agent_output_topic = OutputTopic(name="agent_output_topic")

answer_node = (
    Node.builder()
    .name("AnswerNode")
    .subscribe(agent_input_topic)
    .tool(answer_tool)
    .publish_to(agent_output_topic)
    .build()
)
```

## InWorkflowOutputTopic

`grafi.topics.topic_impl.in_workflow_output_topic.InWorkflowOutputTopic`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | The topic's name |
| `type` | `TopicType` | `TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE` |
| `paired_in_workflow_input_topic_names` | `List[str]` | The `InWorkflowInputTopic`s an answer to it is published to |

A publication to it is handed to the caller, as an `OutputTopic`'s is, and the
request waits there. The caller answers it by invoking the assistant again, for
the same `assistant_request_id`, with an input event citing the request it
answers in its `consumed_event_ids`: the workflow resumes the request from its
stored events, and publishes the answer to the paired input topics.

| Builder Method | Signature | Description |
|----------------|-----------|-------------|
| `paired_in_workflow_input_topic_name` | `(paired_in_workflow_input_topic_name: str) -> Self` | Pairs it with an `InWorkflowInputTopic`; call it once for each |

```python
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

human_request_topic = (
    InWorkflowOutputTopic.builder()
    .name("human_request_topic")
    .paired_in_workflow_input_topic_name("human_response_topic")
    .build()
)
human_response_topic = InWorkflowInputTopic(name="human_response_topic")
```

See [Input Topics](input_topics.md) for the paired input topic, and the
human-in-the-loop examples in `tests_integration/hith_assistant`.

## Best Practices

1. **One final output**: route a node's final answer to the `OutputTopic`, and
   its intermediate messages, such as tool calls, to other topics, with
   [route conditions](../node.md).
2. **Pair every request**: name each `InWorkflowInputTopic` an
   `InWorkflowOutputTopic`'s answer goes to, so the answer reaches the nodes
   waiting for it.
3. **Stream with deltas**: for live text, have the caller stream the run
   (`invoke(..., stream=True)`); publications are whole messages.
