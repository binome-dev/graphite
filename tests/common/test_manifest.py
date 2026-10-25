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
from typing import FrozenSet
from typing import List
from typing import Optional
from typing import Type

import pytest
from pydantic import AliasChoices
from pydantic import AliasPath
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import computed_field
from pydantic_core import PydanticSerializationError

from grafi.common.callable_ref import CallableRef
from grafi.common.exceptions import CallableSerializationError
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
    with pytest.raises(UntrustedImportError, match="outside the trusted modules"):
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

    loaded = Gadget.from_manifest(path)
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
            "Topic",
            {"class": "grafi.topics.topic_impl.topic:Topic", "event_queue": {}},
            "Topic.event_queue",
        ),
    ],
    ids=["own", "event queue"],
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


class Connected(Component):
    """A component holding what is made at run time, saved by mistake."""

    client: Any = None


def test_a_value_json_cannot_hold_is_a_manifest_error() -> None:
    with pytest.raises(
        ManifestError, match="Connected.client cannot be saved.*exclude"
    ):
        Connected(client=object()).to_manifest()


def test_the_field_named_unsaveable_is_the_innermost() -> None:
    """Not the outer field holding it, which the advice would have excluded."""
    holder = Holder(item=Gadget())
    holder.item.__dict__["size"] = object()  # As a client set at run time.

    with pytest.raises(ManifestError, match=r"^\[ERROR\] Gadget.size cannot be saved"):
        holder.to_manifest()


def test_a_str_is_json_never_a_path(tmp_path: Path) -> None:
    """Text from a database or a request never names a file to read: only a
    pathlib.Path does."""
    manifest = Gadget(name="g").to_manifest()
    text = json.dumps(manifest)
    path = tmp_path / "gadget.json"
    path.write_text("\ufeff" + text, encoding="utf-8")  # With a BOM.

    for source in (text, f"\ufeff  {text}", text.encode(), path):
        assert Component.from_manifest(source) == Gadget(name="g")
    for refused in ("{not json", str(path), "/etc/passwd", "", "[1, 2]"):
        with pytest.raises(ManifestError, match="pathlib.Path|JSON object"):
            Component.from_manifest(refused)


class Cycle(Component):
    """A component that can hold itself."""

    other: Optional["Cycle"] = None


class BuildsOnly(Component):
    """A required field saving leaves out."""

    client: Any = Field(exclude=True)


def test_a_cycle_is_refused_as_a_manifest_error() -> None:
    cycle = Cycle()
    cycle.other = cycle

    with pytest.raises(ManifestError, match="Circular reference"):
        cycle.to_manifest()


class Aliased(Component):
    """A field named as BaseModel's attribute is, by its alias."""

    schema_: str = Field("public", alias="schema")


class HiddenByAlias(Component):
    """A field saving leaves out, with an alias."""

    retries: int = Field(3, alias="maxRetries", exclude=True)


class HiddenByChoices(Component):
    """A field saving leaves out, with alias choices."""

    cache: int = Field(
        0, exclude=True, validation_alias=AliasChoices("cache", AliasPath("c", 0))
    )


def test_a_manifest_holds_no_field_saving_leaves_out_by_its_alias_either() -> None:
    spec = {"class": import_path(HiddenByAlias), "maxRetries": 9}

    with pytest.raises(ManifestError, match="HiddenByAlias.retries is never saved"):
        Component.from_manifest(spec)
    saved = HiddenByChoices(cache=5).to_manifest()
    assert Component.from_manifest(saved).cache == 0
    with pytest.raises(ManifestError, match="HiddenByChoices.cache is never saved"):
        Component.from_manifest({"class": import_path(HiddenByChoices), "c": [5]})


def test_a_field_with_an_alias_saves_and_loads_by_its_name() -> None:
    saved = Aliased(schema="private").to_manifest()

    assert Component.from_manifest(saved).schema_ == "private"
    assert Aliased.model_validate({"schema": "by-alias"}).schema_ == "by-alias"


class SometimesLeftOut(Component):
    """A required field saving may leave out."""

    count: int = Field(exclude_if=lambda count: count == 0)


def test_a_required_field_saving_leaves_out_is_refused() -> None:
    """What is saved could not be loaded."""
    with pytest.raises(ManifestError, match="BuildsOnly.client is never saved"):
        BuildsOnly(client=object()).to_manifest()
    with pytest.raises(ManifestError, match="SometimesLeftOut.count is left out"):
        SometimesLeftOut(count=0).to_manifest()


class LeftOutAtZero(Component):
    """A field saving leaves out at a value other than its default."""

    retries: int = Field(3, exclude_if=lambda retries: retries == 0)


def test_a_field_left_out_holding_other_than_its_default_is_refused() -> None:
    """Loading would give it its default, 3, not the 0 it held."""
    with pytest.raises(ManifestError, match="LeftOutAtZero.retries is left out"):
        LeftOutAtZero(retries=0).to_manifest()
    assert LeftOutAtZero(retries=5).to_manifest()["spec"]["retries"] == 5


def test_a_container_holding_itself_is_refused_as_a_manifest_error() -> None:
    held: Dict[str, Any] = {}
    held["self"] = held

    tool = OpenAITool()
    tool.chat_params = held

    with pytest.raises(ManifestError, match="OpenAITool.chat_params cannot be saved"):
        tool.to_manifest()


@pytest.mark.parametrize(
    "manifest",
    [
        {"workflow": 5},
        {"workflow": {"topics": [1]}},
        {"class": ["a"], "base_class": "Tool"},
        {"apiVersion": API_VERSION, "kind": "Gadget", "spec": {"class": 1}},
        "[" * 100_000,
    ],
    ids=["workflow", "topics", "class", "spec class", "deep"],
)
def test_whatever_a_manifest_holds_is_refused_as_a_manifest_error(
    manifest: Any,
) -> None:
    """A web handler need catch ManifestError and ValidationError only."""
    with pytest.raises((ManifestError, ValidationError)):
        Component.from_manifest(manifest)


def test_a_partial_dump_of_a_tool_given_specs_is_not_refused() -> None:
    """The exclude_if rule looks at the value, not at what a dump includes."""
    from grafi.common.models.function_spec import FunctionSpec
    from grafi.tools.function_calls.function_call_tool import FunctionCallTool

    spec = FunctionSpec.model_validate(
        {
            "name": "remote",
            "description": "Elsewhere.",
            "parameters": {"type": "object", "properties": {}},
        }
    )
    tool = FunctionCallTool(function_specs=[spec])

    assert tool.model_dump(mode="json", include={"name"})["name"] == tool.name
    assert "function_specs" not in tool.model_dump(
        mode="json", exclude={"function_specs"}
    )


class TokenAndClient(Component):
    """A held secret, then a client."""

    token: Optional[str] = None
    client: Any = None


def test_a_refusal_met_while_naming_the_field_is_raised_as_it_is() -> None:
    """Not blamed on another field's value: the secret is the problem named."""
    holder = TokenAndClient(token="hunter2-hunter2", client=object())

    with pytest.raises(ManifestError) as raised:
        holder.to_manifest()

    assert "Unable to serialize" not in str(raised.value)
    assert "token" in str(raised.value)


class WithEndpoint(Component):
    """A computed field, saved, which follows from the others."""

    host: str = "example.com"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endpoint(self) -> str:
        return f"https://{self.host}/v1"


def test_a_computed_field_follows_from_the_fields_saved() -> None:
    """Not saved, so an edited one cannot disagree with them; a python dump,
    which holds it, loads without it."""
    component = WithEndpoint(host="api.example.com")
    saved = component.to_manifest()

    assert "endpoint" not in saved["spec"]
    assert Component.from_manifest(saved).endpoint == component.endpoint
    assert "endpoint" not in component.model_dump()  # Nor in a python dump.
    assert WithEndpoint.model_validate(component.model_dump()).host == component.host
    saved["spec"]["endpoint"] = "https://elsewhere/v1"
    with pytest.raises(ValidationError, match="endpoint"):
        Component.from_manifest(saved)


def test_loads_computed_names_only_computed_fields() -> None:
    """A misspelt one would leave the field out of what is saved."""
    with pytest.raises(TypeError, match=r"names \['endpont'\], which are not"):

        class Misspelt(WithEndpoint):
            loads_computed: ClassVar[FrozenSet[str]] = frozenset({"endpont"})
