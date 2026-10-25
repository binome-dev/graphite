"""What a workflow wires to its nodes, as a step of each sees it."""

from typing import FrozenSet
from typing import List
from typing import Mapping

from grafi.runtime.wiring import Wiring
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.workflow import Workflow


def offered_to(workflow: Workflow, node: str) -> List[str]:
    """The names of the functions the LLM of ``node`` is offered."""
    assert isinstance(workflow, EventDrivenWorkflow)
    return [spec.name for spec in workflow.offered_to(node)]


def answered_by(workflow: Workflow, node: str) -> Mapping[str, FrozenSet[str]]:
    """By topic: the functions offered to the LLMs calling there, where
    ``node`` also answers the calls naming another."""
    assert isinstance(workflow, EventDrivenWorkflow)
    return workflow._wire().wiring.get(node, Wiring()).offered  # As a run's.
