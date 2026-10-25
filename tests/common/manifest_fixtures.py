"""Components and helpers shared by the manifest tests (test_manifest.py,
test_manifest_component.py, test_manifest_secrets.py).

A plain module, not a conftest: the tests import what they use by name. It is
trusted, as an application's own modules are, so manifests may name its classes.
"""

from contextlib import contextmanager
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Type

import pytest
from pydantic import BaseModel
from pydantic import Field
from pydantic_core import PydanticSerializationError

from grafi.common.import_ref import trust_modules
from grafi.common.manifest import Component
from grafi.common.manifest import ModelRef
from grafi.common.manifest import env_secret

trust_modules(__name__)

SECRET_VAR = "GRAFI_TEST_MANIFEST_SECRET"
OTHER_VAR = "GRAFI_TEST_MANIFEST_OTHER_SECRET"


class Gadget(Component):
    manifest_kind: ClassVar[Optional[str]] = "Gadget"

    name: str = "gadget"
    size: int = 1


class Widget(Gadget):
    color: str = "red"


class Unrelated(Component):
    label: str = ""


class Holder(Component):
    item: Gadget = Field(default_factory=Gadget)


class Keyed(Component):
    api_key: Optional[str] = env_secret(SECRET_VAR)
    token: Optional[str] = env_secret()  # Without a variable of its own.
    name: str = "keyed"


class Answer(BaseModel):
    text: str


class Formatted(Component):
    params: ModelRef[Dict[str, Any]] = Field(default_factory=dict)


class Box(Component):
    """Fields declaring a base class, holding its subclasses."""

    gadget: Optional[Gadget] = None
    gadgets: List[Gadget] = Field(default_factory=list)
    keyed: Optional[Keyed] = None


# Settings holding a secret: by field, its value, and the name it is held at.
HELD_SECRETS = [
    ("params", {"extra_headers": {"Authorization": "Bearer sk-1"}}, "Authorization"),
    ("params", {"servers": [{"name": "s", "password": "pw"}]}, "password"),
    ("params", {"client_secret": "cs", "temperature": 0.2}, "client_secret"),
    ("params", {"auth": {"token": "t0ken"}}, "auth"),  # Under the outer name.
    ("headers", {"Accept": "text/plain", "X-Api-Key": "k"}, "X-Api-Key"),
    # Text holding more than a reference to a variable.
    ("headers", {"Authorization": "Bearer sk ${API_TOKEN}"}, "Authorization"),
    ("headers", {"Authorization": "sk-literal-1 ${API_TOKEN}"}, "Authorization"),
    ("params", {"api_key": "${OPENAI_API_KEY}-suffix"}, "api_key"),
    # Headers as [name, value] pairs.
    (
        "params",
        {"headers": [["Accept", "text/plain"], ["Authorization", "Bearer sk-1"]]},
        "Authorization",
    ),
    # Names in camelCase.
    ("params", {"clientSecret": "cs"}, "clientSecret"),
    ("params", {"dbPassword": "pw"}, "dbPassword"),
    ("params", {"accessToken": "t0ken"}, "accessToken"),
    # A dict held under a secret's name: all of it is under that name.
    ("params", {"api_keys": {"openai": "sk-1"}}, "api_keys"),
    ("params", {"credentials": {"key": "sk-1"}}, "credentials"),
    # [name, value] pairs held under a secret's name.
    ("params", {"api_key": [["openai", "sk-pair"]]}, "api_key"),
    # A URL's query parameter named like a secret.
    ("params", {"proxy": "https://proxy.example/v1?api_key=sk-q"}, "proxy"),
    # A dict holding a "class" key is checked too.
    ("params", {"tool": {"class": "my_app:Tool", "api_key": "sk-1"}}, "api_key"),
    # A URL's password.
    (
        "params",
        {"db": {"url": "postgresql://app:pw@db.example.com/app"}},
        "url",
    ),
    (
        "params",
        {"mirrors": ["https://user:pw@mirror.example.com/x"]},
        "mirrors",
    ),
]

# Settings holding no secret's value: references to variables, ways to
# authenticate, empty values, and names that only look like a secret's.
UNHELD_SETTINGS = [
    {"api_key": "", "access_token": None, "secret": 0},
    {"max_tokens": 10, "eos_token": "</s>", "cache_key": "k", "tokens": ["a"]},
    {"pad_token": "<pad>", "mask_token": "<mask>", "maxTokens": 5},
    {"url": "https://user@example.com/x", "home": "https://example.com/@me"},
    # A JSON Schema names its properties: they are not settings.
    {
        "response_format": {
            "type": "object",
            "properties": {"pageToken": {"type": "string"}, "password": {}},
            "required": ["pageToken"],
            "$defs": {"AccessToken": {"type": "string"}},
        }
    },
]

# Settings referring to a variable, as "${VAR}", which hold no secret where
# they are expanded: in an MCP configuration.
REFERRING_SETTINGS = [
    {"extra_headers": {"Authorization": "Bearer ${API_TOKEN}"}},
    {"api_key": "${OPENAI_API_KEY}", "nested": [{"password": "${DB_PASSWORD}"}]},
    {"Authorization": "Basic ${CREDENTIALS}", "X-Auth": "Token ${API_TOKEN}"},
    {"auth": "oauth"},  # A way to authenticate, as MCP's.
    {"extra_headers": {"Authorization": "ApiKey ${ES_API_KEY}"}},  # Any scheme.
    {"headers": [["Authorization", "Bearer ${API_TOKEN}"], ["Accept", "*/*"]]},
    {"url": "postgresql://app:${DB_PASSWORD}@db.example.com/app"},
]


@contextmanager
def raises_on_dump(expected: Type[Exception], match: str) -> Iterator[None]:
    """Expect ``model_dump`` to fail with an ``expected`` error matching
    ``match``, which pydantic reports in its own."""
    with pytest.raises(PydanticSerializationError, match=match) as info:
        yield
    assert f"{expected.__name__}: " in str(info.value)
