"""Tests for a Component's class in its data (grafi.common.manifest): the
class names the component, picks the class it loads as, and is imported from
trusted modules only.

The python-mode dump, ``model_dump()``, holds the values themselves -- the
class, functions and secrets -- and loads back in the same process; the JSON
form names the class by import path.
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterator
from typing import Type

import pytest
from pydantic import Field
from pydantic import ValidationError

from grafi.common import import_ref
from grafi.common.callable_ref import CallableRef
from grafi.common.import_ref import UntrustedImportError
from grafi.common.import_ref import trust_modules
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest import ModelRef
from grafi.common.manifest import import_path
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType
from tests.common.manifest_fixtures import SECRET_VAR
from tests.common.manifest_fixtures import Answer
from tests.common.manifest_fixtures import Box
from tests.common.manifest_fixtures import Gadget
from tests.common.manifest_fixtures import Holder
from tests.common.manifest_fixtures import Keyed
from tests.common.manifest_fixtures import Unrelated
from tests.common.manifest_fixtures import Widget
from tests.common.manifest_fixtures import raises_on_dump

WIDGET = import_path(Widget)
GADGET = import_path(Gadget)


def test_class_is_the_first_key_in_every_dump_mode() -> None:
    widget = Widget(color="blue")

    assert WIDGET == f"{Widget.__module__}:Widget"
    assert list(widget.model_dump(mode="json")) == ["class", "name", "size", "color"]
    assert widget.model_dump(mode="json")["class"] == WIDGET
    assert widget.model_dump_json().startswith(f'{{"class":"{WIDGET}"')
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


@pytest.mark.parametrize("named", [GADGET, Gadget, Unrelated])
def test_constructing_from_data_naming_another_class_raises(named: Any) -> None:
    data = {**Widget(color="blue").model_dump(mode="json"), "class": named}

    with pytest.raises(ManifestError, match=r"load it with Widget\.model_validate"):
        Widget(**data)


@pytest.mark.parametrize("named", [WIDGET, Widget])
def test_constructing_from_data_naming_its_class(named: Any) -> None:
    widget = Widget(**{"class": named, "name": "w", "color": "blue"})

    assert (widget.name, widget.color) == ("w", "blue")


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError, match="colour"):
        Widget(colour="blue")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Gadget.model_validate({"class": WIDGET, "colour": "blue"})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Holder.model_validate({"item": {"class": GADGET, "sise": 2}})


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
        (Gadget, {"class": import_path(Unrelated)}, "Gadget"),
        (Widget, {"class": GADGET}, "Widget"),
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
    with pytest.raises(ManifestError, match="is not an import path"):
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
        "class": WIDGET,
        "name": "gadget",
        "size": 1,
        "color": "blue",
    }
    assert [item["class"] for item in data["gadgets"]] == [GADGET, WIDGET]
    loaded = Box.model_validate(json.loads(json.dumps(data)))
    assert type(loaded.gadget) is Widget
    assert loaded.gadget.color == "blue"
    assert [type(item) for item in loaded.gadgets] == [Gadget, Widget]
    assert loaded.model_dump(mode="json") == data
