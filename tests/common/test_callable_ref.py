"""Tests for pickle-free callable (de)serialization (grafi.common.callable_ref)."""

import functools
from typing import Any
from typing import Optional

import pytest
from pydantic import BaseModel
from pydantic import ValidationError

from grafi.common.callable_component import CallableComponent
from grafi.common.callable_ref import CallableRef
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.import_ref import UntrustedImportError
from grafi.common.import_ref import trust_modules  # noqa: F401 - named by a test.
from grafi.common.manifest import API_VERSION
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest import env_secret
from grafi.nodes.conditions import always_true
from grafi.topics.topic_base import TopicRef
from grafi.topics.topic_impl.topic import Topic

SECRET_VAR = "GRAFI_TEST_CALLABLE_REF_SECRET"


def module_level_function(x: int) -> int:
    """A stable, importable callable -> serializes as a reference."""
    return x + 1


class Adder(CallableComponent):
    """A configurable callable -> serializes as a component, with its fields."""

    amount: int

    def __call__(self, x: int) -> int:
        return x + self.amount


class Signer(CallableComponent):
    """A configurable callable holding a secret."""

    key: Optional[str] = env_secret(SECRET_VAR)

    def __call__(self, text: str) -> str:
        return f"{text}:{self.key}"


class ToTopic(CallableComponent):
    """A configurable callable naming a topic, which loads from its name."""

    topic: TopicRef

    def __call__(self, name: str) -> bool:
        return name == self.topic.name


class Hooked(Component):
    fn: CallableRef


# --- reference form -------------------------------------------------------


def test_module_level_function_serializes_as_reference():
    assert serialize_callable(module_level_function) == {
        "ref": f"{__name__}:module_level_function"
    }


def test_reference_roundtrips_to_same_object():
    restored = deserialize_callable(serialize_callable(module_level_function))
    assert restored is module_level_function
    assert restored(41) == 42


# --- component form -------------------------------------------------------


def test_component_serializes_as_a_component():
    assert serialize_callable(Adder(amount=5)) == {
        "class": f"{__name__}:Adder",
        "amount": 5,
    }
    assert serialize_callable(Adder(amount=5)) == Adder(amount=5).model_dump(
        mode="json"
    )


def test_component_roundtrips():
    restored = deserialize_callable(serialize_callable(Adder(amount=5)))
    assert isinstance(restored, Adder)
    assert restored(10) == 15


def test_component_saved_before_grafi_v2_loads():
    restored = deserialize_callable(
        {"component": f"{__name__}:Adder", "config": {"amount": 5}}
    )
    assert isinstance(restored, Adder)
    assert restored(10) == 15


@pytest.mark.parametrize(
    "value",
    [
        {"component": f"{__name__}:module_level_function"},
        {"class": f"{__name__}:module_level_function"},
        {"class": f"{__name__}:Hooked", "fn": {"ref": f"{__name__}:Adder"}},
    ],
    ids=["legacy function", "function", "component not callable"],
)
def test_component_naming_what_is_not_a_callable_component_raises(value):
    with pytest.raises(ManifestError, match="is not a subclass of CallableComponent"):
        deserialize_callable(value)


def test_component_with_an_unknown_field_raises():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        deserialize_callable({"class": f"{__name__}:Adder", "amount": 5, "x": 1})


def test_component_field_round_trips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(SECRET_VAR, "s3cret")
    hooked = Hooked(fn=Signer())

    data = hooked.model_dump(mode="json")

    assert data["fn"] == {"class": f"{__name__}:Signer", "key": {"env": SECRET_VAR}}
    restored = Hooked.model_validate(data)
    assert isinstance(restored.fn, Signer)
    assert restored.fn("text") == "text:s3cret"


def test_component_secret_set_to_a_value_cannot_be_saved(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(SECRET_VAR, "s3cret")

    with pytest.raises(ManifestError, match=f"Signer.key .*{SECRET_VAR}"):
        Hooked(fn=Signer(key="another")).to_manifest()


def test_component_in_a_manifest_follows_its_rules(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRAFI_TEST_OTHER_SECRET", "other")

    def manifest(fn: Any) -> dict:
        spec = {"class": f"{__name__}:Hooked", "fn": fn}
        return {"apiVersion": API_VERSION, "kind": "Hooked", "spec": spec}

    signer = {"class": f"{__name__}:Signer"}
    with pytest.raises(ManifestError, match="never holds a secret"):
        Hooked.from_manifest(manifest({**signer, "key": "literal"}))
    other = manifest({**signer, "key": {"env": "GRAFI_TEST_OTHER_SECRET"}})
    with pytest.raises(ManifestError, match="GRAFI_TEST_OTHER_SECRET"):
        Hooked.from_manifest(other)
    assert Hooked.from_manifest(other, env=["GRAFI_TEST_OTHER_SECRET"]).fn.key == (
        "other"
    )


# --- no pickle: hard errors -----------------------------------------------


def test_lambda_cannot_be_serialized():
    with pytest.raises(CallableSerializationError, match="without pickle"):
        serialize_callable(lambda x: x > 0)


def test_closure_cannot_be_serialized():
    def make_adder(n):
        def adder(x):
            return x + n

        return adder

    with pytest.raises(CallableSerializationError, match="without pickle"):
        serialize_callable(make_adder(10))


def test_an_error_names_a_callable_without_showing_what_it_holds():
    """A partial's repr shows the arguments bound to it, such as a key."""
    bound = functools.partial(module_level_function, "sk-bound-secret")

    with pytest.raises(CallableSerializationError) as raised:
        serialize_callable(bound)

    assert "sk-bound-secret" not in str(raised.value)
    assert "Cannot serialize callable partial without pickle" in str(raised.value)
    with pytest.raises(CallableSerializationError, match="callable test_.*<locals>"):
        serialize_callable(lambda x: x)


def test_legacy_base64_string_is_rejected():
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        deserialize_callable("gASVbase64blob")


def test_legacy_base64_dict_is_rejected():
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        deserialize_callable({"base64": "blob", "code": "lambda _: True"})


def test_malformed_reference_raises():
    with pytest.raises(CallableSerializationError, match="Malformed import reference"):
        deserialize_callable({"ref": "no_separator_here"})


class Inert(BaseModel):
    """Defined here, so a reference to an instance names this module's own."""


NOT_CALLABLE = Inert()


def test_reference_to_a_value_raises():
    """A reference reaches a class or a function, never a value."""
    with pytest.raises(UntrustedImportError, match="reaches 'Inert'"):
        deserialize_callable({"ref": f"{__name__}:NOT_CALLABLE"})


def test_dict_without_known_keys_raises():
    with pytest.raises(CallableSerializationError, match="ref.*CallableComponent"):
        deserialize_callable({"unexpected": "value"})


def test_reference_with_other_keys_raises():
    with pytest.raises(CallableSerializationError, match="Cannot load a callable"):
        deserialize_callable({"ref": f"{__name__}:module_level_function", "x": 1})


@pytest.mark.parametrize(
    "value", ["grafi.nodes.conditions:always_true", f"{__name__}:module_level_function"]
)
def test_bare_import_path_raises_naming_ref(value: str):
    with pytest.raises(CallableSerializationError, match=r'saved as \{"ref": '):
        deserialize_callable(value)


# --- what a reference may name --------------------------------------------


def test_grafi_route_predicates_load_by_reference():
    ref = {"ref": "grafi.nodes.conditions:always_true"}
    assert deserialize_callable(ref) is always_true


@pytest.mark.parametrize(
    "ref",
    [
        "grafi.common.import_ref:trust_modules",
        "grafi.common.callable_ref:deserialize_callable",
        "grafi.nodes.node:Node",
    ],
)
def test_other_grafi_functions_are_refused(ref: str):
    with pytest.raises(UntrustedImportError, match="grafi function a manifest may"):
        deserialize_callable({"ref": ref})


@pytest.mark.parametrize("attr", ["BaseModel", "pytest.raises", "pytest", "SECRET_VAR"])
def test_reference_to_what_a_trusted_module_does_not_own_is_refused(attr: str):
    """This module is trusted, but not what it imported from elsewhere."""
    with pytest.raises(UntrustedImportError, match="reaches|is not trusted"):
        deserialize_callable({"ref": f"{__name__}:{attr}"})


def test_reference_to_an_untrusted_module_is_refused():
    with pytest.raises(UntrustedImportError, match="trust_modules"):
        deserialize_callable({"ref": "os:system"})


def test_deserialize_validates_in_the_context_given():
    topic = Topic(name="answers")
    value = {"class": f"{__name__}:ToTopic", "topic": "answers"}

    restored = deserialize_callable(value, context={"topics": {"answers": topic}})

    assert isinstance(restored, ToTopic)
    assert restored.topic is topic
    with pytest.raises(ValidationError, match="Unknown topic 'answers'"):
        deserialize_callable(value)


def test_a_grafi_function_imported_into_a_trusted_module_is_refused():
    """What decides is where a function belongs, not where it is named."""
    with pytest.raises(UntrustedImportError, match="grafi function a manifest may"):
        deserialize_callable({"ref": f"{__name__}:trust_modules"})
