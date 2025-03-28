import os
import uuid

from multi_functions_call_assistant import MultiFunctionsCallAssistant

from grafi.common.containers.container import event_store
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool

api_key = os.getenv("OPENAI_API_KEY")


class WeatherMock(FunctionTool):
    name: str = "WeatherMock"

    @llm_function
    def get_weather_mock(self, postcode: str):
        """
        Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: A string containing a weather report for the given postcode.
        """
        return f"The weather of {postcode} is bad now."


class PopulationMock(FunctionTool):
    name: str = "PopulationMock"

    @llm_function
    def get_population_mock(self, postcode: str):
        """
        Function to get population information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve population information.

        Returns:
            str: A string containing a population report for the given postcode.
        """
        return f"The population of {postcode} is about 100,000 at this moment."


class HousePriceMock(FunctionTool):
    name: str = "HousePriceMock"

    @llm_function
    def get_house_price_mock(self, postcode: str):
        """
        Function to get house price information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve house price information.

        Returns:
            str: A string containing a house price report for the given postcode.
        """
        return f"The house price of {postcode} is about 250,000 in this year."


def get_execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


user_input_system_message = """"
You are an intelligent assistant with access to several specialized tools. Each tool is designed to answer specific types of questions or perform specialized tasks. Your goal is to evaluate the user's request and determine the most relevant tool to use. If you can match the request to a tool, select it and provide a solution using that tool. If none of the available tools is suitable for the request, respond with a polite message stating that you cannot help with the current query.

Instructions:
1. Carefully analyze the user's prompt and determine the type of request.
2. Select the most appropriate tool based on the request.
3. If no available tool matches the request, respond with: "I'm sorry, but I cannot assist with that request."
4. Only call tools that are specifically relevant to the user's query to avoid unnecessary or irrelevant tool usage.
5. Always strive to provide a helpful and accurate response when a relevant tool is available.
"""

user_output_system_message = """
You are a friendly and helpful assistant with access to multiple tools. After get response from most recent tool, your job is to explain the tool result in a clear, concise, and supportive manner. Your response should ensure the user feels informed, understood, and reassured. If tool fails to provide a satisfactory result, acknowledge it politely and offer helpful guidance if possible.

### Instructions:
1. Collect and explain the results from **MOST RECENT** valid tool's response.
2. Use a warm, supportive tone to ensure the user feels reassured and guided through the process.
3. If any tool couldn't fulfill the request, acknowledge it and provide alternatives or next steps when possible.
4. Always focus on providing a positive and helpful experience for the user.
### Example Response:
1. If all tools succeed: "Here's what I've found for you: [summary of results]. I hope this helps! If you need more information, feel free to ask!"
2. If some tools fail: "It looks like I was able to find some information for you: [summary of results]. However, there are a few things I couldn't find at the moment. Let me know if you'd like me to help in another way!"
"""


def test_multi_functions_call_assistant():
    assistant = (
        MultiFunctionsCallAssistant.Builder()
        .name("MultiFunctionsCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock())
        .function_tool(PopulationMock())
        .function_tool(HousePriceMock())
        .function_call_llm_system_message(user_input_system_message)
        .summary_llm_system_message(user_output_system_message)
        .build()
    )

    # Test the run method

    execution_context_1 = get_execution_context()
    input_question_1 = [
        Message(role="user", content="Hello, how's the weather in 12345?")
    ]

    output = assistant.execute(execution_context_1, input_question_1)

    print(output)
    print(len(event_store.get_events()))
    assert output is not None
    assert len(event_store.get_events()) == 33

    # Test the run method
    execution_context_2 = get_execution_context()
    input_question_2 = [
        Message(role="user", content="Hello, how's the population in 12345?"),
    ]

    output = assistant.execute(execution_context_2, input_question_2)

    print(output)
    assert output is not None
    assert len(event_store.get_events()) == 66

    # Test the run method
    execution_context_3 = get_execution_context()
    input_question_3 = [
        Message(role="user", content="Hello, how's the house price in 12345?"),
    ]

    output = assistant.execute(execution_context_3, input_question_3)
    print(output)
    assert output is not None
    assert len(event_store.get_events()) == 99

    # assistant.generate_workflow_graph()


test_multi_functions_call_assistant()
