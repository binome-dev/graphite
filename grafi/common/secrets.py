"""What holds a secret, by its name, and what refers to one instead.

A manifest never holds a secret's value. Besides the fields declared with
:func:`~grafi.common.manifest.env_secret`, a secret is recognized by its name:
a field, header, variable or URL parameter called ``api_key``, ``clientSecret``,
``GITHUB_TOKEN``, ``Authorization``... (see :func:`is_secret_name`), and a
URL's password. Text that only refers to an environment variable, as
``"${GITHUB_TOKEN}"`` or ``"Bearer ${GITHUB_TOKEN}"``, holds no secret, and is
expanded where it is used (see :func:`expand_env`).
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
    "is_env_reference",
    "is_secret_name",
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


def expand_env(text: str) -> str:
    """``text`` with each ``${VAR}`` replaced by the variable's value.

    Raises:
        ValueError: If a variable is not set.
    """

    def value(reference: "re.Match[str]") -> str:
        value = os.getenv(reference[1])
        if value is None:
            raise ValueError(
                f"The environment variable {reference[1]} is referred to, "
                "but not set."
            )
        return value

    return _REFERENCE.sub(value, text)


def held_secret(name: str, value: Any) -> Optional[str]:
    """The name of a secret ``value`` holds, itself or within it: text under a
    name like a secret's, such as a header dict's ``Authorization``, unless it
    only refers to a variable; or a URL's password or secret parameter. All
    within a value held under a secret's name is under that name."""
    if isinstance(value, str):
        if value and is_secret_name(name) and not is_env_reference(value):
            return name
        return name if _url_secret(value) else None
    if env_reference(value) is not None:
        return None
    under_secret = is_secret_name(name)
    items: Iterable[Any] = ()
    if isinstance(value, Mapping):
        items = (
            (name if under_secret else str(key), item)
            for key, item in value.items()
            if not (key == "class" and is_import_path(str(item)))  # A component's.
        )
    elif isinstance(value, (list, tuple)):
        items = (  # [name, value] pairs, unless under a secret's name.
            item if _named_pair(item) and not under_secret else (name, item)
            for item in value
        )
    for key, item in items:
        held = held_secret(str(key), item)
        if held is not None:
            return held
    return None


def _named_pair(item: Any) -> bool:
    return (
        isinstance(item, (list, tuple))
        and len(item) == 2
        and all(isinstance(part, str) for part in item)
    )


def _url_secret(text: str) -> bool:
    """Whether ``text`` is a URL holding a password, or a parameter named like
    a secret, that is not a variable's reference."""
    if "://" not in text:
        return False
    try:
        url = urlsplit(text)
        query = parse_qsl(url.query)
    except ValueError:
        return True  # Unreadable: it may hold one, so it is refused.
    if url.password and not is_env_reference(url.password):
        return True
    return any(
        value and is_secret_name(name) and not is_env_reference(value)
        for name, value in query
    )
