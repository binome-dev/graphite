"""What holds a secret, by its name, and what refers to one instead.

A manifest never holds a secret's value. Besides the fields declared with
:func:`~grafi.common.manifest.env_secret`, a secret is recognized by its name:
a field, header, variable or URL parameter called ``api_key``, ``clientSecret``,
``GITHUB_TOKEN``, ``Authorization``... (see :func:`is_secret_name`), and a
URL's password. Text that only refers to an environment variable, as
``"${GITHUB_TOKEN}"`` or ``"Bearer ${GITHUB_TOKEN}"``, holds no secret where it
is expanded, in an MCP configuration (see :func:`expand_env`); elsewhere it
would be sent as written, and is refused.
"""

import os
import re
from typing import Any
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
from urllib.parse import parse_qsl
from urllib.parse import urlsplit

from grafi.common.import_ref import is_import_path

__all__ = [
    "env_reference",
    "env_variables_in",
    "expand_env",
    "held_secret",
]

# Names that say they hold a secret: api_key, client_secret, password,
# access_token, GITHUB_TOKEN, Authorization, X-Api-Key...
_SECRET_NAME = re.compile(
    r"^auth$|(password|passwd)s?$"
    r"|(^|_)(api_?keys?|secrets?(_?keys?)?|(private|ssh|signing|access)_?keys?"
    r"|credentials?|authorization|cookies?|token)$",
    re.IGNORECASE,
)

# ... but not a tokenizer's special tokens.
_TOKENIZER_TOKEN = re.compile(r"(^|_)(eos|bos|pad|unk|sep|cls|mask)_token$", re.I)

# The keys of a JSON Schema whose own keys name properties or schemas, such as
# a parameter called pageToken, not settings.
_SCHEMA_NAMES = frozenset({"properties", "patternProperties", "$defs", "definitions"})

# Where a camelCase name's words meet, as in clientSecret and OpenAIApiKey.
_CAMEL_HUMP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# An environment variable's name, and a reference to one in text, "${VAR}".
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Text that only refers to an environment variable, after an auth scheme.
_REFERENCE_TEXT = re.compile(
    r"(?:(?:Bearer|Basic|Token|Digest|ApiKey|Api-Key|Key|OAuth|SSWS)\s+)?"
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}",
    re.IGNORECASE,
)


def is_secret_name(name: str) -> bool:
    """Whether ``name``, of a field, header or variable, says it holds a
    secret, such as ``api_key``, ``client_secret``, ``accessToken``,
    ``GITHUB_TOKEN``, ``Authorization`` or ``X-Api-Key``."""
    name = _CAMEL_HUMP.sub("_", name).replace("-", "_")
    return bool(_SECRET_NAME.search(name)) and not _TOKENIZER_TOKEN.search(name)


def is_env_reference(text: str) -> bool:
    """Whether ``text`` only refers to an environment variable, as
    ``"${GITHUB_TOKEN}"`` or ``"Bearer ${GITHUB_TOKEN}"`` does (an auth scheme
    and a reference), or names a way to authenticate rather than a secret, as
    MCP's ``"auth": "oauth"`` does."""
    return bool(_REFERENCE_TEXT.fullmatch(text.strip())) or text == "oauth"


def env_reference(value: Any) -> Optional[str]:
    """The variable ``value`` refers to, if it is ``{"env": "VAR"}``."""
    if isinstance(value, Mapping) and set(value) == {"env"}:
        if isinstance(value["env"], str) and _VARIABLE.fullmatch(value["env"]):
            return value["env"]
    return None


def env_variables_in(text: str) -> List[str]:
    """The environment variables ``text`` refers to, as ``${VAR}``."""
    return _REFERENCE.findall(text)


def expand_env(text: str, env: Mapping[str, str] = {}) -> str:
    """``text`` with each ``${VAR}`` replaced by the variable's value: the one
    ``env`` gives, else the environment's.

    Raises:
        ValueError: If a variable is not set, or empty.
    """

    def value(reference: "re.Match[str]") -> str:
        value = env.get(reference[1], os.getenv(reference[1]))
        if not value:
            raise ValueError(
                f"The environment variable {reference[1]} is referred to, "
                f"but {'empty' if value == '' else 'not set'}."
            )
        return value

    return _REFERENCE.sub(value, text)


def held_secret(name: str, value: Any, *, expands: bool = False) -> Optional[str]:
    """The name of the first secret ``value`` holds, itself or within it, else
    None: text under a name like a secret's, such as a header dict's
    ``Authorization``; or a URL holding a password or a secret parameter. All
    nested under a secret's name is under that name, but the properties a JSON
    Schema names are not settings. A reference to a class or function holds
    none. Nor does a reference to a variable where it is read: ``{"env":
    "VAR"}`` as a component's field, in its JSON, and text referring to one,
    ``"Bearer ${VAR}"``, where it ``expands``; elsewhere either would be sent
    as written."""
    if isinstance(value, str):
        referring = expands and is_env_reference(value)
        if value and is_secret_name(name) and not referring:
            return name
        return name if _url_secret(value, expands) else None
    if _import_reference(value):
        return None
    under_secret = is_secret_name(name)
    items: Iterable[Any] = ()
    if isinstance(value, Mapping) and name in _SCHEMA_NAMES and _schemas(value):
        items = (("", item) for item in value.values())
    elif isinstance(value, Mapping):
        component = is_import_path(str(value.get("class", "")))  # Its JSON.
        items = (
            (name if under_secret else str(key), item)
            for key, item in value.items()
            if not (component and (key == "class" or env_reference(item)))
        )
    elif isinstance(value, (list, tuple)):
        items = (  # [name, value] pairs, unless under a secret's name.
            item if _named_pair(item) and not under_secret else (name, item)
            for item in value
        )
    for key, item in items:
        held = held_secret(str(key), item, expands=expands)
        if held is not None:
            return held
    return None


def _schemas(value: Mapping[str, Any]) -> bool:
    """Whether ``value``'s values are JSON Schemas, as a schema's properties
    are: objects, or booleans."""
    return all(isinstance(item, (Mapping, bool)) for item in value.values())


def _import_reference(value: Any) -> bool:
    """Whether ``value`` refers to a class or function, ``{"ref": "module:name"}``."""
    return (
        isinstance(value, Mapping)
        and set(value) == {"ref"}
        and is_import_path(str(value["ref"]))
    )


def _named_pair(item: Any) -> bool:
    return (
        isinstance(item, (list, tuple))
        and len(item) == 2
        and all(isinstance(part, str) for part in item)
    )


def _url_secret(text: str, expands: bool) -> bool:
    """Whether ``text`` is a URL holding a password, or a parameter named like
    a secret, that is not a variable's reference where it ``expands``."""
    if "://" not in text:
        return False
    try:
        url = urlsplit(text)
        query = parse_qsl(url.query)
    except ValueError:
        return True  # Unreadable: it may hold one, so it is refused.
    if url.password and not (expands and is_env_reference(url.password)):
        return True
    return any(
        value and is_secret_name(name) and not (expands and is_env_reference(value))
        for name, value in query
    )
