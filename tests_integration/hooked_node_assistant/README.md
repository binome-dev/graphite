# hooked_node_assistant

Real-world `HookedNode` use cases — a pre-execution approval gate, a post-generation review gate, and a pure guardrail hook chain — showing pre/post `ToolHook` chains, HITL pause/resume channels via `ConsumerRouter` + `from_stage`, and manifest-safe custom hooks.

## Assistants

### `pre_approval_assistant.py` — `RefundApprovalAssistant`

A customer-service refund agent that runs a **policy screen in front of a human approval gate** on the refund node's PRE-tool chain. `SpendingLimitHook` (custom) auto-denies over-limit refunds by policy before any human is asked; `HITLApprovalHook` (built-in, `gate_when=has_tool_call_message`) pauses in-limit refunds for a human verdict. The LLM node justifies each call with the built-in `ToolCallReasonHook`. On resume, `ConsumerRouter(pre_hitl_input=...)` classifies the verdict: a bare "approve" recovers the STORED proposal from the event store and runs the tool; a denial reply skips the tool and flows back to the LLM.

Topology:

```
[input]
   |
   v
(agent_input_topic) ------+
                          |  .or_()
(refund_result_topic) ----+
                          v
   [RefundLLMNode: OpenAITool | pre: ToolCallReasonHook]
                          |
        +-----------------+--------------------------+
        |                                            |
  --when=has_tool_call-->                    --when=has_no_tool_call-->
        |                                            |
        v                                            v
(refund_call_topic)                          (agent_output_topic)
        |                                            |
        |                                            v
        |                                         [output]
        |
(refund_call_topic) ---------+
                             |  .or_()
(approval_response_topic) ---+  [in-workflow input / RESUME]
      ^                      v
      |   [RefundFunctionNode: ProcessRefund | pre: SpendingLimitHook -> HITLApprovalHook]
      |     router: ConsumerRouter(pre_hitl_input = approval_response_topic)
      |                      |
      |          +-----------+-----------------------------+
      |          |                                         |
      |    --publish_to-->                       --from_stage=PRE_HOOK-->
      |          |                                         |
      |          v                                         v
      |  (refund_result_topic) --> back to RefundLLMNode   (approval_request_topic)
      |                                                    [in-workflow output / PAUSE]
      |                                                         |
      +<-------------- paired resume channel ------------------+
```

### `post_review_assistant.py` — `AnnouncementReviewAssistant`

A single-node drafting agent with a **post-generation editorial review gate**. Every draft the LLM produces is paused by a post-tool `HITLApprovalHook` (built-in) on an in-workflow output topic. On approval the EXACT reviewed draft is recovered from the event store and released without re-invoking the LLM (deterministic, byte-for-byte); on denial the reviewer's feedback is forwarded instead. `ConsumerRouter(post_hitl_input=...)` classifies the verdict on resume.

Topology:

```
[input]
   |
   v
(agent_input_topic) -------+
                           |  .or_()
(review_response_topic) ---+  [in-workflow input / RESUME]
      ^                    v
      |   [AnnouncementDraftNode: OpenAITool | post: HITLApprovalHook]
      |     router: ConsumerRouter(post_hitl_input = review_response_topic)
      |                    |
      |          +---------+---------------------------+
      |          |                                     |
      |    --publish_to-->                    --from_stage=POST_HOOK-->
      |          |                                     |
      |          v                                     v
      |  (agent_output_topic)                  (review_request_topic)
      |          |                             [in-workflow output / PAUSE]
      |          v                                     |
      |       [output]                                 |
      +<------------- paired resume channel -----------+
```

### `guardrail_chain_assistant.py` — `GuardrailSupportAssistant`

A support agent whose single LLM node carries a **guardrail hook chain with no human in the loop**. The PRE chain runs `RedactPIIHook` (custom — masks emails/phones before the LLM sees the input); the POST chain runs `DisclaimerHook` (custom — stamps a disclaimer onto the final reply). Both are pure transforms that always PROCEED, so there is no pause channel and no consumer router: it is a straight input → LLM → output pipeline.

Topology:

```
[input]
   |
   v
(agent_input_topic)
   |
   v
[GuardrailLLMNode: OpenAITool | pre: RedactPIIHook | post: DisclaimerHook]
   |
   v
(agent_output_topic)
   |
   v
[output]
```

## Examples

- `pre_approval_assistant_example.py` — Wires `ProcessRefund` (a `FunctionCallTool`) as the refund tool with a $500 limit. Three test functions: `test_refund_approved` — an in-limit refund ($120) passes policy, the human gate pauses (first output surfaces the pending `tool_calls`), then a bare "approve" recovers the STORED proposal and runs the tool, and the final message has no `tool_calls` and mentions "refund". `test_refund_denied` — an in-limit refund ($200) pauses, then a substantive denial reply ("no, the customer already used the product") skips the tool and flows back through the LLM as a plain final answer (no `tool_calls`). `test_refund_over_limit_auto_denied` — an over-limit refund ($9000) is denied by `SpendingLimitHook` before the human gate, so a SINGLE invoke completes with a final answer (no pause, no reviewer, no pending `tool_calls`).
- `post_review_assistant_example.py` — Two test functions: `test_draft_approved_releases_exact_reviewed_text` — a draft pauses for review, then "approve" recovers the reviewed draft from the event store and releases it BYTE-FOR-BYTE (`released == reviewed_draft`), proving the LLM was not re-run. `test_draft_denied_forwards_feedback` — a draft pauses, then a denial ("no - too informal, do not release") forwards the reviewer's feedback instead of the draft (output has no `tool_calls` and contains the feedback text).
- `guardrail_chain_assistant_example.py` — Sends a message containing an email and phone number. `test_pii_redacted_and_disclaimer_appended` — asserts the reply leaks neither the raw email nor the raw phone digits (checked with punctuation stripped) and ends with `DisclaimerHook().disclaimer`. `test_manifest_round_trip_preserves_guardrails` — round-trips the assistant through `to_dict()` → JSON → `Assistant.from_dict()`, asserts the restored `GuardrailLLMNode` is a `HookedNode` with one `RedactPIIHook` pre-hook and one `DisclaimerHook` post-hook (custom hooks reconstruct via class-name auto-registration on import), then re-invokes and re-asserts the guardrails still apply (api_key is masked in the manifest and falls back to `OPENAI_API_KEY`).

## Runner

- `run_hooked_node_assistant.py` — Discovers every `*_example.py` in this directory and runs each as a subprocess, skipping `ollama`/`_local` scripts by default (`--no-pass-local` to include them), printing a pass/fail summary and returning an exit code (0 pass / 1 fail); a `collect=True` mode returns per-script results without printing.
