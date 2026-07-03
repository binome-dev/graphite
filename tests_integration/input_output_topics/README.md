# input_output_topics

Demonstrates content-based multi-input/multi-output topic routing, where a single input topic feeds a router node that fans messages out to different downstream LLM paths via `publish_to(..., when=predicate)`.

## Assistants

### `mimo_llm_assistant.py` — `MIMOLLMAssistant`

A Multiple-Input/Multiple-Output LLM assistant whose `InputRouterNode` content-routes one input topic to a greeting path and/or a question path using the serializable `ContainsKeyword` publisher-route predicate, then merges either branch's result through a shared merge node.

Topology:

```
                                   [input]
                                      |
                                      v
                            (agent_input_topic)
                                      |
                                      v
                        [InputRouterNode: FunctionTool]        (tool fn: forward_input)
                          /                          \
        --when=ContainsKeyword("hello")   --when=ContainsKeyword("question")
                        /                              \
                       v                                v
       (agent_greeting_input_topic)        (agent_question_input_topic)
                       |                                |
                       v                                v
       [OpenAIGreetingNode: OpenAITool]    [OpenAIQuestionNode: OpenAITool]
              |             |                     |             |
              v             v                     v             v
   (agent_greeting   (agent_greeting     (agent_greeting  (agent_question
    _output_topic)    _merge_topic)       _output_topic)   _merge_topic)
      [output]            |                  [output]           |
                          \                                    /
                           \                                  /
                            +--- OR-subscription (merge) ----+
                                          |
                                          v
                            [OpenAIMergeNode: OpenAITool]
                                          |
                                          v
                                (agent_output_topic)
                                     [output]
```

Notes:
- Both `OpenAIGreetingNode` and `OpenAIQuestionNode` publish their reply to the **same** terminal `agent_greeting_output_topic` (an `OutputTopic`), and each also fans out to its own merge topic.
- `OpenAIMergeNode` subscribes with a boolean OR expression (`agent_greeting_merge_topic` OR `agent_question_merge_topic`), so it fires when either branch produces a merge message, and publishes the combined reply to the terminal `agent_output_topic`.
- Topics are pure FIFO queues; all content gating lives on the router node's `publish_to(..., when=...)` routes, not on the topics themselves.

## Examples

- `mimo_llm_assistant_example.py` — Builds a `MIMOLLMAssistant` with greeting/question/merge system messages and runs three invokes against a fresh event store (`event_store.clear_events()`):
  - **Greeting input** (`"Hello there! How are you?"`): routes only through the greeting path; asserts output length `== 2` and cumulative event count `== 25`.
  - **Question input** (`"...What is machine learning?"`): routes only through the question path; asserts output length `== 2` and cumulative event count `== 50`.
  - **Mixed input** (`"Hello! I have a question about the UK traditional food."`, invoked with `is_sequential=True`): matches both `"hello"` and `"question"` keywords so the router fans out to both paths and the merge node fires; asserts output length `== 3` and cumulative event count `== 83`.

## Runner

- `run_input_output_topics.py` — Discovers and runs every `*_example.py` in this directory as a subprocess (skipping any `ollama`/`_local` scripts unless `--no-pass-local` is passed), prints a pass/fail summary, and exits non-zero on any failure.
