"""Tests for secrets in components saved as data (grafi.common.manifest): a
secret field, declared with env_secret(), is saved as the environment variable
it comes from; a secret held anywhere else, by its name, is never saved; and a
manifest reads only the variables it is allowed.

Saving as JSON with ``model_dump`` raises pydantic's PydanticSerializationError,
holding the ManifestError's message, and ``to_manifest()`` raises the
ManifestError itself, from the component or any component or field within it.
The python-mode dump, ``model_dump()``, holds a secret read from a variable as
a reference to it, as JSON does: a dump is configuration.
"""

import json
import os
import re
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union

import pytest
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableRef
from grafi.common.exceptions import LLMToolException
from grafi.common.manifest import API_VERSION
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest import env_secret
from grafi.common.manifest import import_path
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from tests.common.manifest_fixtures import HELD_SECRETS
from tests.common.manifest_fixtures import OTHER_VAR
from tests.common.manifest_fixtures import SECRET_VAR
from tests.common.manifest_fixtures import UNHELD_SETTINGS
from tests.common.manifest_fixtures import Box
from tests.common.manifest_fixtures import Formatted
from tests.common.manifest_fixtures import Gadget
from tests.common.manifest_fixtures import Holder
from tests.common.manifest_fixtures import Keyed
from tests.common.manifest_fixtures import Widget
from tests.common.manifest_fixtures import raises_on_dump


class Leaky(Component):
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    password: Optional[str] = None
    max_tokens: int = 100


# --------------------------------------------------------------------------- #
# env_secret: a secret is saved as the environment variable it comes from
# --------------------------------------------------------------------------- #


def test_secret_is_saved_as_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")
    keyed = Keyed()

    assert keyed.api_key == "s3cret-value"  # Read from the variable.
    assert keyed.model_dump(mode="json")["api_key"] == {"env": SECRET_VAR}
    assert "s3cret-value" not in keyed.model_dump_json()
    assert "s3cret-value" not in json.dumps(keyed.to_manifest())
    # The python-mode dump holds the reference too, which loads in code.
    assert keyed.model_dump()["api_key"] == {"env": SECRET_VAR}
    assert Keyed.model_validate(keyed.model_dump()).api_key == "s3cret-value"


def test_secret_field_is_marked_outside_its_json_schema() -> None:
    schema = Keyed.model_json_schema()

    assert set(schema["properties"]) == {"api_key", "token", "name"}
    assert "grafi_env" not in json.dumps(schema)
    assert SECRET_VAR not in json.dumps(schema)


def test_secret_is_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")
    keyed = Keyed(token=None)

    assert "s3cret-value" not in repr(keyed)
    assert "api_key" not in repr(keyed)
    assert "token" not in repr(keyed)
    assert "name='keyed'" in repr(keyed)


def test_secret_set_to_its_variables_value_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")

    keyed = Keyed(api_key="s3cret-value")

    assert keyed.model_dump(mode="json")["api_key"] == {"env": SECRET_VAR}


def test_secret_set_to_another_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")
    keyed = Keyed(api_key="another-value")

    with raises_on_dump(ManifestError, f"Keyed.api_key .*{SECRET_VAR}"):
        keyed.model_dump(mode="json")
    with pytest.raises(ManifestError, match="never holds a secret"):
        keyed.to_manifest()
    assert keyed.model_dump()["api_key"] == "another-value"  # Not saved: a value.


def test_secret_without_a_value_is_saved_as_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SECRET_VAR, raising=False)
    keyed = Keyed()

    assert keyed.api_key is None
    assert keyed.model_dump(mode="json")["api_key"] == {"env": SECRET_VAR}


def test_secret_without_a_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SECRET_VAR, raising=False)

    assert Keyed().token is None
    assert Keyed().model_dump(mode="json")["token"] is None
    with raises_on_dump(ManifestError, "Keyed.token .* an environment variable"):
        Keyed(token="t0ken-value").model_dump(mode="json")
    with pytest.raises(ManifestError, match="Keyed.token"):
        Keyed(token="t0ken-value").to_manifest()


@pytest.mark.parametrize("field", ["api_key", "token"])
def test_secret_loaded_from_another_variable_is_saved_as_it(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv(SECRET_VAR, "default-value")
    monkeypatch.setenv(OTHER_VAR, "other-value")

    spec = {"class": import_path(Keyed), field: {"env": OTHER_VAR}}
    keyed = Keyed.from_manifest(spec, allow_env=[OTHER_VAR])  # A component's JSON.

    assert getattr(keyed, field) == "other-value"
    assert keyed.secret_variable(field) == OTHER_VAR
    data = keyed.model_dump(mode="json")
    assert data[field] == {"env": OTHER_VAR}
    again = Component.from_manifest(json.loads(json.dumps(data)), allow_env=[OTHER_VAR])
    assert type(again) is Keyed
    assert getattr(again, field) == "other-value"
    assert again.model_dump(mode="json")[field] == {"env": OTHER_VAR}


def _keyed_manifest(**fields: Any) -> Dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": "Keyed",
        "spec": {"class": import_path(Keyed), **fields},
    }


def test_a_manifest_reads_only_the_variables_it_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """from_manifest() lets a secret read its own variable, or one it is told
    of, so a manifest cannot read any other secret."""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-aws-secret")
    monkeypatch.setenv(SECRET_VAR, "own-value")
    other = _keyed_manifest(api_key={"env": "AWS_SECRET_ACCESS_KEY"})

    with pytest.raises(ManifestError, match="AWS_SECRET_ACCESS_KEY"):
        Keyed.from_manifest(other)

    allowed = Keyed.from_manifest(other, allow_env=["AWS_SECRET_ACCESS_KEY"])
    assert allowed.api_key == "fake-aws-secret"
    own = Keyed.from_manifest(_keyed_manifest(api_key={"env": SECRET_VAR}))
    assert own.api_key == "own-value"


def test_a_secret_without_a_variable_reads_only_one_it_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OTHER_VAR, "other-value")
    manifest = _keyed_manifest(token={"env": OTHER_VAR})

    with pytest.raises(
        ManifestError, match=rf"{OTHER_VAR}.*allow_env=\['{OTHER_VAR}'\]"
    ):
        Keyed.from_manifest(manifest)
    assert Keyed.from_manifest(manifest, allow_env=[OTHER_VAR]).token == "other-value"


@pytest.mark.parametrize("field", ["api_key", "token"])
def test_a_manifest_never_gives_a_secret_as_a_value(field: str) -> None:
    manifest = _keyed_manifest(**{field: "sk-literal"})

    with pytest.raises(ManifestError, match=f"Keyed.{field} .*never holds a secret"):
        Keyed.from_manifest(manifest)


def test_a_manifest_never_gives_null_for_a_secret_read_from_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saving writes a secret with a variable of its own as a reference, never
    as null, which would replace the variable's value."""
    monkeypatch.setenv(SECRET_VAR, "own-value")

    with pytest.raises(ManifestError, match="Keyed.api_key is given a value"):
        Keyed.from_manifest(_keyed_manifest(api_key=None))
    # One without a variable of its own is saved as null.
    assert Keyed.from_manifest(_keyed_manifest(token=None)).token is None
    # Loaded in code, null is its value.
    assert Keyed.model_validate({"api_key": None}).api_key is None


@pytest.mark.parametrize(
    "allow_env",
    [OTHER_VAR, {OTHER_VAR: "value"}, os.environ],
    ids=["str", "dict", "os.environ"],
)
def test_the_variables_a_manifest_may_read_are_a_list_of_names(allow_env: Any) -> None:
    """Not a mapping: iterating one would allow its keys, all of os.environ's."""
    with pytest.raises(TypeError, match="allow_env is the names of the variables"):
        Keyed.from_manifest(_keyed_manifest(), allow_env=allow_env)


@pytest.mark.parametrize("alias", ["alias", "serialization_alias", "validation_alias"])
def test_a_secret_field_takes_no_alias(alias: str) -> None:
    with pytest.raises(TypeError, match="takes no alias"):
        env_secret(SECRET_VAR, **{alias: "key"})


def test_the_variable_a_secret_field_is_read_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A component's secret_variable(field) is the variable the field reads:
    the one a manifest named for it, else its own."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    keyed = Keyed()

    assert keyed.secret_variable("api_key") == SECRET_VAR
    assert keyed.secret_variable("token") is None  # Without one of its own.
    assert keyed.secret_variable("name") is None  # Not a secret.
    assert OpenAITool().secret_variable("api_key") == "OPENAI_API_KEY"
    renamed = Keyed.from_manifest(
        {
            "class": import_path(Keyed),
            "api_key": {"env": OTHER_VAR},
            "token": {"env": OTHER_VAR},
        },
        allow_env=[OTHER_VAR],
    )
    assert renamed.secret_variable("api_key") == OTHER_VAR
    assert renamed.secret_variable("token") == OTHER_VAR
    assert Keyed().secret_variable("api_key") == SECRET_VAR  # Each its own.


class Sized(Component):
    api_key: Optional[str] = env_secret(SECRET_VAR)
    size: int


def test_a_validation_error_never_shows_the_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A secret read from its variable is in the data validated, which an
    error would otherwise show."""
    monkeypatch.setenv(SECRET_VAR, "sk-read-from-the-environment")

    with pytest.raises(ValidationError, match="size") as raised:
        Sized.model_validate({"api_key": {"env": SECRET_VAR}})

    assert "sk-read-from-the-environment" not in str(raised.value)


def test_a_nested_component_never_gives_a_secret_as_a_value() -> None:
    keyed = {"class": import_path(Keyed), "api_key": "sk-literal"}
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "Box",
        "spec": {"class": import_path(Box), "keyed": keyed},
    }

    # Refused by the nested component's own check, as it is loaded.
    match = "Keyed.api_key is given a value, and a manifest never holds a secret"
    with pytest.raises(ManifestError, match=match):
        Box.from_manifest(manifest)


def test_loading_in_code_applies_no_manifest_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_validate() loads what code gives it, trusted as code is: only
    from_manifest() applies the rules for a manifest."""
    keyed = Keyed.model_validate({"api_key": "sk-literal", "token": "t0ken"})
    holder = Holder.model_validate({"item": {"name": "no class"}})

    assert (keyed.api_key, keyed.token) == ("sk-literal", "t0ken")
    assert type(holder.item) is Gadget


@pytest.mark.parametrize("build", ["model_validate", "model_validate_json", "init"])
@pytest.mark.parametrize("named", [True, False], ids=["with class", "without"])
def test_code_chooses_a_secrets_variable_and_a_manifest_needs_it_allowed(
    monkeypatch: pytest.MonkeyPatch, build: str, named: bool
) -> None:
    """model_validate and the constructors trust what they are given, as code:
    a secret reads the variable named, and is saved as it. Data you did not
    write loads with from_manifest, which reads another only if allowed."""
    monkeypatch.setenv(OTHER_VAR, "other-value")
    data: Dict[str, Any] = {"api_key": {"env": OTHER_VAR}}
    if named:
        data["class"] = import_path(Keyed)
    load = {
        "model_validate": lambda: Keyed.model_validate(data),
        "model_validate_json": lambda: Keyed.model_validate_json(json.dumps(data)),
        "init": lambda: Keyed(**data),
    }[build]

    keyed = load()

    assert keyed.api_key == "other-value"
    assert keyed.to_manifest()["spec"]["api_key"] == {"env": OTHER_VAR}
    spec = {**data, "class": import_path(Keyed)}
    with pytest.raises(ManifestError, match=f"allow_env=\\['{OTHER_VAR}'\\]"):
        Keyed.from_manifest(spec)
    assert Keyed.from_manifest(spec, allow_env=[OTHER_VAR]).api_key == "other-value"


@pytest.mark.parametrize(
    "spec",
    [
        {"class": import_path(Holder), "item": {"name": "no class"}},
        {"class": import_path(Box), "gadget": {"size": 2}},
        {"class": import_path(Box), "gadgets": [{"class": import_path(Widget)}, {}]},
    ],
    ids=["field", "optional field", "list item"],
)
def test_every_component_in_a_manifest_names_its_class(spec: Dict[str, Any]) -> None:
    manifest = {
        "apiVersion": API_VERSION,
        "kind": spec["class"].rpartition(":")[2],
        "spec": spec,
    }

    with pytest.raises(ManifestError, match="names its class.*this Gadget does"):
        Component.from_manifest(manifest)
    assert Component.model_validate(spec)  # Loaded in code, it need not.


def test_secret_loaded_from_an_unset_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OTHER_VAR, raising=False)

    keyed = Keyed.from_manifest(
        {"class": import_path(Keyed), "api_key": {"env": OTHER_VAR}},
        allow_env=[OTHER_VAR],
    )

    assert keyed.api_key is None
    assert keyed.model_dump(mode="json")["api_key"] == {"env": OTHER_VAR}


def test_grafi_secrets_are_saved_as_their_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    tool = OpenAITool()

    assert tool.api_key == "fake-openai-key"
    assert tool.model_dump(mode="json")["api_key"] == {"env": "OPENAI_API_KEY"}
    with raises_on_dump(ManifestError, "OPENAI_API_KEY"):
        OpenAITool(api_key="a-literal-key").model_dump(mode="json")
    with pytest.raises(ManifestError, match="OpenAITool.api_key"):
        OpenAITool(api_key="a-literal-key").to_manifest()


def test_nested_secret_set_to_another_value_raises_from_to_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")
    box = Box(keyed=Keyed(api_key="another-value"))

    with pytest.raises(ManifestError, match="Keyed.api_key"):
        box.to_manifest()
    with raises_on_dump(ManifestError, "Keyed.api_key"):
        box.model_dump(mode="json")


def test_a_class_with_secrets_takes_no_alias_generator() -> None:
    """Secrets are saved and loaded by their fields' names."""
    from pydantic.alias_generators import to_camel

    with pytest.raises(TypeError, match="takes no alias_generator"):

        class Aliased(Component):
            model_config = ConfigDict(alias_generator=to_camel)
            upstream_dsn: Optional[str] = env_secret(SECRET_VAR)


# --------------------------------------------------------------------------- #
# Secrets held by their names, anywhere in a component's settings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["api_key", "access_token", "password"])
def test_undeclared_secret_field_with_a_value_cannot_be_saved(field: str) -> None:
    leaky = Leaky(max_tokens=7, **{field: "leaked-value"})

    with raises_on_dump(ManifestError, f"Leaky.{field} holds a secret, at '{field}'"):
        leaky.model_dump(mode="json")
    with pytest.raises(ManifestError, match=f"Leaky.{field} .*env_secret"):
        leaky.to_manifest()
    with pytest.raises(PydanticSerializationError, match="never holds one"):
        leaky.model_dump_json()
    assert leaky.model_dump()[field] == "leaked-value"  # Not saved: a value.


@pytest.mark.parametrize("value", [None, ""])
def test_undeclared_secret_fields_without_a_value_are_saved(value: Any) -> None:
    leaky = Leaky(api_key=value, access_token=value, password=value, max_tokens=7)

    assert leaky.model_dump(mode="json") == {
        "class": import_path(Leaky),
        "api_key": value,
        "access_token": value,
        "password": value,
        "max_tokens": 7,
    }


class Configured(Component):
    """Fields holding settings, which may hold secrets within them."""

    params: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)


@pytest.mark.parametrize("field, value, held", HELD_SECRETS)
def test_secret_held_at_any_depth_cannot_be_saved(
    field: str, value: Dict[str, Any], held: str
) -> None:
    configured = Configured(**{field: value})
    match = re.escape(f"Configured.{field} holds a secret, at {held!r}")

    with raises_on_dump(ManifestError, match):
        configured.model_dump(mode="json")
    with pytest.raises(ManifestError, match=match):
        configured.to_manifest()
    assert configured.model_dump()[field] == value  # Not saved: its values.


@pytest.mark.parametrize("field, value, held", HELD_SECRETS)
def test_a_manifest_never_holds_a_secret_at_any_depth(
    field: str, value: Dict[str, Any], held: str
) -> None:
    spec = {"class": import_path(Configured), field: value}
    manifest = {"apiVersion": API_VERSION, "kind": "Configured", "spec": spec}
    match = f"Configured.{field} holds a secret, at {held!r}, and a manifest never"

    with pytest.raises(ManifestError, match=re.escape(match)):
        Component.from_manifest(manifest)
    # Loaded in code, it is a value, as code is trusted.
    assert getattr(Component.model_validate(spec), field) == value


@pytest.mark.parametrize("params", UNHELD_SETTINGS)
def test_settings_without_a_secret_value_are_saved(params: Dict[str, Any]) -> None:
    configured = Configured(params=params)

    data = configured.model_dump(mode="json")

    assert data["params"] == params
    assert Configured.model_validate(json.loads(json.dumps(data))) == configured
    manifest = json.loads(json.dumps(configured.to_manifest()))
    assert Configured.from_manifest(manifest) == configured


def test_an_env_reference_names_a_variable() -> None:
    """Text that is no variable's name is not a reference: it is a value."""
    with pytest.raises(ManifestError, match="holds a secret"):
        Formatted(params={"api_key": {"env": "sk-FAKE-1"}}).to_manifest()


def test_a_class_key_hides_no_secret() -> None:
    """Only a component's class, an import path, is skipped."""
    with pytest.raises(ManifestError, match="holds a secret"):
        Formatted(params={"api_key": {"class": "sk-FAKE-1"}}).to_manifest()


def test_grafi_tool_settings_holding_a_secret_cannot_be_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    headers = {"extra_headers": {"Authorization": "Bearer sk-literal"}}

    with pytest.raises(ManifestError, match="OpenAITool.chat_params holds"):
        OpenAITool(chat_params=headers).to_manifest()
    with pytest.raises(ManifestError, match="OpenRouterTool.extra_headers holds"):
        OpenRouterTool(extra_headers={"X-Api-Key": "k"}).to_manifest()
    # Never expanded there: it would be sent as it is.
    referenced = {"extra_headers": {"Authorization": "Bearer ${OPENAI_API_KEY}"}}
    with pytest.raises(ManifestError, match="only an MCP configuration expands"):
        OpenAITool(chat_params=referenced).to_manifest()


def test_a_refusal_gives_the_advice_that_fits() -> None:
    """An assistant's build parameter may be left unsaved; "${VAR}" is
    expanded by MCP alone; a tool's key reads its variable."""
    from grafi.assistants.assistant import Assistant

    class Built(Assistant):
        token: str = "t0ken-value"  # A build parameter, saved by mistake.

    with pytest.raises(ManifestError, match="declare it exclude=True") as raised:
        Built().to_manifest()
    assert "${VAR}" not in str(raised.value)
    with pytest.raises(
        ManifestError, match="only an MCP configuration expands"
    ) as raised:
        Formatted(params={"api_key": "${KEY}"}).to_manifest()
    assert "exclude=True" not in str(raised.value)
    with pytest.raises(ManifestError, match='as {"env": "VAR"}') as raised:
        Keyed(api_key="sk-literal").to_manifest()
    assert "exclude=True" not in str(raised.value)


class Region(CallableComponent):
    """A function configured with a region."""

    region: str = "us-east-1"

    def __call__(self) -> str:
        return self.region


class Signer(Component):
    """Holds a function under a name like a secret's."""

    credentials: CallableRef = Field(default_factory=Region)


class Loose(Component):
    """A field holding components or text: it is checked."""

    items: Dict[str, Union[Gadget, str]] = Field(default_factory=dict)


def test_a_component_in_a_function_field_checks_its_own_secrets() -> None:
    signer = Signer()

    assert Signer.from_manifest(signer.to_manifest()) == signer


def test_a_field_is_left_to_its_values_only_if_all_check_themselves() -> None:
    with pytest.raises(ManifestError, match="Loose.items holds a secret"):
        Loose(items={"api_key": "sk-live-123"}).to_manifest()


def test_a_key_read_from_its_variable_is_kept_and_saved_as_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The variable set for another user since, or unset, does not change the
    key a tool was made with; it still saves as its variable."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-alice")
    alices = OpenAITool()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bob")
    bobs = OpenAITool()

    assert (alices.sdk_api_key(), bobs.sdk_api_key()) == ("sk-alice", "sk-bob")
    assert alices.to_manifest()["spec"]["api_key"] == {"env": "OPENAI_API_KEY"}
    monkeypatch.delenv("OPENAI_API_KEY")
    assert alices.sdk_api_key() == "sk-alice"


def test_an_empty_key_reads_its_variable_when_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As os.getenv("OPENAI_API_KEY", "") gives it, before the variable is set."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tool = OpenAITool(api_key="")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-later")

    assert tool.sdk_api_key() == "sk-later"
    assert tool.to_manifest()["spec"]["api_key"] == {"env": "OPENAI_API_KEY"}


def test_a_reference_given_to_a_copy_is_refused_when_used() -> None:
    tool = OpenAITool(api_key="sk-given")
    copied = tool.model_copy(update={"api_key": {"env": "OTHER_KEY"}})

    with pytest.raises(LLMToolException, match="holds a dict, not a key"):
        copied.sdk_api_key()


@pytest.mark.parametrize("tenant_key", [None, "sk-tenant"], ids=["unset", "set"])
def test_a_python_dump_keeps_a_tenants_variable(
    monkeypatch: pytest.MonkeyPatch, tenant_key: Optional[str]
) -> None:
    """Loading the dump reads the tenant's variable, never the tool's own."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default-account")
    if tenant_key is None:
        monkeypatch.delenv("TENANT_KEY", raising=False)
    else:
        monkeypatch.setenv("TENANT_KEY", tenant_key)
    tool = OpenAITool.model_validate({"api_key": {"env": "TENANT_KEY"}})

    copy = OpenAITool.model_validate(tool.model_dump())

    assert copy.secret_variable("api_key") == "TENANT_KEY"
    assert copy.to_manifest()["spec"]["api_key"] == {"env": "TENANT_KEY"}


def test_secret_value_reads_only_secret_fields() -> None:
    with pytest.raises(ValueError, match="OpenAITool.model is not a secret field"):
        OpenAITool().secret_value("model")


def test_every_copy_keeps_the_key_though_the_variable_changed_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set for another user's session since: a copy, and a component given
    the key passed on, uses this tool's key, never the variable's new one."""
    import copy

    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-a")
    tool = OpenAITool()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-b")

    copies = [
        tool.model_copy(),
        copy.deepcopy(tool),
        OpenAITool.builder().api_key(tool.secret_reference("api_key")).build(),
    ]

    assert [c.sdk_api_key() for c in copies] == ["sk-user-a"] * 3
    assert tool.to_manifest()["spec"]["api_key"] == {"env": "OPENAI_API_KEY"}


def test_a_dump_is_configuration_read_again_when_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As from_manifest reads it: a python dump refers to the variable, never
    holding the key, and loading it reads the variable as it is then."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-a")
    tool = OpenAITool()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user-b")

    dump = tool.model_dump()

    assert dump["api_key"] == {"env": "OPENAI_API_KEY"}
    assert OpenAITool.model_validate(dump).sdk_api_key() == "sk-user-b"


def test_a_secret_declared_again_without_env_secret_is_refused() -> None:
    """As 0.0.36's tools declared their keys: it would be held, and sent, as
    plain text, and fail only at its first call or save."""
    from pydantic import Field as PlainField

    with pytest.raises(TypeError, match="Plain.api_key is a secret, as OpenAITool"):

        class Plain(OpenAITool):
            api_key: Optional[str] = PlainField(default=None)


class NoVariable(Component):
    """A secret with no variable of its own."""

    token: Optional[str] = env_secret()


def test_an_empty_secret_without_a_variable_is_saved_as_none() -> None:
    """As secret_value takes it: none."""
    assert NoVariable(token="").to_manifest()["spec"]["token"] is None


def test_a_secret_field_holds_text() -> None:
    """A mapping, or SecretStr, could not be read from a variable, nor saved
    as one: refused when the class is defined."""
    with pytest.raises(TypeError, match="DictCredentials.credentials is a secret"):

        class DictCredentials(Component):
            credentials: Optional[Dict[str, str]] = env_secret("GRAFI_TEST_CREDS")


@pytest.mark.parametrize("dump", [{"exclude_none": True}, {"exclude_defaults": True}])
@pytest.mark.parametrize("mode", ["python", "json"])
def test_a_dump_leaving_out_none_keeps_a_tenants_variable(
    monkeypatch: pytest.MonkeyPatch, dump: Dict[str, Any], mode: str
) -> None:
    """Unset, the tenant's key is none: the dump still names its variable, so
    loading it never reads the tool's own, another account's."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default-account")
    monkeypatch.delenv("TENANT_KEY", raising=False)
    tool = OpenAITool.model_validate({"api_key": {"env": "TENANT_KEY"}})

    dumped = tool.model_dump(mode=mode, **dump)

    assert dumped["api_key"] == {"env": "TENANT_KEY"}
    assert OpenAITool.model_validate(dumped).secret_variable("api_key") == "TENANT_KEY"


def test_a_dump_leaving_a_tenants_key_out_on_purpose_keeps_it_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TENANT_KEY", raising=False)
    tool = OpenAITool.model_validate({"api_key": {"env": "TENANT_KEY"}})

    dumped = tool.model_dump(exclude_none=True, exclude={"api_key"})

    assert "api_key" not in dumped


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
@pytest.mark.parametrize("variable", ["OPENAI_API_KEY", "TENANT_KEY"])
def test_a_reference_given_after_the_tool_was_made_is_refused(variable: str) -> None:
    """Its own variable's or another's alike: a reference is read when the
    component is made. Assigning one is refused; a copy given one is refused
    when saved."""
    tool = OpenAITool()

    with pytest.raises(TypeError, match="give a reference"):
        tool.api_key = {"env": variable}  # type: ignore[assignment]
    copied = tool.model_copy(update={"api_key": {"env": variable}})
    with pytest.raises(ManifestError, match="given after it was made"):
        copied.to_manifest()


def test_a_secret_with_constraints_is_refused() -> None:
    """A constraint would apply to a key loaded, not to one read by default,
    nor when used, so what is saved could not load, or would differ: refused
    in a union, on the type, and on the field alike."""
    from typing import Annotated

    from pydantic import StringConstraints

    with pytest.raises(TypeError, match="with no constraint"):

        class InUnion(Component):
            key: Optional[Annotated[str, StringConstraints(to_lower=True)]] = (
                env_secret("GRAFI_TEST_CONSTRAINED")
            )

    with pytest.raises(TypeError, match="with no constraint"):

        class OnType(Component):
            key: Annotated[str, StringConstraints(min_length=20)] = env_secret(
                "GRAFI_TEST_CONSTRAINED"
            )

    with pytest.raises(TypeError, match="with no constraint"):

        class OnField(Component):
            key: Optional[str] = env_secret("GRAFI_TEST_CONSTRAINED", min_length=20)
