"""``GrafiRuntime``: run an assistant with a given set of services.

Its ``invoke`` binds the services to the invocation and drives the assistant's
unchanged call chain; components read them through :func:`current_services`,
so no ``invoke`` signature carries a ``services`` parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import AsyncGenerator
from typing import Optional

from grafi.common.async_lifecycle import cleanup_on_exit
from grafi.common.async_lifecycle import close_iterator
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services

if TYPE_CHECKING:
    from grafi.assistants.assistant_base import AssistantBase


class GrafiRuntime:
    """Runs assistants with its own services, such as a tenant's store:
    ``GrafiRuntime(ExecutionServices(event_store=...))``. ``GrafiRuntime()`` runs
    them with the current services: those bound, else the process default.
    """

    def __init__(self, services: Optional[ExecutionServices] = None) -> None:
        self._services = services

    @property
    def services(self) -> ExecutionServices:
        return self._services or current_services()

    async def invoke(
        self,
        assistant: "AssistantBase",
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
        """Stream the assistant's output with this runtime's services bound.

        The services are bound around each read and the close (and inherited by
        tasks the stream starts), never in the caller's context between reads.
        If you stop early, close the generator (``aclose()`` or
        ``contextlib.aclosing``): one left open is closed only when it is
        garbage collected, or at loop shutdown, which closes it together with
        the generators it reads and can log errors.
        """
        # A generator's body runs in the context of whoever iterates it, so
        # the services are bound around each step rather than across a yield.
        services = self.services
        stream = assistant.invoke(input_data, is_sequential)

        async def close() -> None:
            with bind_services(services):
                await close_iterator(stream)

        async with cleanup_on_exit(close):
            while True:
                with bind_services(services):
                    try:
                        event = await anext(stream)
                    except StopAsyncIteration:
                        return
                yield event
