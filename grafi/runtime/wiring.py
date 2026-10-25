"""What a workflow wires to each of its nodes: the functions an LLM node is
offered, and the calls a function-call node answers besides its own.

A run works it out from its workflow's nodes as it starts, and binds each
node's wiring to the node's steps. There, only the node's tool, or a copy of
it (same tool_id), reads it: an LLM in its get_function_specs(), a
function-call tool through its command. So a workflow stores none of it in
the tools and nodes it shares with another workflow, or with a copy of
itself.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import field
from typing import FrozenSet
from typing import Iterator
from typing import Mapping
from typing import Optional
from typing import Tuple

from grafi.common.models.function_spec import FunctionSpec


@dataclass(frozen=True)
class Wiring:
    """A node's wiring in its workflow."""

    # The id of the node's tool, which alone reads it: the tool, or a copy of
    # it, such as model_copy() makes.
    tool_id: Optional[str] = None
    # An LLM node's: the functions of the function-call nodes reading its calls.
    functions: Tuple[FunctionSpec, ...] = ()
    # A function-call node's, for each topic where it answers unknown calls:
    # the functions offered to the LLMs calling there. It answers a call there
    # naming any other with an error.
    offered: Mapping[str, FrozenSet[str]] = field(default_factory=dict)


_wiring: ContextVar[Wiring] = ContextVar("grafi_wiring", default=Wiring())


def wiring(tool_id: str) -> Wiring:
    """The wiring of the node whose tool has ``tool_id``, in a step of it;
    none elsewhere, also for another tool run in the step."""
    node_wiring = _wiring.get()
    return node_wiring if tool_id == node_wiring.tool_id else Wiring()


@contextmanager
def wired(node_wiring: Wiring) -> Iterator[None]:
    """Run the block with ``node_wiring``, as a step of its node."""
    token = _wiring.set(node_wiring)
    try:
        yield
    finally:
        _wiring.reset(token)
