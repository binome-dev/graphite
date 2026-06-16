"""Tests for grafi.common.exceptions.serialization."""

import json

from grafi.common.exceptions.base import GrafiError
from grafi.common.exceptions.serialization import error_message
from grafi.common.exceptions.serialization import error_to_dict
from grafi.common.exceptions.serialization import flatten_error_chain
from grafi.common.exceptions.serialization import iter_cause_chain
from grafi.common.exceptions.tool_exceptions import FunctionCallException
from grafi.common.exceptions.tool_exceptions import LLMToolException
from grafi.common.exceptions.workflow_exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext


def _raise_and_capture(exc: BaseException) -> BaseException:
    """Raise and catch so the exception gets a real ``__traceback__``."""
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001
        return caught


def test_generic_exception_with_traceback() -> None:
    err = _raise_and_capture(ValueError("boom"))
    details = error_to_dict(err)

    assert details["error_type"] == "ValueError"
    assert details["error_module"] == "builtins"
    assert details["message"] == "boom"
    assert "boom" in details["traceback"]
    assert "ValueError" in details["traceback"]
    # No cause -> no nested cause key.
    assert "cause" not in details


def test_traceback_can_be_disabled() -> None:
    err = _raise_and_capture(ValueError("boom"))
    details = error_to_dict(err, include_traceback=False)
    assert "traceback" not in details


def test_grafi_error_includes_invoke_context_and_severity() -> None:
    ctx = InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="a")
    err = GrafiError("kaboom", invoke_context=ctx, severity="CRITICAL")
    details = error_to_dict(err, include_traceback=False)

    assert details["error_type"] == "GrafiError"
    assert details["error_module"] == "grafi.common.exceptions.base"
    assert details["message"] == "kaboom"
    assert details["severity"] == "CRITICAL"
    assert details["invoke_context"]["conversation_id"] == "c"


def test_node_execution_error_with_function_call_cause() -> None:
    root = ValueError("root cause")
    fc = FunctionCallException(
        tool_name="search_tool",
        function_name="do_search",
        message="function call failed",
        cause=root,
    )
    node_err = NodeExecutionError(
        node_name="SearchNode", message="node failed", cause=fc
    )
    details = error_to_dict(node_err, include_traceback=False)

    assert details["error_type"] == "NodeExecutionError"
    assert details["node_name"] == "SearchNode"

    # Immediate cause (nested).
    assert details["cause"]["error_type"] == "FunctionCallException"
    assert details["cause"]["tool_name"] == "search_tool"
    assert details["cause"]["function_name"] == "do_search"

    # Root cause is the innermost nested cause.
    assert details["cause"]["cause"]["error_type"] == "ValueError"
    assert details["cause"]["cause"]["message"] == "root cause"
    assert "cause" not in details["cause"]["cause"]


def test_llm_tool_exception_includes_tool_name_and_model() -> None:
    err = LLMToolException(
        tool_name="openai_tool", model="gpt-4o", message="llm failed"
    )
    details = error_to_dict(err, include_traceback=False)

    assert details["tool_name"] == "openai_tool"
    assert details["model"] == "gpt-4o"


def test_function_call_exception_includes_function_name() -> None:
    err = FunctionCallException(
        tool_name="search_tool", function_name="do_search", message="failed"
    )
    details = error_to_dict(err, include_traceback=False)

    assert details["tool_name"] == "search_tool"
    assert details["function_name"] == "do_search"


def test_flatten_error_chain_is_cycle_safe() -> None:
    a = GrafiError("a")
    b = GrafiError("b", cause=a)
    a.cause = b  # introduce a cycle

    chain = flatten_error_chain(a)

    # The cycle guard yields each distinct exception exactly once.
    assert len(chain) == 2
    assert chain[0]["message"] == "a"
    assert chain[1]["message"] == "b"


def test_flatten_error_chain_is_depth_bounded() -> None:
    deepest = GrafiError("level-0")
    current = deepest
    for level in range(1, 30):
        current = GrafiError(f"level-{level}", cause=current)

    chain = flatten_error_chain(current)
    assert len(chain) == 10  # DEFAULT_MAX_CAUSE_DEPTH
    # Walk is outermost-first; the deeper tail is truncated.
    assert chain[0]["message"] == "level-29"
    assert chain[-1]["message"] == "level-20"


def test_error_message_prefers_grafi_message() -> None:
    err = GrafiError("clean message", severity="ERROR")
    # str(err) adds decoration; error_message returns the raw message.
    assert error_message(err) == "clean message"
    assert "clean message" in str(err)
    assert error_message(ValueError("plain")) == "plain"


def test_error_to_dict_is_json_safe_with_exotic_invoke_context_kwargs() -> None:
    class _Weird:
        def __repr__(self) -> str:
            return "<weird-object>"

    ctx = InvokeContext(
        conversation_id="c",
        invoke_id="i",
        assistant_request_id="a",
        kwargs={"obj": _Weird()},
    )
    err = GrafiError("boom", invoke_context=ctx)
    details = error_to_dict(err, include_traceback=False)

    # The whole payload must be JSON-serializable for JSONB persistence.
    json.dumps(details)
    # The non-serializable object is rendered to a string, not dropped.
    assert isinstance(details["invoke_context"]["kwargs"]["obj"], str)


def test_iter_cause_chain_yields_outermost_first_and_is_cycle_safe() -> None:
    root = ValueError("root")
    middle = GrafiError("middle", cause=root)
    outer = GrafiError("outer", cause=middle)

    chain = list(iter_cause_chain(outer))
    assert chain == [outer, middle, root]

    # Cycle: outer -> middle -> outer
    middle.cause = outer
    assert list(iter_cause_chain(outer)) == [outer, middle]
