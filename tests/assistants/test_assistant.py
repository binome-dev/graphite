import json
import os
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.models.message import Message
from grafi.workflows.workflow import Workflow


class TestAssistant:
    @pytest.fixture
    def mock_assistant(self):
        # Create a mock Workflow class instance
        mock_workflow = Mock(spec=Workflow)

        assistant = Assistant(
            name="test_assistant",
            type="test_type",
            oi_span_type=OpenInferenceSpanKindValues.AGENT,
            workflow=mock_workflow,
        )
        return assistant

    @pytest.fixture
    def input_messages(self):
        return [Message(content="test message", role="user")]

    def test_execute_success(self, mock_assistant, execution_context, input_messages):
        # Setup
        mock_assistant.workflow.execute = Mock()

        # Mock consumed events
        event = Mock()
        event.topic_name = "test_topic"
        event.execution_context = execution_context
        event.offset = 0
        event.data = [Message(content="response", role="assistant", timestamp=1)]

        with (
            patch(
                "grafi.common.topics.output_topic.OutputTopic.can_consume",
                return_value=True,
            ),
            patch(
                "grafi.common.topics.output_topic.OutputTopic.consume",
                return_value=[event],
            ),
        ):
            # Execute
            result = mock_assistant.execute(execution_context, input_messages)

            # Verify
            mock_assistant.workflow.execute.assert_called_once_with(
                execution_context, input_messages
            )
            assert len(result) == 1
            assert result[0].content == "response"

    @pytest.mark.asyncio
    async def test_a_execute_success(
        self, mock_assistant, execution_context, input_messages
    ):
        # Setup
        mock_assistant.workflow.a_execute = AsyncMock(return_value=None)

        # Mock consumed events
        event = Mock()
        event.topic_name = "test_topic"
        event.execution_context = execution_context
        event.offset = 0
        event.data = [Message(content="async response", role="assistant")]

        with (
            patch(
                "grafi.common.topics.output_topic.OutputTopic.can_consume",
                return_value=True,
            ),
            patch(
                "grafi.common.topics.output_topic.OutputTopic.consume",
                return_value=[event],
            ),
        ):
            # Execute
            result = await mock_assistant.a_execute(execution_context, input_messages)

            # Verify
            assert len(result) == 1
            assert result[0].content == "async response"
            mock_assistant.workflow.a_execute.assert_called_once_with(
                execution_context, input_messages
            )

    def test_to_dict(self, mock_assistant):
        # Setup
        mock_assistant.workflow.to_dict.return_value = {"key": "value"}

        # Execute
        result = mock_assistant.to_dict()

        # Verify
        assert result == {"key": "value"}
        mock_assistant.workflow.to_dict.assert_called_once()

    def test_generate_manifest(self, mock_assistant, tmp_path):
        # Setup
        mock_assistant.workflow.to_dict.return_value = {"key": "value"}

        print(tmp_path)
        path = tmp_path / "test"
        path.mkdir()
        # Execute
        mock_assistant.generate_manifest(str(path))

        manifest_path = path / "test_assistant_manifest.json"

        # Verify
        assert os.path.exists(manifest_path)
        with open(manifest_path, "r") as f:
            manifest_data = json.loads(f.read())
        assert manifest_data == {"key": "value"}
