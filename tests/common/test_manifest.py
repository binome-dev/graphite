"""Tests for components saved as data and loaded back (grafi.common.manifest).

Loading raises ManifestError and UntrustedImportError as they are. Saving as
JSON with ``model_dump`` raises pydantic's PydanticSerializationError, holding
the ManifestError's message, and ``to_manifest()`` raises the ManifestError
itself, from the component or any component or field within it. The python-mode
dump, ``model_dump()``, holds the values themselves -- the class, functions and
secrets -- and loads back in the same process.
"""

import json
import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Type

import pytest
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common import import_ref
from grafi.common.callable_ref import CallableRef
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.exceptions import GrafiError
from grafi.common.import_ref import UntrustedImportError
from grafi.common.import_ref import trust_modules
from grafi.common.manifest import API_VERSION
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest import ModelRef
from grafi.common.manifest import env_secret
from grafi.common.manifest import import_path
from grafi.common.manifest import secret_name
from grafi.common.manifest import secret_variable
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType

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


class Leaky(Component):
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    password: Optional[str] = None
    max_tokens: int = 100


class Answer(BaseModel):
    text: str


class Citation(BaseModel):
    url: str


class Formatted(Component):
    params: ModelRef[Dict[str, Any]] = Field(default_factory=dict)


def double(x: int) -> int:
    return 2 * x


class Hooked(BaseModel):
    fn: CallableRef


class Box(Component):
    """Fields declaring a base class, holding its subclasses."""

    gadget: Optional[Gadget] = None
    gadgets: List[Gadget] = Field(default_factory=list)
    keyed: Optional[Keyed] = None


@contextmanager
def raises_on_dump(expected: Type[Exception], match: str) -> Iterator[None]:
    """Expect ``model_dump`` to fail with an ``expected`` error matching
    ``match``, which pydantic reports in its own."""
    with pytest.raises(PydanticSerializationError, match=match) as info:
        yield
    assert f"{expected.__name__}: " in str(info.value)


# --------------------------------------------------------------------------- #
# Component: the class names the component, and picks the class it loads as
# --------------------------------------------------------------------------- #


def test_class_is_the_first_key_in_every_dump_mode() -> None:
    widget = Widget(color="blue")
    path = f"{__name__}:Widget"

    assert import_path(Widget) == path
    assert list(widget.model_dump(mode="json")) == ["class", "name", "size", "color"]
    assert widget.model_dump(mode="json")["class"] == path
    assert widget.model_dump_json().startswith(f'{{"class":"{path}"')
    # The python-mode dump holds the class itself, not its import path.
    assert list(widget.model_dump()) == ["class", "name", "size", "color"]
    assert widget.model_dump()["class"] is Widget


@pytest.mark.parametrize("base", [Component, Gadget, Widget])
def test_load_builds_the_class_named(base: Type[Component]) -> None:
    data = Widget(name="w", size=3, color="blue").model_dump(mode="json")

    loaded = base.model_validate(data)

    assert type(loaded) is Widget
    assert (loaded.name, loaded.size, loaded.color) == ("w", 3, "blue")
    assert loaded.model_dump(mode="json") == data
    assert type(base.model_validate_json(json.dumps(data))) is Widget


def test_load_without_class_builds_the_class_called() -> None:
    loaded = Widget.model_validate({"color": "green"})

    assert type(loaded) is Widget
    assert loaded.color == "green"


@pytest.mark.parametrize("base", [Component, Gadget, Widget])
def test_python_dump_loads_back_in_process(base: Type[Component]) -> None:
    widget = Widget(name="w", size=3, color="blue")
    data = widget.model_dump()

    loaded = base.model_validate(data)

    assert type(loaded) is Widget
    assert loaded == widget
    assert loaded.model_dump() == data


class Wired(Component):
    """Fields the python-mode dump holds as they are."""

    fn: CallableRef
    keyed: Keyed
    params: ModelRef[Dict[str, Any]] = Field(default_factory=dict)


def test_python_dump_holds_live_values_and_loads_them_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_VAR, "own-value")

    def local(x: int) -> int:  # Not importable: the dump holds it itself.
        return x

    wired = Wired(fn=local, keyed=Keyed(api_key="another-value"), params={"a": Answer})

    data = wired.model_dump()

    assert data == {
        "class": Wired,
        "fn": local,
        "keyed": {
            "class": Keyed,
            "api_key": "another-value",
            "token": None,
            "name": "keyed",
        },
        "params": {"a": Answer},
    }
    loaded = Wired.model_validate(data)
    assert loaded.fn is local
    assert loaded.keyed.api_key == "another-value"  # A secret, as its value.
    assert loaded.params["a"] is Answer
    assert loaded.model_dump() == data


def test_python_dump_holds_topics_in_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    question, answer = InputTopic(name="question"), OutputTopic(name="answer")
    node = (
        Node.builder()
        .name("Answerer")
        .subscribe(question)
        .tool(OpenAITool())
        .publish_to(answer)
        .build()
    )

    data = node.model_dump()

    [route] = data["publisher_router"]["routes"]
    assert route["topic"] == {
        "class": OutputTopic,
        "name": "answer",
        "type": TopicType.AGENT_OUTPUT_TOPIC_TYPE,
    }
    assert data["tool"]["api_key"] == "fake-openai-key"
    loaded = Node.model_validate(data)  # Without the topics in its context.
    assert loaded.node_id == node.node_id
    assert [(type(t), t.name) for t in loaded.subscribed_topics] == [
        (InputTopic, "question")
    ]
    assert [(type(t), t.name) for t in loaded.publish_to] == [(OutputTopic, "answer")]
    assert loaded.tool.api_key == "fake-openai-key"


@pytest.mark.parametrize("named", [f"{__name__}:Gadget", Gadget, Unrelated])
def test_constructing_from_data_naming_another_class_raises(named: Any) -> None:
    data = {**Widget(color="blue").model_dump(mode="json"), "class": named}

    with pytest.raises(ManifestError, match=r"load it with Widget\.model_validate"):
        Widget(**data)


@pytest.mark.parametrize("named", [f"{__name__}:Widget", Widget])
def test_constructing_from_data_naming_its_class(named: Any) -> None:
    widget = Widget(**{"class": named, "name": "w", "color": "blue"})

    assert (widget.name, widget.color) == ("w", "blue")


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError, match="colour"):
        Widget(colour="blue")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Gadget.model_validate({"class": f"{__name__}:Widget", "colour": "blue"})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Holder.model_validate({"item": {"class": f"{__name__}:Gadget", "sise": 2}})


def _local_class() -> Type[Gadget]:
    class Local(Gadget):
        pass

    return Local


@pytest.mark.parametrize(
    "cls",
    [
        _local_class(),
        type("Scripted", (Gadget,), {"__module__": "__main__"}),
    ],
    ids=["local", "__main__"],
)
def test_class_that_cannot_be_imported_back_cannot_be_saved(
    cls: Type[Gadget],
) -> None:
    """A class a fresh process cannot import -- one a function defines, or a
    script -- is refused when saving, not when loading."""
    match = "cannot be saved by reference"
    with pytest.raises(ManifestError, match=match):
        import_path(cls)
    with pytest.raises(ManifestError, match=match):
        cls().to_manifest()
    with raises_on_dump(ManifestError, match):
        Box(gadget=cls()).model_dump(mode="json")
    assert cls().model_dump()["class"] is cls  # Kept, in process.


def test_grafi_tool_loads_as_its_own_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tool = OpenAITool(name="Planner", model="gpt-4o-mini", system_message="Plan.")
    data = tool.model_dump(mode="json")

    loaded = Tool.model_validate(data)

    assert data["class"] == "grafi.tools.llms.impl.openai_tool:OpenAITool"
    assert type(loaded) is OpenAITool
    assert loaded.tool_id == tool.tool_id
    assert (loaded.name, loaded.model) == ("Planner", "gpt-4o-mini")
    assert loaded.system_message == "Plan."


@pytest.mark.parametrize(
    "base, data, kind",
    [
        (Gadget, {"class": f"{__name__}:Unrelated"}, "Gadget"),
        (Widget, {"class": f"{__name__}:Gadget"}, "Widget"),
        (Tool, Topic(name="t").model_dump(mode="json"), "Tool"),
        (Tool, {"class": "grafi.nodes.conditions:always_true"}, "Tool"),
    ],
)
def test_class_that_is_not_a_subclass_raises(
    base: Type[Component], data: Dict[str, Any], kind: str
) -> None:
    with pytest.raises(ManifestError, match=f"is not a subclass of {kind}"):
        base.model_validate(data)


@pytest.mark.parametrize("value", [5, None, ["grafi.tools.tool:Tool"], {"a": 1}])
def test_class_that_is_not_an_import_path_raises(value: Any) -> None:
    with pytest.raises(ManifestError, match="must be named by its import path"):
        Component.model_validate({"class": value})


@pytest.mark.parametrize("path", ["grafi.tools.tool.Tool", "OpenAITool"])
def test_class_that_is_not_an_import_path_string_raises(path: str) -> None:
    with pytest.raises(ManifestError, match="Cannot import .* must be an import path"):
        Component.model_validate({"class": path})


@pytest.mark.parametrize(
    "path", ["grafi.no_such_module:Thing", "grafi.tools.tool:NoSuchTool"]
)
def test_class_that_cannot_be_imported_raises(path: str) -> None:
    with pytest.raises(ManifestError, match="Cannot import"):
        Tool.model_validate({"class": path})


_UNTRUSTED_MODULE = """
from pathlib import Path

from grafi.common.manifest import Component

Path(__file__).with_suffix(".imported").touch()


class Thing(Component):
    size: int = 0
"""


@pytest.fixture
def untrusted_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The name of a throwaway module defining a Component, ``Thing``, which
    is importable but not trusted. The test's trust_modules() is undone."""
    monkeypatch.setattr(import_ref, "_trusted", import_ref._trusted)
    name = f"grafi_test_untrusted_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(_UNTRUSTED_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield name
    sys.modules.pop(name, None)


def test_untrusted_class_raises_without_importing_its_module(
    untrusted_module: str, tmp_path: Path
) -> None:
    with pytest.raises(UntrustedImportError, match="trust_modules"):
        Component.model_validate({"class": f"{untrusted_module}:Thing", "size": 2})

    assert untrusted_module not in sys.modules
    assert not (tmp_path / f"{untrusted_module}.imported").exists()


def test_trusted_module_class_loads(untrusted_module: str) -> None:
    trust_modules(untrusted_module)

    thing = Component.model_validate({"class": f"{untrusted_module}:Thing", "size": 2})

    assert type(thing).__module__ == untrusted_module
    assert type(thing).__name__ == "Thing"
    assert thing.size == 2


def test_subclass_in_a_field_of_its_base_saves_as_itself() -> None:
    box = Box(gadget=Widget(color="blue"), gadgets=[Gadget(size=2), Widget(size=3)])

    data = box.model_dump(mode="json")

    assert data["gadget"] == {
        "class": f"{__name__}:Widget",
        "name": "gadget",
        "size": 1,
        "color": "blue",
    }
    assert [item["class"] for item in data["gadgets"]] == [
        f"{__name__}:Gadget",
        f"{__name__}:Widget",
    ]
    loaded = Box.model_validate(json.loads(json.dumps(data)))
    assert type(loaded.gadget) is Widget
    assert loaded.gadget.color == "blue"
    assert [type(item) for item in loaded.gadgets] == [Gadget, Widget]
    assert loaded.model_dump(mode="json") == data


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


def test_the_variable_a_secret_field_is_read_from() -> None:
    assert secret_variable(Keyed, "api_key") == SECRET_VAR
    assert secret_variable(Keyed, "token") is None  # Without one of its own.
    assert secret_variable(Keyed, "name") is None  # Not a secret.
    assert secret_variable(OpenAITool, "api_key") == "OPENAI_API_KEY"


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
        {"class": f"{__name__}:Holder", "item": {"name": "no class"}},
        {"class": f"{__name__}:Box", "gadget": {"size": 2}},
        {"class": f"{__name__}:Box", "gadgets": [{"class": f"{__name__}:Widget"}, {}]},
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
        "class": f"{__name__}:Leaky",
        "api_key": value,
        "access_token": value,
        "password": value,
        "max_tokens": 7,
    }


class Configured(Component):
    """Fields holding settings, which may hold secrets within them."""

    params: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)


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


@pytest.mark.parametrize(
    "params",
    [
        {"extra_headers": {"Authorization": "Bearer ${API_TOKEN}"}},
        {"api_key": "${OPENAI_API_KEY}", "nested": [{"password": "${DB_PASSWORD}"}]},
        {"Authorization": "Basic ${CREDENTIALS}", "X-Auth": "Token ${API_TOKEN}"},
        {"auth": "oauth"},  # A way to authenticate, as MCP's.
        {"extra_headers": {"Authorization": "ApiKey ${ES_API_KEY}"}},  # Any scheme.
        {"headers": [["Authorization", "Bearer ${API_TOKEN}"], ["Accept", "*/*"]]},
        {"api_key": "", "access_token": None, "secret": 0},
        {"max_tokens": 10, "eos_token": "</s>", "cache_key": "k", "tokens": ["a"]},
        {"pad_token": "<pad>", "mask_token": "<mask>", "maxTokens": 5},
        {"url": "postgresql://app:${DB_PASSWORD}@db.example.com/app"},
        {"url": "https://user@example.com/x", "home": "https://example.com/@me"},
    ],
)
def test_settings_without_a_secret_value_are_saved(params: Dict[str, Any]) -> None:
    configured = Configured(params=params)

    data = configured.model_dump(mode="json")

    assert data["params"] == params
    assert Configured.model_validate(json.loads(json.dumps(data))) == configured
    manifest = json.loads(json.dumps(configured.to_manifest()))
    assert Configured.from_manifest(manifest) == configured


@pytest.mark.parametrize(
    "name",
    [
        "api_key",
        "OPENAI_API_KEY",
        "apikey",
        "X-Api-Key",
        "secret",
        "client_secret",
        "secret_key",
        "private_key",
        "access_key",
        "password",
        "passwd",
        "credentials",
        "auth",
        "Authorization",
        "Cookie",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "bearer_token",
        "session_token",
        "api_token",
        "github_token",
        "GITHUB_TOKEN",
        "hf_token",
        "clientSecret",
        "api_keys",
        "passwords",
        "client_secrets",
        "PGPASSWORD",
        "OpenAIApiKey",
        "dbPassword",
        "accessToken",
        "apiSecret",
        "apiKey",
    ],
)
def test_names_that_say_they_hold_a_secret(name: str) -> None:
    assert secret_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "max_tokens",
        "maxTokens",
        "cache_key",
        "tokens",
        "token_count",
        "author",
        "keyword",
        "secretary",
        # A tokenizer's special tokens.
        "eos_token",
        "bos_token",
        "pad_token",
        "unk_token",
        "sep_token",
        "cls_token",
        "mask_token",
        "PAD_TOKEN",
        "padToken",
    ],
)
def test_names_that_do_not_say_they_hold_a_secret(name: str) -> None:
    assert not secret_name(name)


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


# --------------------------------------------------------------------------- #
# ModelRef and CallableRef: classes and functions saved as import paths
# --------------------------------------------------------------------------- #


def test_model_classes_are_saved_as_references_in_dicts_and_lists() -> None:
    params = {
        "response_format": Answer,
        "schemas": [Answer, {"cite": Citation}, "text"],
        "temperature": 0.2,
        "ref": "not a reference, beside other keys",
    }
    formatted = Formatted(params=params)

    data = formatted.model_dump(mode="json")

    assert data["params"] == {
        "response_format": {"ref": f"{__name__}:Answer"},
        "schemas": [
            {"ref": f"{__name__}:Answer"},
            {"cite": {"ref": f"{__name__}:Citation"}},
            "text",
        ],
        "temperature": 0.2,
        "ref": "not a reference, beside other keys",
    }
    assert formatted.model_dump()["params"]["response_format"] is Answer
    loaded = Formatted.model_validate(json.loads(json.dumps(data)))
    assert loaded.params == params
    assert loaded.params["response_format"] is Answer
    assert loaded.params["schemas"][1]["cite"] is Citation


def test_model_reference_to_a_non_model_raises() -> None:
    reference = {"ref": "grafi.nodes.conditions:always_true"}
    with pytest.raises(ManifestError, match="is not a subclass of BaseModel"):
        Formatted.model_validate({"params": {"response_format": reference}})


def test_model_reference_to_an_untrusted_module_raises() -> None:
    reference = {"ref": "json:JSONDecoder"}
    with pytest.raises(UntrustedImportError, match="trust_modules"):
        Formatted.model_validate({"params": {"response_format": reference}})


def test_function_field_round_trips_by_reference() -> None:
    hooked = Hooked(fn=double)

    data = hooked.model_dump(mode="json")

    assert data == {"fn": {"ref": f"{__name__}:double"}}
    assert Hooked.model_validate(data).fn is double
    assert Hooked.model_validate_json(hooked.model_dump_json()).fn is double


def test_function_field_keeps_the_function_in_python_mode() -> None:
    assert Hooked(fn=double).model_dump()["fn"] is double
    anonymous = Hooked(fn=lambda x: x)
    assert anonymous.model_dump()["fn"] is anonymous.fn


def test_lambda_function_field_cannot_be_saved_as_json() -> None:
    anonymous = Hooked(fn=lambda x: x)

    with raises_on_dump(CallableSerializationError, "without pickle"):
        anonymous.model_dump(mode="json")
    with pytest.raises(PydanticSerializationError, match="without pickle"):
        anonymous.model_dump_json()


def test_function_reference_to_an_untrusted_module_raises() -> None:
    with pytest.raises(UntrustedImportError, match="trust_modules"):
        Hooked.model_validate({"fn": {"ref": "os:getcwd"}})


@pytest.mark.parametrize(
    "ref",
    [
        "grafi.nodes.conditions:no_such_fn",
        "nocolon",
        f"{__name__}:no_such_fn",
        f"{__name__}_no_such_module:fn",
    ],
)
def test_function_reference_that_cannot_be_imported_raises(
    ref: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(import_ref, "_trusted", import_ref._trusted)
    trust_modules(f"{__name__}_no_such_module")

    with pytest.raises(CallableSerializationError, match="Cannot import"):
        Hooked.model_validate({"fn": {"ref": ref}})
    assert issubclass(CallableSerializationError, ManifestError)


@pytest.mark.parametrize(
    "ref", ["grafi.common.import_ref:trust_modules", "grafi.no_such_module:fn"]
)
def test_function_reference_to_grafi_outside_its_conditions_raises(ref: str) -> None:
    with pytest.raises(UntrustedImportError, match="grafi function a manifest may"):
        Hooked.model_validate({"fn": {"ref": ref}})


def test_function_saved_as_a_bare_import_path_raises() -> None:
    with pytest.raises(CallableSerializationError, match='saved as {"ref": '):
        Hooked.model_validate({"fn": "grafi.nodes.conditions:always_true"})


# --------------------------------------------------------------------------- #
# Manifests: a component's JSON in an envelope
# --------------------------------------------------------------------------- #


def test_manifest_errors_are_grafi_errors() -> None:
    error = ManifestError("Cannot load it.")

    assert isinstance(error, GrafiError)
    assert str(error) == "[ERROR] Cannot load it."
    assert issubclass(UntrustedImportError, ManifestError)
    assert issubclass(UntrustedImportError, ImportError)
    assert issubclass(CallableSerializationError, ManifestError)


class Initialized(Gadget):
    """A component with an __init__ of its own."""

    def __init__(self, **data: Any) -> None:
        data.setdefault("size", 7)
        super().__init__(**data)


def test_a_component_with_its_own_init_is_never_loaded_from_a_manifest() -> None:
    """Pydantic validates such a class by calling its __init__, which would
    load what it holds without from_manifest()'s rules."""
    manifest = Initialized(name="i").to_manifest()
    nested = {
        "apiVersion": API_VERSION,
        "kind": "Holder",
        "spec": {"class": import_path(Holder), "item": manifest["spec"]},
    }

    for refused in (manifest, nested):
        with pytest.raises(ManifestError, match="Initialized has an __init__ of its"):
            Component.from_manifest(refused)
    # In code, it is built and loaded as any component is.
    assert Initialized().size == 7
    loaded = Component.model_validate(manifest["spec"])
    assert type(loaded) is Initialized
    assert (loaded.name, loaded.size) == ("i", 7)
    assert type(Holder.model_validate(nested["spec"]).item) is Initialized


class Building(Component):
    """A component building one with an __init__ of its own, in code."""

    built: Optional[Initialized] = Field(default=None, exclude=True)

    def model_post_init(self, _context: Any) -> None:
        self.built = Initialized(name="built")


def test_a_component_with_its_own_init_built_in_code_while_loading_is_fine() -> None:
    """Only one the manifest holds is refused, not one built in code."""
    loaded = Building.from_manifest(Building().to_manifest())

    assert loaded.built is not None and loaded.built.size == 7


def test_manifest_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    widget = Widget(color="blue")

    assert API_VERSION == "grafi/v2"
    assert widget.to_manifest() == {
        "apiVersion": "grafi/v2",
        "kind": "Gadget",  # The nearest manifest_kind.
        "spec": widget.model_dump(mode="json"),
    }
    assert Unrelated().to_manifest()["kind"] == "Unrelated"  # Its class name.
    assert OpenAITool().to_manifest()["kind"] == "Tool"
    assert Topic(name="t").to_manifest()["kind"] == "Topic"


@pytest.mark.parametrize("base", [Component, Gadget, Widget])
def test_manifest_round_trips(base: Type[Component]) -> None:
    widget = Widget(name="w", color="blue")

    loaded = base.from_manifest(json.loads(json.dumps(widget.to_manifest())))

    assert type(loaded) is Widget
    assert loaded.to_manifest() == widget.to_manifest()


def test_manifest_loads_from_a_path(tmp_path: Path) -> None:
    widget = Widget(color="blue")
    path = tmp_path / "widget.json"
    path.write_text(json.dumps(widget.to_manifest()))

    for source in (path, str(path)):
        loaded = Gadget.from_manifest(source)
        assert type(loaded) is Widget
        assert loaded.color == "blue"


@pytest.mark.parametrize("version", ["grafi/v1", "grafi/v3", None])
def test_manifest_of_another_version_raises(version: Optional[str]) -> None:
    manifest = {**Widget().to_manifest(), "apiVersion": version}
    with pytest.raises(ManifestError, match="Unsupported manifest version"):
        Gadget.from_manifest(manifest)


@pytest.mark.parametrize("kind", ["Tool", "Widget", None])
def test_manifest_of_another_kind_raises(kind: Optional[str]) -> None:
    manifest = {**Widget().to_manifest(), "kind": kind}
    match = f"The manifest's kind is {kind!r}, but its spec is of kind 'Gadget'."
    with pytest.raises(ManifestError, match=re.escape(match)):
        Component.from_manifest(manifest)


def test_manifest_without_a_kind_raises() -> None:
    manifest = Widget().to_manifest()
    del manifest["kind"]
    with pytest.raises(ManifestError, match="kind is None"):
        Gadget.from_manifest(manifest)


class Recorded(Component):
    """A component that records each one built."""

    manifest_kind: ClassVar[Optional[str]] = "Recorded"
    built: ClassVar[List[str]] = []

    name: str = "recorded"

    def model_post_init(self, _context: Any) -> None:
        Recorded.built.append(self.name)


def test_manifest_kind_is_checked_before_its_component_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Recorded, "built", [])
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "Tool",
        "spec": {"class": import_path(Recorded), "name": "loaded"},
    }

    with pytest.raises(ManifestError, match="kind is 'Tool'"):
        Component.from_manifest(manifest)
    assert Recorded.built == []

    loaded = Component.from_manifest({**manifest, "kind": "Recorded"})
    assert type(loaded) is Recorded
    assert Recorded.built == ["loaded"]


class Derived(Component):
    """A component with a field that follows from another, never saved."""

    size: int = 1
    double: int = Field(default=0, exclude=True)

    def model_post_init(self, _context: Any) -> None:
        self.double = 2 * self.size


@pytest.mark.parametrize(
    "kind, spec, unsaved",
    [
        (
            "Derived",
            {"class": f"{__name__}:Derived", "size": 2, "double": 5},
            "Derived.double",
        ),
        (
            "Tool",
            {
                "class": "grafi.tools.function_calls.function_call_tool:"
                "FunctionCallTool",
                "function_specs": [],
            },
            "FunctionCallTool.function_specs",
        ),
        (
            "Topic",
            {"class": "grafi.topics.topic_impl.topic:Topic", "event_queue": {}},
            "Topic.event_queue",
        ),
    ],
    ids=["own", "function specs", "event queue"],
)
def test_a_manifest_never_holds_a_field_that_is_never_saved(
    kind: str, spec: Dict[str, Any], unsaved: str
) -> None:
    manifest = {"apiVersion": API_VERSION, "kind": kind, "spec": spec}

    with pytest.raises(ManifestError, match=f"{unsaved} is never saved, so a"):
        Component.from_manifest(manifest)


class Deriving(Component):
    parts: List[Derived] = Field(default_factory=list)


def test_a_nested_field_that_is_never_saved_is_refused() -> None:
    derived = {"class": f"{__name__}:Derived", "double": 4}
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "Deriving",
        "spec": {"class": f"{__name__}:Deriving", "parts": [derived]},
    }

    with pytest.raises(ManifestError, match="Derived.double is never saved"):
        Component.from_manifest(manifest)


def test_a_field_that_is_never_saved_follows_from_the_others() -> None:
    derived = Derived(size=3)

    loaded = Component.from_manifest(json.loads(json.dumps(derived.to_manifest())))

    assert "double" not in derived.to_manifest()["spec"]
    assert type(loaded) is Derived
    assert loaded.double == 6
    # Loaded in code, it may be given, as code is trusted.
    assert Component.model_validate({"class": Derived, "double": 0}) == Derived()


@pytest.mark.parametrize("spec", [{"name": "w"}, ["class"], None])
def test_manifest_spec_without_class_raises(spec: Any) -> None:
    manifest = {"apiVersion": API_VERSION, "kind": "Gadget", "spec": spec}
    with pytest.raises(ManifestError, match="spec is a component, with its class"):
        Gadget.from_manifest(manifest)


def test_manifest_that_is_not_an_object_raises(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]")
    with pytest.raises(ManifestError, match="A manifest is a JSON object"):
        Component.from_manifest(path)


def test_dict_that_is_not_a_manifest_raises() -> None:
    with pytest.raises(ManifestError, match="Not a manifest"):
        Component.from_manifest({"spec": Widget().model_dump(mode="json")})


@pytest.mark.parametrize(
    "base, manifest, kind",
    [
        (Unrelated, Widget().to_manifest(), "Unrelated"),
        (Tool, Topic(name="t").to_manifest(), "Tool"),
        (Topic, Widget().to_manifest(), "Topic"),
    ],
)
def test_manifest_of_another_class_raises(
    base: Type[Component], manifest: Dict[str, Any], kind: str
) -> None:
    with pytest.raises(ManifestError, match=f"is not a subclass of {kind}"):
        base.from_manifest(manifest)


def test_manifest_loads_in_a_validation_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    question, answer = InputTopic(name="question"), OutputTopic(name="answer")
    node = (
        Node.builder()
        .name("Answerer")
        .subscribe(question)
        .tool(OpenAITool())
        .publish_to(answer)
        .build()
    )
    manifest = json.loads(json.dumps(node.to_manifest()))
    assert manifest["kind"] == "Node"

    topics = {"question": question, "answer": answer}
    loaded = Node.from_manifest(manifest, context={"topics": topics})

    assert loaded.node_id == node.node_id
    assert loaded.subscribed_topics == [question]
    assert loaded.publish_to == [answer]
    with pytest.raises(ValidationError, match="Unknown topic 'question'"):
        Node.from_manifest(manifest)


def test_nested_secret_set_to_another_value_raises_from_to_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_VAR, "s3cret-value")
    box = Box(keyed=Keyed(api_key="another-value"))

    with pytest.raises(ManifestError, match="Keyed.api_key"):
        box.to_manifest()
    with raises_on_dump(ManifestError, "Keyed.api_key"):
        box.model_dump(mode="json")


def test_function_that_cannot_be_saved_raises_from_to_manifest() -> None:
    class Holder(Component):
        fn: CallableRef

    with pytest.raises(CallableSerializationError, match="without pickle"):
        Holder(fn=lambda x: x).to_manifest()


def test_a_class_with_secrets_takes_no_alias_generator() -> None:
    """Secrets are saved and loaded by their fields' names."""
    from pydantic.alias_generators import to_camel

    with pytest.raises(TypeError, match="takes no alias_generator"):

        class Aliased(Component):
            model_config = ConfigDict(alias_generator=to_camel)
            upstream_dsn: Optional[str] = env_secret(SECRET_VAR)


def test_an_env_reference_names_a_variable() -> None:
    """Text that is no variable's name is not a reference: it is a value."""
    with pytest.raises(ManifestError, match="holds a secret"):
        Formatted(params={"api_key": {"env": "sk-FAKE-1"}}).to_manifest()


def test_a_class_key_hides_no_secret() -> None:
    """Only a component's class, an import path, is skipped."""
    with pytest.raises(ManifestError, match="holds a secret"):
        Formatted(params={"api_key": {"class": "sk-FAKE-1"}}).to_manifest()


def test_a_manifest_holds_only_json() -> None:
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "Formatted",
        "spec": {"class": import_path(Formatted), "params": {"blob": b"bytes"}},
    }

    with pytest.raises(ManifestError, match="holds only JSON"):
        Formatted.from_manifest(manifest)
