"""Tools are saved as data and loaded back polymorphically: ``model_dump`` names
a tool's class by import path, and ``Tool.model_validate`` builds that class,
grafi's or the user's, from trusted modules only."""

import json
import sys
from pathlib import Path
from typing import Any
from typing import Dict

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic_core import PydanticSerializationError

from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.llms.llm import LLM
from grafi.tools.tool import Tool


class WeatherTool(Tool):
    """A user's tool, defined outside grafi, with a field of its own."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    units: str = "celsius"


class TunedOpenAITool(OpenAITool):
    """A user's subclass of a grafi LLM, with a field of its own."""

    temperature_hint: float = 0.2


# --------------------------------------------------------------------------- #
#  Built-in tools load by import path                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path,cls,fields",
    [
        (
            "grafi.tools.llms.impl.openai_tool:OpenAITool",
            OpenAITool,
            {"model": "gpt-4o-mini", "reasoning_effort": "low"},
        ),
        (
            "grafi.tools.llms.impl.claude_tool:ClaudeTool",
            ClaudeTool,
            {"model": "claude-haiku-4-5", "max_tokens": 4096},
        ),
        (
            "grafi.tools.llms.impl.deepseek_tool:DeepseekTool",
            DeepseekTool,
            {"base_url": "https://deepseek.example/v1"},
        ),
        (
            "grafi.tools.llms.impl.gemini_tool:GeminiTool",
            GeminiTool,
            {"thinking_budget": 128},
        ),
        (
            "grafi.tools.llms.impl.ollama_tool:OllamaTool",
            OllamaTool,
            {"api_url": "http://ollama:11434"},
        ),
        (
            "grafi.tools.llms.impl.openrouter_tool:OpenRouterTool",
            OpenRouterTool,
            {"extra_headers": {"X-Title": "grafi"}},
        ),
        (
            "grafi.tools.function_calls.impl.duckduckgo_tool:DuckDuckGoTool",
            DuckDuckGoTool,
            {"timeout": 15},
        ),
        (
            "grafi.tools.function_calls.impl.google_search_tool:GoogleSearchTool",
            GoogleSearchTool,
            {"fixed_language": "fr"},
        ),
        (
            "grafi.tools.function_calls.impl.tavily_tool:TavilyTool",
            TavilyTool,
            {"search_depth": "basic"},
        ),
    ],
)
def test_a_built_in_tool_loads_as_the_class_its_path_names(
    path: str, cls: type, fields: Dict[str, Any]
) -> None:
    tool = Tool.model_validate(
        {"class": path, "tool_id": "test-id", "name": "Named", **fields}
    )

    assert type(tool) is cls
    assert tool.tool_id == "test-id"
    assert tool.name == "Named"
    for name, value in fields.items():
        assert getattr(tool, name) == value


MCP_CONFIG = {"mcpServers": {"s": {"url": "http://localhost:1"}}}


@pytest.mark.parametrize(
    "cls,fields",
    [
        (OpenAITool, {}),
        (ClaudeTool, {}),
        (DeepseekTool, {}),
        (GeminiTool, {}),
        (OllamaTool, {}),
        (OpenRouterTool, {}),
        (DuckDuckGoTool, {}),
        (GoogleSearchTool, {}),
        (TavilyTool, {}),
        (FunctionCallTool, {}),
        (MCPTool, {"mcp_config": MCP_CONFIG}),
        (MCPFunctionTool, {"mcp_config": MCP_CONFIG, "function_name": "search"}),
    ],
    ids=lambda param: param.__name__ if isinstance(param, type) else "",
)
def test_a_built_in_tool_round_trips_through_the_base_class(
    cls: Any, fields: Dict[str, Any]
) -> None:
    tool = cls(**fields)  # A key, if any, from its variable, as the default.
    data = tool.model_dump(mode="json")
    assert data["class"] == f"{cls.__module__}:{cls.__qualname__}"
    assert list(data)[0] == "class"
    json.dumps(data)  # Plain JSON.

    restored = Tool.model_validate(data)

    assert type(restored) is cls
    assert restored.tool_id == tool.tool_id
    assert restored.model_dump(mode="json") == data


# --------------------------------------------------------------------------- #
#  A user's subclass loads as itself                                           #
# --------------------------------------------------------------------------- #
def test_a_user_tool_loads_as_itself_with_its_own_field() -> None:
    tool = WeatherTool(name="weather", units="kelvin")
    data = tool.model_dump(mode="json")
    assert data == {
        "class": f"{__name__}:WeatherTool",
        "tool_id": tool.tool_id,
        "name": "weather",
        "type": None,
        "oi_span_type": "TOOL",
        "units": "kelvin",
    }

    restored = Tool.model_validate(data)

    assert type(restored) is WeatherTool
    assert restored == tool


@pytest.mark.parametrize("base", [Tool, LLM, OpenAITool, TunedOpenAITool])
def test_a_user_subclass_loads_as_itself_through_any_of_its_bases(base: Any) -> None:
    tool = TunedOpenAITool(model="gpt-5-mini", temperature_hint=0.9)

    restored = base.model_validate(tool.model_dump(mode="json"))

    assert type(restored) is TunedOpenAITool
    assert restored.temperature_hint == 0.9
    assert restored == tool


def test_without_a_class_the_class_called_is_loaded() -> None:
    tool = OpenAITool.model_validate({"model": "gpt-4o"})

    assert type(tool) is OpenAITool
    assert tool.model == "gpt-4o"


def test_a_tool_manifest_names_its_kind_and_loads_back(tmp_path: Path) -> None:
    tool = WeatherTool(name="weather", units="kelvin")

    manifest = tool.to_manifest()

    assert manifest == {
        "apiVersion": "grafi/v2",
        "kind": "Tool",
        "spec": tool.model_dump(mode="json"),
    }
    assert Tool.from_manifest(manifest) == tool
    path = tmp_path / "weather_tool.json"
    path.write_text(json.dumps(manifest))
    assert Tool.from_manifest(path) == tool


def test_a_tool_manifest_of_another_kind_fails() -> None:
    manifest = {**WeatherTool().to_manifest(), "kind": "Workflow"}

    with pytest.raises(
        ManifestError,
        match="The manifest's kind is 'Workflow', but its spec is of kind 'Tool'.",
    ):
        Tool.from_manifest(manifest)
    with pytest.raises(ManifestError, match="kind is None"):
        Tool.from_manifest({k: v for k, v in manifest.items() if k != "kind"})


def test_a_tool_manifest_reads_its_key_from_its_own_variable_or_one_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "own-key")
    monkeypatch.setenv("TEAM_OPENAI_KEY", "team-key")
    manifest = OpenAITool().to_manifest()
    assert manifest["spec"]["api_key"] == {"env": "OPENAI_API_KEY"}
    assert Tool.from_manifest(manifest).api_key == "own-key"

    manifest["spec"]["api_key"] = {"env": "TEAM_OPENAI_KEY"}
    with pytest.raises(ManifestError, match=r"env=\['TEAM_OPENAI_KEY'\]"):
        Tool.from_manifest(manifest)
    tool = Tool.from_manifest(manifest, allow_env=["TEAM_OPENAI_KEY"])
    assert tool.api_key == "team-key"
    assert tool.to_manifest()["spec"]["api_key"] == {"env": "TEAM_OPENAI_KEY"}

    manifest["spec"]["api_key"] = "sk-literal"
    with pytest.raises(ManifestError, match="never holds a secret"):
        Tool.from_manifest(manifest)


# --------------------------------------------------------------------------- #
#  A class that is not to be loaded fails loudly                               #
# --------------------------------------------------------------------------- #
def test_a_class_outside_the_trusted_modules_is_never_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = "untrusted_tool_plugin"
    (tmp_path / f"{module}.py").write_text(
        "from grafi.tools.tool import Tool\n\n\nclass PluginTool(Tool):\n"
        "    oi_span_type: str = 'TOOL'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))  # Importable, but not trusted.

    with pytest.raises(UntrustedImportError, match="outside the trusted modules"):
        Tool.model_validate({"class": f"{module}:PluginTool"})

    assert module not in sys.modules


def test_a_standard_library_class_is_not_trusted() -> None:
    with pytest.raises(UntrustedImportError):
        Tool.model_validate({"class": "collections:OrderedDict"})


@pytest.mark.parametrize(
    "path,message",
    [
        ("grafi.tools.llms.impl.openai_tool:NoSuchTool", "Cannot import"),
        ("grafi.tools.no_such_module:SomeTool", "Cannot import"),
        ("grafi.topics.topic_impl.topic:Topic", "is not a subclass of Tool"),
        ("grafi.tools.tool:ToolBuilder", "is not a subclass of Tool"),
        ("grafi.common.manifest:import_path", "is not a subclass of Tool"),
        (f"{__name__}:WeatherTool.units", "Cannot import"),
    ],
)
def test_an_unknown_or_non_tool_class_fails_loudly(path: str, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        Tool.model_validate({"class": path, "name": "x"})


def test_a_tool_of_another_kind_than_the_class_called_fails() -> None:
    with pytest.raises(ManifestError, match="is not a subclass of LLM"):
        LLM.model_validate(TavilyTool().model_dump(mode="json"))
    with pytest.raises(ManifestError, match="is not a subclass of ClaudeTool"):
        ClaudeTool.model_validate(OpenAITool().model_dump(mode="json"))
    with pytest.raises(ManifestError, match="is not a subclass of LLM"):
        LLM.from_manifest(WeatherTool().to_manifest())


@pytest.mark.parametrize("path", [42, None, {"name": "OpenAITool"}])
def test_a_class_not_named_by_a_string_fails(path: Any) -> None:
    with pytest.raises(ManifestError, match="must be named by its import path"):
        Tool.model_validate({"class": path, "name": "x"})


def test_a_bare_class_name_fails() -> None:
    # The old ToolFactory format; from_manifest upgrades a whole old manifest,
    # but model_validate takes import paths only.
    with pytest.raises((ManifestError, ValueError), match="OpenAITool"):
        Tool.model_validate({"class": "OpenAITool", "name": "x"})


# --------------------------------------------------------------------------- #
#  A secret set in code fails to save                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cls,var",
    [
        (OpenAITool, "OPENAI_API_KEY"),
        (ClaudeTool, "ANTHROPIC_API_KEY"),
        (DeepseekTool, "DEEPSEEK_API_KEY"),
        (GeminiTool, "GEMINI_API_KEY"),
        (OpenRouterTool, "OPENROUTER_API_KEY"),
        (TavilyTool, "TAVILY_API_KEY"),
    ],
)
def test_a_key_set_in_code_raises_manifest_error_on_save(
    monkeypatch: pytest.MonkeyPatch, cls: Any, var: str
) -> None:
    monkeypatch.setenv(var, "the_env_key")
    tool = cls(api_key="sk-set-in-code")

    with pytest.raises(PydanticSerializationError) as caught:
        tool.model_dump(mode="json")
    assert isinstance(caught.value.__cause__, ManifestError)
    with pytest.raises(ManifestError, match=f"{cls.__name__}.api_key"):
        tool.to_manifest()

    monkeypatch.setenv(var, "sk-set-in-code")  # Now its variable's value.
    assert tool.to_manifest()["spec"]["api_key"] == {"env": var}
