import json
import os
import uuid
from pathlib import Path
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
        stream: bool = False,
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

    def generate_manifest(self, output_dir: "str | os.PathLike[str]" = ".") -> Path:
        """Write the assistant's manifest (see ``to_manifest()``) to
        ``<name>_manifest.json`` in ``output_dir``, and return its path. Load
        it back with ``Assistant.from_manifest(path)``."""
        if any(char in self.name for char in "/\\:\0"):
            raise ManifestError(
                f"The assistant's name {self.name!r} names its manifest's file, "
                "so it holds no '/', '\\', ':' or NUL."
            )
        text = json.dumps(self.to_manifest(), indent=2) + "\n"
        output_path = Path(output_dir) / f"{self.name}_manifest.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside it, then moved over it, so a failure leaves it whole,
        # and a link there is replaced, never followed; made as open() makes a
        # file, as the umask allows.
        partial = output_path.with_name(f".{uuid.uuid4().hex}.partial")
        try:
            with open(partial, "x", encoding="utf-8") as file:
                file.write(text)
            os.replace(partial, output_path)
        finally:
            partial.unlink(missing_ok=True)
        return output_path
