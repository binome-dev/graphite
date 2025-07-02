import os
from typing import Callable

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleMultiLLMAssistant(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleMultiLLMAssistant")
    type: str = Field(default="SimpleMultiLLMAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    model_openai: str = Field(default="openai/gpt-4o-mini")
    model_deepseek: str = Field(default="deepseek/deepseek-chat-v3-0324:free")
    model_gemini: str = Field(default="google/gemini-2.0-flash-001")
    model_qwen: str = Field(default="qwen/qwen3-235b-a22b")
    openai_function: Callable
    deepseek_function: Callable
    gemini_function: Callable
    qwen_function: Callable
    human_request_process_function: Callable

    def _construct_workflow(self) -> "SimpleMultiLLMAssistant":
        openai_function_call_topic = Topic(name="openai_function_call_topic")
        deepseek_function_call_topic = Topic(name="deepseek_function_call_topic")
        gemini_function_call_topic = Topic(name="gemini_function_call_topic")
        qwen_function_call_topic = Topic(name="qwen_function_call_topic")

        # Create input LLM nodes
        openai_llm_node = (
            Node.builder()
            .name("OpenAIInputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenRouterTool.builder()
                .name("OpenAIInputLLM")
                .api_key(self.api_key)
                .model(self.model_openai)
                .build()
            )
            .publish_to(openai_function_call_topic)
            .build()
        )

        deepseek_llm_node = (
            Node.builder()
            .name("DeepSeekInputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenRouterTool.builder()
                .name("DeepSeekInputLLM")
                .api_key(self.api_key)
                .model(self.model_deepseek)
                .build()
            )
            .publish_to(deepseek_function_call_topic)
            .build()
        )

        gemini_llm_node = (
            Node.builder()
            .name("GeminiInputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenRouterTool.builder()
                .name("GeminiInputLLM")
                .api_key(self.api_key)
                .model(self.model_gemini)
                .build()
            )
            .publish_to(gemini_function_call_topic)
            .build()
        )

        qwen_llm_node = (
            Node.builder()
            .name("QwenInputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenRouterTool.builder()
                .name("QwenInputLLM")
                .api_key(self.api_key)
                .model(self.model_qwen)
                .build()
            )
            .publish_to(qwen_function_call_topic)
            .build()
        )

        # Create function call nodes
        openai_function_node = (
            Node.builder()
            .name("OpenAINode")
            .type("FunctionNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(openai_function_call_topic).build()
            )
            .tool(
                FunctionTool.builder()
                .name("OpenAIInputFunctionTool")
                .function(self.openai_function)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        deepseek_function_node = (
            Node.builder()
            .name("DeepSeekNode")
            .type("FunctionNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(deepseek_function_call_topic)
                .build()
            )
            .tool(
                FunctionTool.builder()
                .name("DeepSeekFunctionTool")
                .function(self.deepseek_function)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        gemini_function_node = (
            Node.builder()
            .name("GeminiNode")
            .type("FunctionNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(gemini_function_call_topic).build()
            )
            .tool(
                FunctionTool.builder()
                .name("GeminiFunctionTool")
                .function(self.gemini_function)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        qwen_function_node = (
            Node.builder()
            .name("QwenNode")
            .type("FunctionNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(qwen_function_call_topic).build()
            )
            .tool(
                FunctionTool.builder()
                .name("QwenFunctionTool")
                .function(self.qwen_function)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        human_request_process_node = (
            Node.builder()
            .name("HumanRequestProcessNode")
            .type("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(human_request_topic).build())
            .tool(
                FunctionTool.builder()
                .name("HumanRequestProcessTool")
                .function(self.human_request_process_function)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_OpenRouter_function_call_workflow")
            .node(openai_llm_node)
            .node(openai_function_node)
            .node(deepseek_llm_node)
            .node(deepseek_function_node)
            .node(gemini_llm_node)
            .node(gemini_function_node)
            .node(qwen_llm_node)
            .node(qwen_function_node)
            .node(human_request_process_node)
            .build()
        )

        return self
