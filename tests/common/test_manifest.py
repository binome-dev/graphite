"""Tests for manifests (grafi.common.manifest): a component's JSON in an
envelope naming the format and its kind, and the fields saved as references
to classes and functions (ModelRef, CallableRef).

Loading raises ManifestError and UntrustedImportError as they are. Saving as
JSON with ``model_dump`` raises pydantic's PydanticSerializationError, holding
the ManifestError's message, and ``to_manifest()`` raises the ManifestError
itself, from the component or any component or field within it. A component's
class in its data is tested in test_manifest_component.py, and its secrets in
test_manifest_secrets.py.
"""

import json
import re
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import List
from typing import Optional
from typing import Type

import pytest
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common.callable_ref import CallableRef
from grafi.common.callable_ref import CallableSerializationError
from grafi.common.exceptions import GrafiError
from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import API_VERSION
from grafi.common.manifest import Component
from grafi.common.manifest import ManifestError
from grafi.common.manifest import import_path
from grafi.common.manifest import kind_of
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from tests.common.manifest_fixtures import Answer
from tests.common.manifest_fixtures import Formatted
from tests.common.manifest_fixtures import Gadget
from tests.common.manifest_fixtures import Holder
from tests.common.manifest_fixtures import Unrelated
from tests.common.manifest_fixtures import Widget
from tests.common.manifest_fixtures import raises_on_dump


class Citation(BaseModel):
    url: str


def double(x: int) -> int:
    return 2 * x


class Hooked(BaseModel):
    fn: CallableRef


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
        "response_format": {"ref": import_path(Answer)},
        "schemas": [
            {"ref": import_path(Answer)},
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


def test_kind_of_is_the_nearest_manifest_kind_else_the_class_name() -> None:
    assert kind_of(Widget) == "Gadget"
    assert kind_of(Unrelated) == "Unrelated"
    assert kind_of(OpenAITool) == "Tool"
    assert kind_of(Node) == "Node"


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


def test_function_that_cannot_be_saved_raises_from_to_manifest() -> None:
    class Holder(Component):
        fn: CallableRef

    with pytest.raises(CallableSerializationError, match="without pickle"):
        Holder(fn=lambda x: x).to_manifest()


def test_a_manifest_holds_only_json() -> None:
    manifest = {
        "apiVersion": API_VERSION,
        "kind": "Formatted",
        "spec": {"class": import_path(Formatted), "params": {"blob": b"bytes"}},
    }

    with pytest.raises(ManifestError, match="holds only JSON"):
        Formatted.from_manifest(manifest)
