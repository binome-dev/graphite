"""The execution runtime: composition root and invocation entry point.

``GrafiRuntime`` owns an :class:`ExecutionServices` and is the public way to run
an assistant. ``invoke`` binds those services to the request scope and then
drives the assistant's *unchanged* call chain; components resolve infrastructure
through :func:`current_services`, so no ``invoke`` signature carries a
``services`` parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import AsyncGenerator
from typing import Optional

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services

if TYPE_CHECKING:
    from grafi.assistants.assistant_base import AssistantBase


class GrafiRuntime:
    """Holds runtime dependencies and runs assistants under a bound scope.

    ``GrafiRuntime()`` uses the in-process :class:`ExecutionServices` defaults
    (dev/test); production passes its own bundle, e.g.
    ``GrafiRuntime(ExecutionServices(event_store=EventStorePostgres(...)))``.
    """

    def __init__(self, services: Optional[ExecutionServices] = None) -> None:
        self._services = services if services is not None else ExecutionServices()

    @property
    def services(self) -> ExecutionServices:
        return self._services

    async def invoke(
        self,
        assistant: "AssistantBase",
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """Bind this runtime's services and stream the assistant's output.

        The binding is active for the whole iteration and reset on exit; child
        ``asyncio`` tasks spawned during execution inherit it.
        """
        with bind_services(self._services):
            async for event in assistant.invoke(input_data, is_sequential):
                yield event
