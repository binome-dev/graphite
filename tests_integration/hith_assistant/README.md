# hith_assistant

Human-in-the-loop (HITL) assistants that pause mid-workflow by publishing to an in-workflow output topic and resume when the human's reply arrives on the paired in-workflow input topic.

## Assistants

### `human_tool_approval_assistant.py` — `HumanApprovalAssistant`

An OpenAI assistant that surfaces every proposed tool call (with a generated justification) for human approval before the function node runs it; on approval the tool executes, on denial the reply is fed back to the LLM.

Topology:

```
(agent_input_topic) [input] ---------------------+
                                                  |
(human_tool_call_response_topic) -----------------+--> [OpenAIInputNode: OpenAITool]
                                                         |  pre_tool_hook = ToolCallReasonHook
                                                         |  (justifies each tool call)
                                                         |
       --when=has_tool_call-----> (human_tool_call_request_topic) [in-workflow output]
       --when=has_no_tool_call--> (agent_output_topic) [output]

(human_tool_call_request_topic) [in-workflow output]  ==paired==>  (human_response_topic) [in-workflow input]
   (proposed tool call + reason, surfaced to human)                (human's approve/deny verdict)

(human_response_topic) [in-workflow input] --> [FunctionCallNode: FunctionCallTool]
                                                  |  ConsumerRouter(pre_hitl_input = human_response_topic)
                                                  |  approve -> run tool | deny -> forward reply
                                                  --> (human_tool_call_response_topic)
                                                        (loops back to [OpenAIInputNode])
```

Notes: 2-node workflow built from `HookedNode`. `OpenAIInputNode` subscribes to `agent_input_topic OR human_tool_call_response_topic`. The `human_tool_call_request_topic` (`InWorkflowOutputTopic`) is paired to `human_response_topic` (`InWorkflowInputTopic`) via `paired_in_workflow_input_topic_names`.

### `kyc_assistant.py` — `KycAssistant`

A five-node KYC onboarding assistant: it validates that the user supplied a full name and email, asks the human for anything missing via a HITL request, then registers the client and summarizes the result.

Topology:

```
(agent_input_topic) [input] --------------------+
                                                 |
(human_response_topic) [in-workflow input] ------+--> [ThoughtNode: OpenAITool]
                                                         --> (user_info_extract_topic)
                                                                    |
                                                                    v
                                                          [ActionNode: OpenAITool]
                                                            |                       |
                    --when=needs_human_review--> (hitl_call_topic)                  |
                                                            |                       |
                                                            v                       |
                                          [HumanRequestNode: FunctionCallTool]      |
                                                            |                       |
                                                            v                       |
                                 (human_request_topic) [in-workflow output]         |
                                                                                    |
             --when=is_register_client--> (register_user_topic) <------------------ +
                                                            |
                                                            v
                                        [FunctionCallRegisterNode: FunctionCallTool]
                                                            |
                                                            v
                                                (register_user_respond)
                                                            |
                                                            v
                                          [LLMResponseToUserNode: OpenAITool]
                                                            |
                                                            v
                                                (agent_output_topic) [output]

(human_request_topic) [in-workflow output]  ==paired==>  (human_response_topic) [in-workflow input]
   (question asked of the human)                          (human's answer; re-enters ThoughtNode)
```

Notes: `ThoughtNode` subscribes to `agent_input_topic OR human_response_topic`, so the human's reply loops back to re-validation. `human_request_topic` (`InWorkflowOutputTopic`) is paired to `human_response_topic` (`InWorkflowInputTopic`). Routing predicates `needs_human_review` / `is_register_client` are defined in this file (any pending tool call that is not `register_client` needs review).

### `simple_hitl_assistant.py` — `SimpleHITLAssistant`

A three-node assistant that, when the LLM emits a tool call, runs a HITL request function and pauses for the human; when there is no tool call it routes straight to a summarizing output LLM.

Topology:

```
(agent_input_topic) [input] --------------------+
                                                 |
(human_response_topic) [in-workflow input] ------+--> [OpenAIInputNode: OpenAITool]
                                                         |                        |
                     --when=has_tool_call--> (hitl_call_topic)                    |
                                                         |                        |
                                                         v                        |
                                       [FunctionCallNode: FunctionCallTool]        |
                                                         |                        |
                                                         v                        |
                                (human_request_topic) [in-workflow output]        |
                                                                                  |
              --when=has_no_tool_call--> (register_user_topic) <----------------- +
                                                         |
                                                         v
                                        [OpenAIOutputNode: OpenAITool]
                                                         |
                                                         v
                                             (agent_output_topic) [output]

(human_request_topic) [in-workflow output]  ==paired==>  (human_response_topic) [in-workflow input]
   (information request shown to human)                   (human's reply; re-enters OpenAIInputNode)
```

Notes: `OpenAIInputNode` subscribes to `agent_input_topic OR human_response_topic`. `human_request_topic` (`InWorkflowOutputTopic`) is paired to `human_response_topic` (`InWorkflowInputTopic`).

## Examples

- `human_tool_approval_assistant_example.py` — Exercises the approve-vs-deny HITL flow for `HumanApprovalAssistant` with a `DeleteDatabase` tool. First invoke returns a pending tool call (workflow paused at the human request); `test_function_call_assistant` resumes with "YES" and asserts the tool ran (final output has no tool_calls), while `test_function_call_assistant_disapproval` resumes with "NO" and asserts the LLM answered without running the tool. Two further tests (a "NO, add staging. prefix" suggestion loop that re-proposes the call with modified args, and a system-message memory variant) are defined but commented out; only the approve and disapprove tests run.
- `kyc_assistant_example.py` — Drives the full `KycAssistant` KYC pause/resume: the user asks to register but omits details, the assistant pauses on the HITL request for name/email, then the human reply ("Craig Li, craig@binome.dev") resumes the workflow so `register_client` fires and a summary is returned. Includes a strict name+email validator system message.
- `simple_hitl_assistant_example.py` — Tests two consecutive pause/resume rounds of `SimpleHITLAssistant` (asks for name, then age) using `async_func_wrapper` with `is_sequential=True`, asserting the event store grows 18 -> 36 -> 54 events across the initial request and the two human replies.
- `simple_hitl_assistant_async_example.py` — Same 18/36/54 two-round pause/resume scenario as above, but consumes the assistant via `async for output in assistant.invoke(...)` streaming iteration (collecting `ConsumeFromTopicEvent` lists) instead of `async_func_wrapper`, verifying the async streaming path of the HITL flow.

## Runner

- `run_hith_assistant.py` — Discovers and runs every `*_example.py` in this directory as a subprocess, skipping `ollama`/`_local` scripts unless `--no-pass-local` is passed, and prints a pass/fail summary (exit code 1 on any failure).
