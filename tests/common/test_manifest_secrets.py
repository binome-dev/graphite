"""Tests for secrets in components saved as data (grafi.common.manifest): a
secret field, declared with env_secret(), is saved as the environment variable
it comes from; a secret held anywhere else, by its name, is never saved; and a
manifest reads only the variables it is allowed.

Saving as JSON with ``model_dump`` raises pydantic's PydanticSerializationError,
holding the ManifestError's message, and ``to_manifest()`` raises the
ManifestError itself, from the component or any component or field within it.
The python-mode dump, ``model_dump()``, holds the secrets' values.
"""

import json
import re
from typing import Any
from typing import Dict
from typing import Optional

import pytest
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

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
    # The python-mode dump holds its value, as pydantic's does.
    assert keyed.model_dump()["api_key"] == "s3cret-value"


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

    keyed = Keyed.model_validate({field: {"env": OTHER_VAR}})

    assert getattr(keyed, field) == "other-value"
    assert keyed.secret_variable(field) == OTHER_VAR
    data = keyed.model_dump(mode="json")
    assert data[field] == {"env": OTHER_VAR}
    again = Component.model_validate(json.loads(json.dumps(data)))
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

    allowed = Keyed.from_manifest(other, env=["AWS_SECRET_ACCESS_KEY"])
    assert allowed.api_key == "fake-aws-secret"
    own = Keyed.from_manifest(_keyed_manifest(api_key={"env": SECRET_VAR}))
    assert own.api_key == "own-value"


def test_a_secret_without_a_variable_reads_only_one_it_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OTHER_VAR, "other-value")
    manifest = _keyed_manifest(token={"env": OTHER_VAR})

    with pytest.raises(ManifestError, match=rf"{OTHER_VAR}.*env=\['{OTHER_VAR}'\]"):
        Keyed.from_manifest(manifest)
    assert Keyed.from_manifest(manifest, env=[OTHER_VAR]).token == "other-value"


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


def test_the_variables_a_manifest_may_read_are_a_list_of_names() -> None:
    with pytest.raises(TypeError, match=rf"env=\['{OTHER_VAR}'\]"):
        Keyed.from_manifest(_keyed_manifest(), env=OTHER_VAR)


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
    renamed = Keyed.model_validate(
        {"api_key": {"env": OTHER_VAR}, "token": {"env": OTHER_VAR}}
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

    # Refused by the component holding it, before the nested one is loaded.
    match = "Box.keyed holds a secret, at 'api_key', and a manifest never holds one"
    with pytest.raises(ManifestError, match=match):
        Box.from_manifest(manifest)


def test_loading_in_code_applies_no_manifest_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_validate() loads what code gives it, trusted as code is: only
    from_manifest() applies the rules for a manifest."""
    monkeypatch.setenv(OTHER_VAR, "other-value")

    keyed = Keyed.model_validate({"api_key": "sk-literal", "token": {"env": OTHER_VAR}})
    holder = Holder.model_validate({"item": {"name": "no class"}})

    assert (keyed.api_key, keyed.token) == ("sk-literal", "other-value")
    assert type(holder.item) is Gadget


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

    with pytest.raises(ManifestError, match="names its class.*this Gadget does not"):
        Component.from_manifest(manifest)
    assert Component.model_validate(spec)  # Loaded in code, it need not.


def test_secret_loaded_from_an_unset_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OTHER_VAR, raising=False)

    keyed = Keyed.model_validate({"api_key": {"env": OTHER_VAR}})

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
    referenced = {"extra_headers": {"Authorization": "Bearer ${OPENAI_API_KEY}"}}
    saved = OpenAITool(chat_params=referenced).to_manifest()
    assert saved["spec"]["chat_params"] == referenced
