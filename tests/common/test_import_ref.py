"""Tests for resolving import references from trusted modules only
(grafi.common.import_ref)."""

import functools
import sys
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from grafi.common import import_ref
from grafi.common.import_ref import UntrustedImportError
from grafi.common.import_ref import is_trusted
from grafi.common.import_ref import reference_to
from grafi.common.import_ref import resolve_import_ref
from grafi.common.import_ref import trust_modules
from grafi.common.manifest import Component
from grafi.nodes.conditions import always_true

# A package whose import leaves a mark, to tell whether it was imported.
_INIT = """
from pathlib import Path

Path(__file__).parent.with_name(__name__ + ".imported").touch()

VALUE = 42


def value() -> int:
    return VALUE
"""

_SUB = """
def answer() -> int:
    return 42
"""


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the test's trust_modules() calls when it ends."""
    monkeypatch.setattr(import_ref, "_trusted", import_ref._trusted)


@pytest.fixture
def package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trusted: None
) -> Iterator[str]:
    """The name of a throwaway package, importable but not trusted."""
    name = f"grafi_test_untrusted_{uuid.uuid4().hex}"
    (tmp_path / name).mkdir()
    (tmp_path / name / "__init__.py").write_text(_INIT)
    (tmp_path / name / "sub.py").write_text(_SUB)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield name
    for module in [m for m in sys.modules if m.split(".")[0] == name]:
        del sys.modules[module]


def _imported(package: str, tmp_path: Path) -> bool:
    return package in sys.modules or (tmp_path / f"{package}.imported").exists()


def test_resolves_a_module_attribute() -> None:
    assert resolve_import_ref("grafi.nodes.conditions:always_true") is always_true


def test_resolves_an_attribute_nested_on_a_class() -> None:
    ref = "grafi.common.manifest:Component.to_manifest"
    assert resolve_import_ref(ref) is Component.to_manifest


@pytest.mark.parametrize(
    "ref",
    ["", "grafi", "grafi.nodes.conditions", "grafi:", ":always_true", "os:"],
)
def test_malformed_reference_raises(ref: str) -> None:
    with pytest.raises(ValueError, match="Malformed import reference"):
        resolve_import_ref(ref)


def test_missing_module_or_attribute_of_a_trusted_module_raises() -> None:
    with pytest.raises(ImportError):
        resolve_import_ref("grafi.no_such_module:thing")
    with pytest.raises(AttributeError):
        resolve_import_ref("grafi.nodes.conditions:no_such_condition")


def test_grafi_and_its_submodules_are_trusted() -> None:
    assert is_trusted("grafi")
    assert is_trusted("grafi.tools.llms.impl.openai_tool")


@pytest.mark.parametrize("module", ["os", "json", "grafiti", "grafi_plugins"])
def test_other_modules_are_not_trusted(module: str) -> None:
    assert not is_trusted(module)


def test_untrusted_reference_raises_and_names_trust_modules() -> None:
    with pytest.raises(UntrustedImportError, match=r"trust_modules\('os'\)"):
        resolve_import_ref("os.path:join")
    assert issubclass(UntrustedImportError, ImportError)


def test_untrusted_module_is_never_imported(package: str, tmp_path: Path) -> None:
    with pytest.raises(UntrustedImportError):
        resolve_import_ref(f"{package}:value")
    with pytest.raises(UntrustedImportError):
        resolve_import_ref(f"{package}.sub:answer")
    assert not _imported(package, tmp_path)


def test_trusting_a_package_trusts_its_submodules(package: str, tmp_path: Path) -> None:
    trust_modules(package)

    assert resolve_import_ref(f"{package}:value")() == 42
    assert resolve_import_ref(f"{package}.sub:answer")() == 42
    assert _imported(package, tmp_path)
    with pytest.raises(UntrustedImportError, match="reaches|is not trusted"):
        resolve_import_ref(f"{package}:VALUE")  # Not a trusted module's own.
    assert not is_trusted(f"{package}_other")


def test_trusting_a_submodule_does_not_trust_its_package(
    package: str, tmp_path: Path
) -> None:
    trust_modules(f"{package}.sub")

    assert resolve_import_ref(f"{package}.sub:answer")() == 42
    with pytest.raises(UntrustedImportError):
        resolve_import_ref(f"{package}:value")


@pytest.mark.parametrize(
    "ref",
    [
        "grafi.common.manifest:os.system",  # Through a module it imported.
        "grafi.common.manifest:os",
        "grafi.nodes.node_base:logger",  # Another library's object.
        "grafi.common.manifest:API_VERSION",  # A constant, of no module.
        "grafi.common.manifest_v1:TOOL_CLASSES",
        "grafi.common.manifest:Component.model_config",
    ],
)
def test_names_only_what_a_trusted_module_defines(ref: str) -> None:
    with pytest.raises(UntrustedImportError, match="reaches|is not trusted"):
        resolve_import_ref(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "grafi.common.manifest:Component.__subclasses__",
        "grafi.common.manifest:Component.__init__",
        "grafi.nodes.conditions:always_true.__globals__",
    ],
)
def test_special_attributes_are_refused(ref: str) -> None:
    with pytest.raises(UntrustedImportError, match="names a special attribute"):
        resolve_import_ref(ref)


@pytest.mark.parametrize(
    "ref",
    ["grafi.__main__:main", "__main__:main", "grafi.tools.__init__:Tool", "__x:y"],
)
def test_special_modules_are_refused(ref: str) -> None:
    with pytest.raises(UntrustedImportError, match="names a special module"):
        resolve_import_ref(ref)


def test_a_trusted_package_runs_no_main_module(package: str, tmp_path: Path) -> None:
    """A package's __main__ runs a program when imported."""
    (tmp_path / package / "__main__.py").write_text(_INIT)
    trust_modules(package)

    with pytest.raises(UntrustedImportError, match="names a special module"):
        resolve_import_ref(f"{package}.__main__:value")
    assert not _imported(package, tmp_path)


def test_trusted_modules_are_replaced_whole(trusted: None) -> None:
    before = import_ref._trusted

    trust_modules("grafi_test_one", "grafi_test_two")

    assert isinstance(import_ref._trusted, frozenset)
    assert import_ref._trusted == before | {"grafi_test_one", "grafi_test_two"}
    assert "grafi_test_one" not in before  # A reader of it sees it whole.
    assert is_trusted("grafi_test_two.sub")


class _Nested:
    class Inner:
        pass


def _local() -> type:
    class Local:
        pass

    return Local


def test_reference_to_what_imports_back() -> None:
    assert reference_to(always_true) == "grafi.nodes.conditions:always_true"
    assert reference_to(Component) == "grafi.common.manifest:Component"
    assert reference_to(_Nested.Inner) == f"{__name__}:_Nested.Inner"
    assert reference_to(Component.to_manifest) == (
        "grafi.common.manifest:Component.to_manifest"
    )


@pytest.mark.parametrize(
    "obj",
    [
        _local(),
        lambda: None,
        type("Scripted", (), {"__module__": "__main__"}),
        type("Renamed", (), {"__module__": "grafi.common.manifest"}),
        42,
        "grafi.common.manifest:Component",
    ],
    ids=["local", "lambda", "__main__", "not found there", "int", "str"],
)
def test_no_reference_to_what_does_not_import_back(obj: object) -> None:
    assert reference_to(obj) is None


class Holder:
    @classmethod
    def build(cls) -> str:
        return cls.__name__

    @staticmethod
    def helper() -> int:
        return 1


def test_a_classmethod_is_refused_and_a_staticmethod_named() -> None:
    with pytest.raises(UntrustedImportError, match="names a classmethod"):
        resolve_import_ref(f"{__name__}:Holder.build")
    assert resolve_import_ref(f"{__name__}:Holder.helper")() == 1


@functools.cache
def cached() -> int:
    return 1


def test_only_what_loading_names_has_a_reference() -> None:
    """A callable that is not a plain function, such as a cached one, has no
    reference, so saving it fails at once rather than loading later."""
    assert reference_to(cached) is None
    assert reference_to(Holder) == f"{__name__}:Holder"
    assert reference_to(Holder.helper) == f"{__name__}:Holder.helper"


@pytest.mark.parametrize(
    "planted, ref",
    [
        ("grafi/planted.py", "grafi.planted:Evil"),  # A module grafi lacks.
        ("grafi/agents/__init__.py", "grafi.agents:Evil"),  # A package it has.
        ("grafi/agents/React_Agent.py", "grafi.agents.React_Agent:Evil"),  # Case.
    ],
)
def test_a_grafi_module_from_elsewhere_on_the_path_is_never_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: str, ref: str
) -> None:
    """grafi is a regular package, so only its own directory holds its
    modules: a grafi/ directory elsewhere on the path adds none."""
    marker = tmp_path / "imported"
    path = tmp_path / planted
    path.parent.mkdir(parents=True)
    path.write_text(f"open({str(marker)!r}, 'w').close()\nclass Evil: ...\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises((ImportError, AttributeError)):
        resolve_import_ref(ref)
    assert not marker.exists()

