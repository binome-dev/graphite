"""
Tests for the LLM base class: function specs, and how chat_params are saved.
"""

import json
import re
from typing import Optional
from typing import Type
from unittest.mock import Mock

import pytest
from openai import Omit
from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from grafi.common.exceptions import LLMToolException
from grafi.common.import_ref import UntrustedImportError
from grafi.common.manifest import ManifestError
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.llms.llm import LLM
from grafi.tools.tool import Tool


def _spec(name: str) -> FunctionSpec:
    return FunctionSpec(
        name=name,
        description=f"{name} description",
        parameters=ParametersSchema(type="object", properties={}),
    )


class TestAddFunctionSpecs:
    """add_function_specs must be idempotent (deduped by name)."""

    def test_specs_deduped_across_calls(self):
        llm = LLM()
        llm.add_function_specs([_spec("get_weather")])
        # Re-linking the same spec (as model_post_init does on every round-trip)
        # must not duplicate it.
        llm.add_function_specs([_spec("get_weather")])
        names = [s.name for s in llm.get_function_specs()]
        assert names == ["get_weather"]

    def test_specs_deduped_within_a_call(self):
        llm = LLM()
        llm.add_function_specs([_spec("a"), _spec("b"), _spec("a")])
        names = sorted(s.name for s in llm.get_function_specs())
        assert names == ["a", "b"]

    def test_distinct_specs_all_added(self):
        llm = LLM()
        llm.add_function_specs([_spec("a")])
        llm.add_function_specs([_spec("b")])
        names = sorted(s.name for s in llm.get_function_specs())
        assert names == ["a", "b"]


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    age: int


class NestedModel(BaseModel):
    """Nested Pydantic model for testing."""

    user: SampleModel
    active: bool


class TestChatParamsSaving:
    """A pydantic model class in chat_params, such as a ``response_format``, is
    saved as its import path and loaded back as the same class."""

    def test_a_response_format_class_is_saved_as_its_import_path(self):
        llm = LLM(
            model="test-model",
            chat_params={"response_format": SampleModel, "temperature": 0.7},
        )

        data = llm.model_dump(mode="json")

        assert data["chat_params"] == {
            "response_format": {"ref": f"{__name__}:SampleModel"},
            "temperature": 0.7,
        }
        json.dumps(data)  # Plain JSON.
        # A python-mode dump keeps the class itself.
        assert llm.model_dump()["chat_params"]["response_format"] is SampleModel

    def test_a_response_format_class_round_trips_as_the_same_class(self):
        llm = LLM(
            model="test-model",
            chat_params={"response_format": NestedModel, "max_tokens": 100},
            structured_output=True,
        )
        data = llm.model_dump(mode="json")

        restored = Tool.model_validate(data)

        assert type(restored) is LLM
        assert restored.tool_id == llm.tool_id
        assert restored.chat_params == {
            "response_format": NestedModel,
            "max_tokens": 100,
        }
        assert restored.chat_params["response_format"] is NestedModel
        assert restored.structured_output is True
        assert restored.model_dump(mode="json") == data

    def test_model_classes_nested_in_dicts_and_lists_round_trip(self):
        params = {
            "formats": [SampleModel, NestedModel],
            "advanced": {"response_format": SampleModel, "temperature": 0.5},
            "stop": ["a", "b"],
        }
        llm = LLM(model="test-model", chat_params=params)
        data = llm.model_dump(mode="json")

        assert data["chat_params"] == {
            "formats": [
                {"ref": f"{__name__}:SampleModel"},
                {"ref": f"{__name__}:NestedModel"},
            ],
            "advanced": {
                "response_format": {"ref": f"{__name__}:SampleModel"},
                "temperature": 0.5,
            },
            "stop": ["a", "b"],
        }
        assert LLM.model_validate(data).chat_params == params

    def test_plain_params_are_saved_as_they_are(self):
        params = {"temperature": 0.7, "top_p": 0.9, "seed": None, "stop": ["x"]}
        llm = LLM(model="test-model", chat_params=params)

        assert llm.model_dump(mode="json")["chat_params"] == params
        assert LLM.model_validate(llm.model_dump(mode="json")).chat_params == params

    def test_a_model_class_from_an_untrusted_module_is_not_loaded(self):
        data = {"chat_params": {"response_format": {"ref": "json:JSONDecoder"}}}

        with pytest.raises(UntrustedImportError):
            LLM.model_validate(data)

    def test_a_model_class_that_is_not_a_pydantic_model_is_not_loaded(self):
        data = {
            "chat_params": {
                "response_format": {"ref": "grafi.tools.llms.llm:LLMBuilder"}
            }
        }

        with pytest.raises(ManifestError, match="is not a subclass of BaseModel"):
            LLM.model_validate(data)


class TestChatParamsSecrets:
    """A secret in chat_params, at any depth, is never saved."""

    @pytest.mark.parametrize(
        "params,held",
        [
            (
                {"extra_headers": {"Authorization": "Bearer sk-literal"}},
                "Authorization",
            ),
            ({"extra_headers": {"X-Api-Key": "literal"}}, "X-Api-Key"),
            ({"extra_body": {"auth": [{"access_token": "literal"}]}}, "auth"),
            ({"api_key": "sk-literal"}, "api_key"),
        ],
    )
    def test_a_secret_held_as_a_value_is_never_saved(self, params, held):
        llm = LLM(model="m", chat_params=params)

        with pytest.raises(PydanticSerializationError, match="ManifestError"):
            llm.model_dump(mode="json")
        match = f"LLM.chat_params holds a secret, at '{held}'"
        with pytest.raises(ManifestError, match=match):
            llm.to_manifest()

    def test_a_reference_to_a_variable_and_names_not_of_secrets_are_saved(self):
        params = {
            "extra_headers": {"Authorization": "Bearer ${MY_TOKEN}", "X-Title": "t"},
            "max_tokens": 100,
            "cache_key": "k",
            "eos_token": "</s>",
        }
        llm = LLM(model="m", chat_params=params)

        assert llm.to_manifest()["spec"]["chat_params"] == params

    def test_a_python_dump_keeps_the_values(self):
        params = {"extra_headers": {"Authorization": "Bearer sk-literal"}}
        llm = LLM(model="m", chat_params=params)

        assert llm.model_dump()["chat_params"] == params


class TestBaseLLMKey:
    """The base LLM's key has no variable of its own."""

    def test_an_unset_key_is_saved_as_none(self):
        assert LLM(model="m").model_dump(mode="json")["api_key"] is None

    def test_a_key_set_in_code_is_never_saved(self):
        llm = LLM(model="m", api_key="sk-literal")

        with pytest.raises(PydanticSerializationError, match="ManifestError"):
            llm.model_dump(mode="json")
        with pytest.raises(ManifestError, match="LLM.api_key"):
            llm.to_manifest()
        assert "sk-literal" not in repr(llm)

    def test_a_key_named_by_its_variable_is_read_and_saved_as_it(self, monkeypatch):
        monkeypatch.setenv("MY_LLM_KEY", "from-env")

        llm = LLM.model_validate({"model": "m", "api_key": {"env": "MY_LLM_KEY"}})

        assert llm.api_key == "from-env"
        assert llm.model_dump(mode="json")["api_key"] == {"env": "MY_LLM_KEY"}


class TestRequiredApiKey:
    """An OpenAI-compatible tool given no key raises, naming its variable,
    before the OpenAI SDK is called: the SDK would read OPENAI_API_KEY, perhaps
    another provider's, and send it wherever base_url points."""

    OPENAI_CLIENT = "grafi.tools.llms.impl.openai_compatible.AsyncClient"

    @pytest.mark.parametrize(
        "tool_class, variable, foreign, client",
        [
            (OpenAITool, "OPENAI_API_KEY", None, OPENAI_CLIENT),
            (DeepseekTool, "DEEPSEEK_API_KEY", "OPENAI_API_KEY", OPENAI_CLIENT),
            (OpenRouterTool, "OPENROUTER_API_KEY", "OPENAI_API_KEY", OPENAI_CLIENT),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_provider_without_a_key_raises_before_building_a_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        invoke_context: InvokeContext,
        tool_class: Type[LLM],
        variable: str,
        foreign: Optional[str],
        client: str,
    ) -> None:
        monkeypatch.delenv(variable, raising=False)
        if foreign is not None:  # Another provider's, which its SDK reads.
            monkeypatch.setenv(foreign, "sk-another-providers-key")
        sdk_client = Mock()
        monkeypatch.setattr(client, sdk_client)
        tool = tool_class()
        match = re.escape(f"{tool_class.__name__} has no API key: set {variable}.")

        with pytest.raises(LLMToolException, match=match) as raised:
            async for _ in tool.invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass
        assert raised.value.tool_name == tool.name
        sdk_client.assert_not_called()

    def test_the_key_is_given_when_set(self) -> None:
        assert OpenAITool(api_key="sk-given").required_api_key() == "sk-given"

    def test_a_key_set_after_the_tool_was_made_is_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        tool = OpenAITool()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-later")

        assert tool.required_api_key() == "sk-later"

    def test_a_key_read_from_another_variable_is_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEAM_OPENAI_KEY", raising=False)
        tool = OpenAITool.model_validate({"api_key": {"env": "TEAM_OPENAI_KEY"}})

        with pytest.raises(LLMToolException, match="set TEAM_OPENAI_KEY"):
            tool.required_api_key()

    @pytest.mark.parametrize("tool_class", [DeepseekTool, OpenRouterTool])
    @pytest.mark.asyncio
    async def test_another_provider_gets_none_of_openais_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        invoke_context: InvokeContext,
        tool_class: Type[LLM],
    ) -> None:
        """The OpenAI SDK makes headers from OpenAI's variables: another
        provider's base_url is sent none of them."""
        monkeypatch.setenv("OPENAI_ORG_ID", "org-fake")
        monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "X-Gateway-Key: fake-secret")
        sdk_client = Mock(side_effect=RuntimeError("stop"))
        monkeypatch.setattr(self.OPENAI_CLIENT, sdk_client)

        with pytest.raises(Exception):
            async for _ in tool_class(api_key="sk-own").invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass

        headers = dict(sdk_client.call_args.kwargs["default_headers"])
        assert headers.pop("Authorization") == "Bearer sk-own"
        assert set(headers) == {
            "OpenAI-Organization",
            "OpenAI-Project",
            "X-Gateway-Key",
        }
        assert all(isinstance(value, Omit) for value in headers.values())

    @pytest.mark.asyncio
    async def test_another_providers_key_is_sent_whatever_openais_headers_name(
        self, monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
    ) -> None:
        monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: Bearer proxy")
        sdk_client = Mock(side_effect=RuntimeError("stop"))
        monkeypatch.setattr(self.OPENAI_CLIENT, sdk_client)

        with pytest.raises(Exception):
            async for _ in DeepseekTool(api_key="ds-key").invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass

        headers = sdk_client.call_args.kwargs["default_headers"]
        assert headers["Authorization"] == "Bearer ds-key"

    @pytest.mark.asyncio
    async def test_another_provider_needs_its_base_url(
        self, monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
    ) -> None:
        """Without one, the SDK would read OPENAI_BASE_URL."""
        sdk_client = Mock()
        monkeypatch.setattr(self.OPENAI_CLIENT, sdk_client)

        with pytest.raises(LLMToolException, match="DeepseekTool has no base_url"):
            async for _ in DeepseekTool(api_key="ds-key", base_url=None).invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass
        sdk_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_openai_keeps_its_own_settings(
        self, monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
    ) -> None:
        sdk_client = Mock(side_effect=RuntimeError("stop"))
        monkeypatch.setattr(self.OPENAI_CLIENT, sdk_client)

        with pytest.raises(Exception):
            async for _ in OpenAITool(api_key="sk-own").invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass

        assert "default_headers" not in sdk_client.call_args.kwargs

    def test_gemini_without_a_key_lets_its_sdk_use_googles_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Google's SDK reads GOOGLE_API_KEY, or Vertex AI's credentials."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        sdk_client = Mock()
        monkeypatch.setattr("google.genai.Client", sdk_client)

        GeminiTool()._client()

        sdk_client.assert_called_once_with(api_key=None)

    def test_a_key_without_a_variable_names_none(self) -> None:
        with pytest.raises(LLMToolException, match=r"LLM has no API key\.$"):
            LLM(model="m").required_api_key()


@pytest.mark.asyncio
async def test_tool_results_follow_their_calls_in_the_calls_order() -> None:
    # Some providers, such as Ollama, match results to calls by position.
    from grafi.common.events.topic_events.consume_from_topic_event import (
        ConsumeFromTopicEvent,
    )
    from grafi.common.models.invoke_context import InvokeContext
    from grafi.common.models.message import Message
    from grafi.tools.llms.impl.openai_tool import OpenAITool
    from grafi.tools.llms.llm_command import LLMCommand

    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )
    calls = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": f"c{n}",
                    "type": "function",
                    "function": {"name": "f", "arguments": "{}"},
                }
                for n in (1, 2, 3)
            ],
        }
    )
    results = [
        Message(role="tool", tool_call_id=f"c{n}", content=str(n)) for n in (3, 1, 2)
    ]
    consumed = [ConsumeFromTopicEvent(invoke_context=context, data=[calls, *results])]
    messages = await LLMCommand(tool=OpenAITool(api_key="k")).get_tool_input(
        context, consumed
    )
    assert [message.tool_call_id for message in messages] == [None, "c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_a_message_consumed_from_several_topics_is_in_the_history_once() -> None:
    from grafi.common.events.topic_events.consume_from_topic_event import (
        ConsumeFromTopicEvent,
    )
    from grafi.common.models.invoke_context import InvokeContext
    from grafi.common.models.message import Message
    from grafi.tools.llms.impl.openai_tool import OpenAITool
    from grafi.tools.llms.llm_command import LLMCommand

    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )
    question = Message(role="user", content="?")
    copies = [
        ConsumeFromTopicEvent(
            invoke_context=context, name=name, data=[question.model_copy(deep=True)]
        )
        for name in ("t1", "t2")
    ]
    messages = await LLMCommand(tool=OpenAITool(api_key="k")).get_tool_input(
        context, copies
    )
    assert [message.message_id for message in messages] == [question.message_id]
