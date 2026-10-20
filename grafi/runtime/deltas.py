"""Deltas: pieces of a tool's output as it is produced, such as an LLM's tokens.

A caller streaming a run (``invoke(..., stream=True)``) receives the deltas its
steps emit as they emit them, among the run's outputs. Deltas are a side
channel: they are neither published to topics nor stored, so routing and the
event log only ever see whole messages, which follow as the tool's output. A
resumed run streams again what it runs again.

A tool sends text with :func:`emit_delta`. One whose output costs more to stream,
such as an LLM that asks its provider for a stream, first checks
:func:`streaming`.
"""

import asyncio
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from typing import Callable
from typing import Optional


@dataclass(frozen=True, slots=True)
class Delta:
    """A piece of a tool's output, such as a token, for a streaming caller."""

    content: str
    # The node whose step emitted it, and the step: the run counts its steps
    # from 1 as they start, so a node's next turn, such as an agent's answer
    # after its tool calls, is a new one.
    node_name: Optional[str] = None
    step: Optional[int] = None
    # The tool call whose function emitted it, if one did.
    tool_call_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class _Receiver:
    receive: Callable[[Delta], None]
    loop: Optional[asyncio.AbstractEventLoop]  # Where receive() must run.
    delta: Delta  # What a delta emitted here carries besides its content.


_receiver: ContextVar[Optional[_Receiver]] = ContextVar(
    "grafi_delta_receiver", default=None
)


def streaming() -> bool:
    """Whether the deltas emitted here reach a caller."""
    return _receiver.get() is not None


def emit_delta(content: str) -> None:
    """Send ``content`` to the caller streaming the run, if any. Safe from a
    worker thread, such as one running a sync function."""
    receiver = _receiver.get()
    if receiver is None or not content:
        return
    delta = replace(receiver.delta, content=content)
    if receiver.loop is None or _running_loop() is receiver.loop:
        receiver.receive(delta)
    else:
        receiver.loop.call_soon_threadsafe(receiver.receive, delta)


def _running_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class _Binding:
    """Binds a receiver, or none, to a block, and the tasks it starts."""

    __slots__ = ("_receiver", "_token")

    def __init__(self, receiver: Optional[_Receiver]) -> None:
        self._receiver = receiver
        self._token: Optional[Token[Optional[_Receiver]]] = None

    def __enter__(self) -> None:
        self._token = _receiver.set(self._receiver)

    def __exit__(self, *exc_info: Any) -> None:
        token, self._token = self._token, None
        if token is not None:
            _receiver.reset(token)


def deltas_to(
    receive: Optional[Callable[[Delta], None]],
    node_name: Optional[str] = None,
    step: Optional[int] = None,
) -> _Binding:
    """Send the deltas emitted in the block to ``receive``, called on the loop
    that made the binding; or, with None, to no one. The tasks the block
    starts, and the threads ``asyncio.to_thread`` runs, inherit it. A workflow
    run binds one for each step, so tests and code invoking a tool directly
    can collect its deltas the same way: ``with deltas_to(received.append):``.
    """
    if receive is None:
        return _Binding(None)
    delta = Delta("", node_name=node_name, step=step)
    return _Binding(_Receiver(receive, _running_loop(), delta))


def deltas_for(tool_call_id: str) -> _Binding:
    """Mark the deltas emitted in the block as ``tool_call_id``'s, as the
    function answering that call emits them."""
    receiver = _receiver.get()
    if receiver is None:
        return _Binding(None)
    return _Binding(
        replace(receiver, delta=replace(receiver.delta, tool_call_id=tool_call_id))
    )
