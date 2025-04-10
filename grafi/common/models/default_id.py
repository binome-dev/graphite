import uuid

from pydantic import Field


default_id = Field(default_factory=lambda: uuid.uuid4().hex)
