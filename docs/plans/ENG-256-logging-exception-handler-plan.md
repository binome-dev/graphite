# ENG-256 Logging and Exception Handler Improvement Plan

## Feature/Issue summary

The current logging and exception handling path does not expose enough information to debug failed assistant, workflow, node, and tool runs. The main failure recorder only persists `str(e)`, so users lose exception type, wrapped cause chain, traceback, component metadata, and invoke context details that are already available in the runtime.

Goal: improve runtime logs, failed events, and trace error attributes so a developer can identify which component failed, why it failed, and what the underlying cause chain was without changing successful execution behavior.

Scope clarification: the code already uses `raise ... from e` throughout, so an *uncaught* exception escaping `assistant.invoke()` still prints Python's full chained traceback. The breakage this plan targets is specifically in the *logged* and *persisted* representations — `logger.error(f"... {e}")` emits no traceback, and failed events store only `str(e)` — which is what developers actually inspect when a run fails inside the framework. The fix must surface the traceback, the cause chain, and the component location in those two paths.

## Current code findings

- Recording is centralized in `grafi/common/decorators/record_base.py`.
  - `create_async_decorator()` wraps assistant, workflow, node, and tool invokes.
  - It records invoke events before execution and respond events after success.
  - On exception it only does `span.set_attribute("error", str(e))` and creates the failed event with `error=str(e)` (`grafi/common/decorators/record_base.py:138-151`).
  - The same decorator wraps all four layers (tool, node, workflow, assistant) and each `except` block re-raises the failure upward, so one root failure is recorded and logged at every layer it propagates through. Any per-layer traceback logging must therefore be de-duplicated, or it will emit the same stack trace four-plus times and bury the signal.
- Failed event serialization is also string-only.
  - `FailedEvent` has `error: Any`, but `to_dict()` serializes only `"error": str(self.error)` (`grafi/common/events/component_base.py:129-141`).
  - `ComponentFailedEvent.from_dict()` reads only `data["error"]` (`grafi/common/events/component_base.py:290-320`).
  - Current tests assert the exact current failed-event shape in `tests/events/tool_events/test_tool_failed_event.py:39-87`, `tests/events/node_events/test_node_failed_event.py:51-108`, `tests/events/workflow_events/test_workflow_failed_event.py`, and `tests/events/assistant_events/test_assistant_failed_event.py`.
- There is already a Grafi exception hierarchy with useful fields.
  - `GrafiError` stores `message`, `cause`, `invoke_context`, `timestamp`, and `severity`, and has `to_dict()` (`grafi/common/exceptions/base.py:13-57`).
  - `NodeExecutionError` adds `node_name` (`grafi/common/exceptions/workflow_exceptions.py:18-30`).
  - `ToolInvocationError` adds `tool_name`; `LLMToolException`, `FunctionCallException`, and `FunctionToolException` add `model`, `function_name`, or `operation` (`grafi/common/exceptions/tool_exceptions.py:12-75`).
  - `GrafiError.to_dict()` does not currently include subclass fields, exception module, traceback, or recursive cause details.
- Workflow and tool boundaries wrap exceptions repeatedly.
  - Tool failures are wrapped in domain exceptions in `FunctionTool.invoke()` (`grafi/tools/functions/function_tool.py:47-68`), `FunctionCallTool.invoke()` (`grafi/tools/function_calls/function_call_tool.py:118-151`), and LLM tool implementations such as `OpenAITool.invoke()` (`grafi/tools/llms/impl/openai_tool.py:102-151`).
  - Workflow node execution wraps lower-level failures into `NodeExecutionError` in sequential and parallel paths (`grafi/workflows/impl/event_driven_workflow.py:306-312`, `379-384`, `435-440`, `544-553`, `568-573`).
  - The top-level workflow invoke re-raises `NodeExecutionError` but wraps other errors in `WorkflowError` (`grafi/workflows/impl/event_driven_workflow.py:578-607`).
  - Each wrap builds its message with an f-string such as `f"Node execution failed: {e}"`, and `GrafiError.__str__` already appends `[Caused by: ...]`, so the persisted `error` string nests redundantly at every layer and becomes hard to read. The structured `cause` chain is the real fix; the flat string is kept only for backward compatibility.
- Logging is currently direct Loguru usage without a Grafi-specific logging utility.
  - `loguru` is a dependency in `pyproject.toml`.
  - Modules import `from loguru import logger` directly, for example `grafi/common/containers/container.py:7` and `grafi/workflows/impl/event_driven_workflow.py`.
  - There is no package-level `configure_logging()` or structured context helper.
- Event-store deserialization errors also drop traceback and cause details.
  - `_create_event_from_dict()` logs only `Failed to create event from dict: {e}` and raises a new `ValueError` without `from e` (`grafi/common/event_stores/event_store.py:67-81`).
- Tracing docs promise richer failed-event and trace behavior than the implementation provides.
  - `docs/docs/user-guide/invoke-decorators.md` says decorators capture exception details, add error information to spans, and preserve context, but the code currently records only a string.

## Proposed implementation approach

1. Add a small exception serialization utility.
   - Add a new module such as `grafi/common/exceptions/serialization.py`.
   - Define an `ErrorDetails` Pydantic model or typed dict with fields:
     - `error_type`
     - `error_module`
     - `message`
     - `severity`
     - `timestamp`
     - `component_type`
     - `component_name`
     - `component_id`
     - `invoke_context`
     - domain fields when present: `node_name`, `tool_name`, `model`, `function_name`, `operation`, `topic_name`
     - `cause`, recursively summarized over a bounded chain (depth cap, e.g. 10) with a cycle guard on already-seen exception ids, so self-referential or very deep `__cause__`/`cause` chains cannot loop or bloat the record
     - `traceback`, controlled by an option
   - Provide functions:
     - `error_to_dict(exc, *, include_traceback: bool = True, max_traceback_frames: int | None = None) -> dict`
     - `flatten_error_chain(exc) -> list[dict]`
     - `error_message(exc) -> str`
     - `has_logged_traceback(exc) -> bool`
     - `mark_traceback_logged(exc) -> None`
   - Use existing `GrafiError` fields as the primary source, then fall back to generic exception attributes.
   - For the cause chain, traverse a single consistent source (prefer `GrafiError.cause`, fall back to `exc.__cause__`, then `exc.__context__`). In this codebase `cause=e` and `raise ... from e` are set together, so they coincide; pick one order and document it.
   - Keep the returned details strictly JSON-compatible before they are placed in events, since `EventStorePostgres` persists `event_data` as JSONB. Use primitives/lists/dicts only, and sanitize any unexpected values with the same style as the existing `to_jsonable_python` usage in `record_base.py`.

2. Extend `GrafiError.to_dict()` instead of replacing it.
   - Keep existing keys (`error_type`, `message`, `timestamp`, `severity`, `cause`, `invoke_context`) for compatibility.
   - Add optional subclass fields for known exception attributes.
   - Add a non-breaking `cause_details` object or chain list.
   - Avoid making traceback mandatory in `GrafiError.to_dict()` if that would make deterministic tests harder; traceback can be added by `error_to_dict()` at capture time.

3. Make failed events backward compatible but more useful.
   - Keep `data["error"]` as the same human-readable string so existing stored events and tests keep a stable field.
   - Add `data["error_details"]` as an optional structured object.
   - Update `FailedEvent` in `grafi/common/events/component_base.py` with an optional `error_details: Optional[Dict[str, Any]] = None`.
   - Update `FailedEvent.to_dict()` to include `error_details` only when present.
   - Update `ComponentFailedEvent.from_dict()` to read `data["data"].get("error_details")` so old event data still loads.
   - Keep event type values unchanged.

4. Improve the decorator exception handler.
   - In `create_async_decorator()` (`grafi/common/decorators/record_base.py`), build structured details once in the `except Exception as e` block.
     - Build the details (and any `traceback.format_exception(...)` call) from inside the `except` block while the caught exception object is still in scope and its `__traceback__` is available.
   - Add component metadata from `EventContext` into the structured details.
   - Record failed events with both `error=str(e)` and `error_details=...`. Failed events are persisted and queried per layer, so recording full details at every layer is fine and useful — the de-duplication below applies only to console/file traceback logging, not to events.
   - De-duplicate console/file traceback logging across the four stacked decorator layers (tool → node → workflow → assistant) so one root failure does not print the same stack trace four-plus times:
     - Emit the full `logger.opt(exception=e).error(...)` traceback once, at the layer closest to the failure (the first decorator to catch it — the innermost tool/node layer), which is also the most precise "where the error is".
     - Mark the exception as already-logged and have outer layers that see the mark log only a concise one-line summary (component name, type, message) instead of repeating the full trace.
     - The mark cannot be checked only on the current exception object. The workflow creates new wrapper exceptions such as `NodeExecutionError(..., cause=node_error)` after the tool/node decorator has already logged the inner exception. Therefore `has_logged_traceback(exc)` must scan the wrapped cause chain (`GrafiError.cause`, `__cause__`, `__context__`) and return true if any linked exception is marked.
     - `mark_traceback_logged(exc)` can set a private attribute such as `_grafi_traceback_logged = True`; if a third-party exception does not allow custom attributes, fall back to an internal id-based set for the current process.
     - When logging a newly-created wrapper exception whose cause chain is already marked, mark the wrapper too. This keeps later assistant/workflow layers concise without relying on repeated cause-chain scans.
     - The manual `logger.error(f"... {e}")` calls inside `event_driven_workflow.py` (`invoke_parallel`/`_invoke_node`, lines ~371, 434, 545, 566) must use the same helper and cause-chain-aware flag so they do not add further duplicate traces.
   - Set trace attributes such as:
     - `error = True`
     - `error.type`
     - `error.message`
     - `error.stack`
     - `error.details` as JSON when serializable
   - Use `span.record_exception(e)` and `span.set_status(Status(StatusCode.ERROR, ...))` if the OpenTelemetry span supports it.
   - Log using Loguru with `logger.bind(...)` and `logger.opt(exception=e).error(...)` so console/file logs include traceback and context, subject to the de-duplication rule above.
   - Preserve current behavior by re-raising the same exception.

5. Add a small Grafi logging helper.
   - Add `grafi/common/logging.py` or `grafi/common/logging_utils.py`.
   - Provide helpers such as:
     - `bind_invoke_context(logger, invoke_context, **extra)`
     - `log_exception(exc, *, component_name, component_type, invoke_context, metadata=None)`
     - optional `configure_logging(level: str | None = None, json: bool = False)` for applications that want standard Loguru setup.
   - Avoid forcing global `logger.remove()` at import time; library code should not surprise host applications.
   - Use this helper first in `record_base.py`, and only later migrate scattered direct `logger.error(f"... {e}")` calls if needed.

6. Improve exception chaining where current code loses cause context.
   - Change `grafi/common/event_stores/event_store.py:79-81` to log with exception details and raise `ValueError(...) from e`.
   - For workflow log lines such as `logger.error(f"Node {node_name} failed with exception: {result}")`, use exception-aware logging where `result` is an exception object.
   - Do not remove existing `raise ... from ...` statements; they are important for cause chains.
   - Point log/event consumers and docs at the structured `error_details.cause` chain for the readable root cause, rather than the flat nested `error` string, which stays only for backward compatibility.

7. Update docs after behavior changes.
   - Update `docs/docs/user-guide/invoke-decorators.md` to describe `data.error` and optional `data.error_details`.
   - Add a brief example of configuring Loguru through the new helper if `configure_logging()` is added.

## Files to change

- `grafi/common/exceptions/serialization.py`
  - New utility for structured exception serialization, cause-chain extraction, and traceback formatting.
- `grafi/common/exceptions/base.py`
  - Extend `GrafiError.to_dict()` with optional subclass fields and structured cause details.
- `grafi/common/events/component_base.py`
  - Add optional `error_details` to `FailedEvent`.
  - Serialize `error_details` when present.
  - Deserialize it with `data["data"].get("error_details")`.
- `grafi/common/decorators/record_base.py`
  - Build structured exception details in the centralized async decorator.
  - Record enhanced failed events.
  - Add exception-aware Loguru logging and richer span error attributes.
- `grafi/common/event_stores/event_store.py`
  - Preserve deserialization cause with `raise ... from e`.
  - Log event deserialization failures with traceback.
- `grafi/workflows/impl/event_driven_workflow.py`
  - Replace string-only `logger.error(...)` calls in node failure paths with exception-aware structured logging, but keep exception types and propagation unchanged.
- `grafi/common/logging.py` or `grafi/common/logging_utils.py`
  - New helper module for binding invoke/component context and optional user-facing logging configuration.
- Tests:
  - `tests/common/decorators/test_record_decorators.py`
  - `tests/events/tool_events/test_tool_failed_event.py`
  - `tests/events/node_events/test_node_failed_event.py`
  - `tests/events/workflow_events/test_workflow_failed_event.py`
  - `tests/events/assistant_events/test_assistant_failed_event.py`
  - Add new tests under `tests/common/exceptions/` for the serialization helper.
  - Add/update workflow and assistant exception tests in `tests/assistants/test_assistant_mock_llm.py` and/or `tests/workflow/test_event_driven_workflow.py`.
- Docs:
  - `docs/docs/user-guide/invoke-decorators.md`

## API/data model changes

- Additive event data change:
  - Current failed event:
    ```json
    {
      "data": {
        "input_data": "...",
        "error": "[ERROR] ..."
      }
    }
    ```
  - Proposed failed event:
    ```json
    {
      "data": {
        "input_data": "...",
        "error": "[ERROR] ...",
        "error_details": {
          "error_type": "NodeExecutionError",
          "error_module": "grafi.common.exceptions.workflow_exceptions",
          "message": "Async node execution failed: ...",
          "severity": "ERROR",
          "node_name": "ErrorNode",
          "invoke_context": {
            "conversation_id": "...",
            "invoke_id": "...",
            "assistant_request_id": "...",
            "user_id": "",
            "kwargs": {}
          },
          "cause": {
            "error_type": "FunctionCallException",
            "message": "Async function call failed: ..."
          },
          "traceback": "Traceback ..."
        }
      }
    }
    ```
- No event type enum changes are needed.
- No public invoke method signatures need to change.
- Optional new public API if desired:
  - `grafi.common.logging.configure_logging(...)`
  - `grafi.common.exceptions.serialization.error_to_dict(...)`

## Implementation sequencing

The intellectual fix is small; most of the line count is structure and test updates. Split the work so the debugging win lands first and the refactor follows independently.

- PR 1 — the actual debugging fix (highest leverage, ships the goal on its own):
  - Decorator exception handler in `record_base.py`: exception-aware logging with the de-duplication rule (approach step 4), plus `error_details` (error type, module, traceback, bounded cause chain, component metadata, invoke context) on failed events.
  - Minimal `FailedEvent.error_details` field plus serialize/deserialize so the details persist and old data still loads.
  - Just enough of the serialization/logging helper (inline or a thin module) to build JSON-compatible `error_details` and enforce cause-chain-aware traceback de-duplication.
  - Updated failed-event tests for the additive field; one decorator test asserting `error_details` is recorded and the original exception still propagates.
  - This PR alone makes a failed run debuggable: traceback, component location, and cause chain appear in both logs and persisted events.
- PR 2 — structure and breadth (no behavior change to the fix):
  - Extract the full `serialization.py` and `logging_utils.py` helpers; refactor PR 1's inline code onto them.
  - Extend `GrafiError.to_dict()` with subclass fields and structured cause details.
  - Fix `event_store.py` `_create_event_from_dict` to `raise ValueError(...) from e` and log with traceback.
  - Migrate the scattered `logger.error(f"... {e}")` calls in `event_driven_workflow.py` to exception-aware logging that respects the de-duplication flag.
  - Optional `configure_logging()` opt-in helper, plus the docs updates.

## Testing plan

- Unit test the exception serialization helper.
  - Generic exception with traceback.
  - `GrafiError` with `invoke_context`.
  - `NodeExecutionError` containing a `FunctionCallException` cause.
  - `LLMToolException` includes `tool_name` and `model`.
  - `FunctionCallException` includes `function_name`.
- Update failed-event serialization tests.
  - Existing tests should still assert `data["error"]`.
  - Add cases where `error_details` is present and round-trips through `to_dict()` and `from_dict()`.
  - Add old-data compatibility tests where `error_details` is absent.
- Add decorator behavior tests.
  - Trigger an exception through a decorated tool or small dummy component.
  - Assert the event store receives a failed event with `error_details.error_type`, `message`, component metadata, and invoke context.
  - Assert the original exception still propagates.
- Add workflow propagation tests.
  - Reuse existing failing tool paths from `tests/assistants/test_assistant_mock_llm.py:1618-1743`.
  - Assert the final `NodeExecutionError` still propagates.
  - Inspect recorded `ToolFailed`, `NodeFailed`, `WorkflowFailed`, or `AssistantFailed` events and verify structured cause chain contains the original user exception message.
- Add logging tests with patched Loguru logger only where stable.
  - Prefer asserting helper behavior over exact Loguru formatting.
  - Avoid brittle assertions on full traceback text.
  - Add a de-duplication test where an inner exception is marked as logged, then wrapped in `NodeExecutionError(cause=inner)`, and verify the helper treats the wrapper as already logged.
- Regression commands:
  - `uv run pytest tests/common/exceptions tests/common/decorators tests/events -q`
  - `uv run pytest tests/tools/functions/test_function_tool.py tests/tools/llm_function_calls/test_function_call_tool.py -q`
  - `uv run pytest tests/assistants/test_assistant_mock_llm.py::TestEdgeCasesAndExceptions -q`
  - Broader final run: `uv run pytest tests -q`

## Risks, assumptions, and open questions

- Risk: failed-event tests currently assert exact dictionaries. Adding `error_details` unconditionally will require fixture updates. To reduce breakage, include it only when passed and add compatibility tests for old event data.
- Risk: tracebacks can include local paths and large payloads. The implementation should support disabling traceback capture or limiting frames, probably through environment variables or helper options.
- Risk: `input_data` may contain user content or tool arguments. The logging helper should avoid logging full inputs by default; failed events already persist input data today, so this plan should not expand logged sensitive payloads beyond current event storage.
- Risk: Loguru global configuration in a library can interfere with host applications. Keep `configure_logging()` opt-in.
- Risk: the four stacked decorator layers each catch and re-raise the same failure, so naive `logger.opt(exception=e)` logging emits the same traceback four-plus times (more once the manual workflow `logger.error` calls are made exception-aware), which buries the signal and makes debugging harder rather than easier. Mitigation: log the full traceback once at the layer closest to the failure and mark the exception so outer layers log only a one-line summary (see approach step 4). Full structured `error_details` are still recorded on every layer's failed event.
- Assumption: the primary requested improvement is for the Grafi library runtime path, not only the integration examples.
- Assumption: persisted event schemas can accept additive JSON fields because `EventStorePostgres` stores `event_data` as JSONB and in-memory storage keeps event objects.
- Open question: should `error_details.traceback` be stored in persistent events by default, or only emitted to logs/traces? Recommendation: include it by default in local/dev, make it configurable for production.
- Open question: should failed events store the complete cause chain for every component level or only the root cause plus immediate wrapper? Recommendation: store a bounded chain to avoid very large event records.
