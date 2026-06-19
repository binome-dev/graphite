"""A Pydantic base for callable logic that serializes as configuration data.

A workflow callable that needs configuration (rather than just being a named
function referenced by import path) is modeled as a ``CallableComponent``:
subclass it, declare the configuration as Pydantic fields, and implement
:meth:`__call__`. The *behavior* lives in your subclass (ordinary, reviewable
Python in your codebase); the *manifest* carries only a reference to the class
plus its validated field values.

Example::

    class ThresholdCondition(CallableComponent):
        field: str
        minimum: float

        def __call__(self, event: PublishToTopicEvent) -> bool:
            value = getattr(event.data[-1], self.field, 0)
            return value >= self.minimum

A ``ThresholdCondition(field="score", minimum=0.8)`` round-trips as::

    {"component": "my_app.conditions:ThresholdCondition",
     "config": {"field": "score", "minimum": 0.8}}

No pickle, no embedded code: deserialization re-imports the class and re-validates
the config, so a tampered manifest can at most construct a declared component
with declared fields -- never execute arbitrary code.
"""

from abc import ABC
from abc import abstractmethod
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict


class CallableComponent(BaseModel, ABC):
    """Base class for configurable, JSON-serializable callables.

    Subclasses declare configuration as fields and implement :meth:`__call__`.
    Instances are serialized by :mod:`grafi.common.callable_ref` as a class
    reference plus config, with no pickle.

    :meth:`__call__` is abstract, so a subclass that forgets it (or the base
    itself) cannot be instantiated -- the contract is enforced when the component
    is built (e.g. as a manifest loads) rather than failing later at call time.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the component's behavior. Implemented by subclasses."""
