import json
import re
import os
from typing import AsyncGenerator
from typing import Literal
from typing import Union
from typing import overload

from grafi.assistants.assistant_base import AssistantBase
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.decorators.record_decorators import record_assistant_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.manifest import ManifestError
from grafi.runtime.deltas import Delta


class Assistant(AssistantBase):
    """An assistant that runs an event-driven workflow on each request, and
    saves as a manifest holding that workflow (see ``generate_manifest``)."""

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: Literal[False] = False,
    ) -> AsyncGenerator[ConsumeFromTopicEvent, None]: ...

    @overload
    def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]: ...

    @record_assistant_invoke
    async def invoke(
        self,
        input_data: PublishToTopicEvent,
        is_sequential: bool = False,
        *,
        stream: bool = False,
    ) -> AsyncGenerator[Union[ConsumeFromTopicEvent, Delta], None]:
        """Run the assistant's workflow on ``input_data``, yielding its outputs
        as they are committed, and, if ``stream``, each :class:`Delta` its tools
        emit as they emit it, such as an LLM's tokens."""
        async with owned_iterator(
            self.workflow.invoke(input_data, is_sequential, stream=stream)
        ) as outputs:
            async for output in outputs:
                yield output

    def generate_manifest(self, output_dir: str = ".") -> str:
        """Write the assistant's manifest (see ``to_manifest()``) to
        ``<name>_manifest.json`` in ``output_dir``, and return its path. Load
        it back with ``Assistant.from_manifest(path)``."""
        if not re.fullmatch(r"\w[\w .-]*", self.name) or ".." in self.name:
            raise ManifestError(
                f"The assistant's name {self.name!r} names its manifest's file, "
                "so it holds no path."
            )
        text = json.dumps(self.to_manifest(), indent=2) + "\n"
        output_path = os.path.join(output_dir, f"{self.name}_manifest.json")
        # Written beside it, then moved over it, so a failure leaves it whole.
        partial = f"{output_path}.{os.getpid()}.tmp"
        try:
            with open(partial, "w") as f:
                f.write(text)
            os.replace(partial, output_path)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        return output_path
