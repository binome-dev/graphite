import json
import os
import uuid
from pathlib import Path

from react_assistant import ReActAssistant
from tools.tavily_tool import TavilyTool

from grafi.common.containers.container import event_store
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

api_key = os.getenv("OPENAI_API_KEY")
tavily_api_key = os.getenv("TAIVLY_API_KEY")

observation_llm_system_message = """
You are an AI assistant that records and reports the results obtained from executed actions. 
After performing an action, provide a clear and concise summary of the findings relevant to the user's question.
"""
thought_llm_system_message = """
You are an AI assistant tasked with analyzing the user's question and considering the provided observation to determine the next logical step required to answer the question. 
Your response should describe what would be the most effective action to take based on the information gathered.
If the information is sufficient to answer the question, return the answer with confirmation the answer is ready.
"""
action_llm_system_message = """
You are an AI assistant responsible for executing actions based on a given plan to retrieve information. 
Specify the appropriate action to take, such as performing a search query or accessing a specific resource, to gather the necessary data.
If answer is ready, return **FINISH REACT**. 
"""
summary_llm_system_message = """
You are an AI assistant tasked with summarizing the findings from previous observations to provide a clear and accurate answer to the user's question. 
Ensure the summary directly addresses the query based on the information gathered.
"""


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# mock events
def load_events_from_json() -> ExecutionContext:
    # Load events from JSON file
    with open(Path(__file__).parent / "react_events_unfinished.json", "r") as f:
        events_data = json.load(f)

    # Clear any existing events
    event_store.clear_events()

    # Convert each event dict to Event object and store it
    for event_dict in events_data:
        event = event_store._create_event_from_dict(event_dict)
        event_store.record_event(event)
        execution_context = event.execution_context

    return execution_context


def test_react_assistant():
    execution_context = load_events_from_json()

    # Set up the assistant with DuckDuckGoTool
    assistant = (
        ReActAssistant.Builder()
        .name("ReActAssistant")
        .api_key(api_key)
        .observation_llm_system_message(observation_llm_system_message)
        .thought_llm_system_message(thought_llm_system_message)
        .action_llm_system_message(action_llm_system_message)
        .summary_llm_system_message(summary_llm_system_message)
        .search_tool(
            TavilyTool.Builder()
            .name("TavilyTestTool")
            .api_key(tavily_api_key)
            .max_tokens(6000)
            .search_depth("advanced")
            .build()
        )
        .build()
    )

    input_data = [
        Message(
            role="user",
            content="What is the elevation range for the area that the eastern sector of the Colorado orogeny extends into?",
        )
    ]

    # Execute the assistant's function call
    output = assistant.execute(execution_context, input_data)
    print("Assistant output:", output)

    # Assert that the output is valid and check event count

    # assistant.generate_workflow_graph()
    # assistant.generate_manifest()


test_react_assistant()
