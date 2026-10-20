"""A component that is a callable, saved as its configuration.

A callable that needs configuration (rather than just being a named function,
referenced by import path) is a ``CallableComponent``: subclass it, declare the
configuration as fields, and implement :meth:`__call__`. The *behavior* lives in
your subclass (ordinary, reviewable Python in your codebase); the *manifest*
holds only its class and fields, as any component's.

Example::

    class ThresholdCondition(CallableComponent):
        field: str
        minimum: float

        def __call__(self, event: PublishToTopicEvent) -> bool:
            value = getattr(event.data[-1], self.field, 0)
            return value >= self.minimum

A ``ThresholdCondition(field="score", minimum=0.8)`` is saved as::

    {"class": "my_app.conditions:ThresholdCondition",
     "field": "score", "minimum": 0.8}

No pickle, no embedded code: loading re-imports the class, from a trusted
module, and validates its fields, so a tampered manifest can at most build a
declared component with declared fields -- never execute arbitrary code.
"""

from abc import ABC
from abc import abstractmethod
from typing import Any

from grafi.common.manifest import Component


class CallableComponent(Component, ABC):
    """Base class for configurable callables, saved as components.

    :meth:`__call__` is abstract, so a subclass that forgets it (or the base
    itself) cannot be instantiated -- the contract is enforced when the component
    is built (e.g. as a manifest loads) rather than failing later at call time.
    """

    @abstractmethod
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the component's behavior. Implemented by subclasses."""
