"""Read events stored before event version 2.

An event of version 1 (``"event_version": "1.0"``) kept its component's or
topic's fields and its invoke context under ``event_context``, a topic event
its messages as JSON text in ``data``, and a component event its input, output
and error under ``data``. :func:`upcast_v1` rewrites one as version 2: its
fields, flat, as ``Event.model_dump(mode="json")`` writes them.

grafi 0.0.25 wrote version 1 with other names: ``topic_name`` and
``topic_type``, ``node_id`` (or ``tool_``, ``workflow_``, ``assistant_``),
an assistant's or workflow's input as ``input_event``, and a tool's messages
as JSON text; those are read too. Events of grafi before 0.0.25 are not read:
decoding one raises.

Only grafi's own event types are upgraded so: an event of version 1 of a
type of yours, which its class wrote with its own ``to_dict()``, reaches the
class as stored (see :mod:`grafi.common.events.event_codec`).
"""

import json
from typing import Any
from typing import Dict
from typing import Mapping

# The key of an event of version 1 holding its context.
_CONTEXT = "event_context"

# The names grafi before 0.0.26 gave fields, by their names now.
_OLD_NAMES: Dict[str, str] = {
    "topic_name": "name",
    "topic_type": "type",
    "input_event": "input_data",
    **{
        f"{component}_{field}": field
        for component in ("node", "tool", "workflow", "assistant")
        for field in ("id", "name", "type")
    },
}


def upcast_v1(event: Mapping[str, Any]) -> Dict[str, Any]:
    """An event of version 1, as version 2.

    Raises:
        ValueError: For an event without its context, or a topic event without
            its topic's name and type.
    """
    if not isinstance(event.get(_CONTEXT), Mapping):
        raise ValueError(f"An event of version 1 holds its fields in {_CONTEXT!r}.")
    context = {_OLD_NAMES.get(k, k): v for k, v in event[_CONTEXT].items()}
    context.pop("component_type", None)
    upcast: Dict[str, Any] = {
        "event_id": event["event_id"],
        "event_version": 2,
        "event_type": event["event_type"],
        "timestamp": event["timestamp"],
        **context,
    }
    data = event.get("data")
    if isinstance(data, str):  # A topic event's messages.
        if "name" not in context or "type" not in context:
            raise ValueError("A topic event of version 1 names its topic and type.")
        upcast["data"] = json.loads(data)
    elif isinstance(data, Mapping):  # A component event's input, output, error.
        for key, value in data.items():
            if key in ("input_data", "output_data") and isinstance(value, str):
                value = json.loads(value)  # A tool's messages, before 0.0.26.
            upcast[_OLD_NAMES.get(str(key), str(key))] = _upcast_within(value)
    return upcast


def _upcast_within(value: Any) -> Any:
    """``value``, with the events of version 1 it holds as version 2."""
    if isinstance(value, Mapping) and _CONTEXT in value:
        return upcast_v1(value)
    if isinstance(value, list):
        return [_upcast_within(item) for item in value]
    return value
