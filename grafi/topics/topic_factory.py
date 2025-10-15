"""
TopicFactory - Factory class for deserializing topics from dictionary representations.

This module provides a centralized factory for creating topic instances from
serialized dictionary data. It automatically determines the correct topic type
and instantiates the appropriate class.
"""

from typing import Any
from typing import Dict
from typing import Type

from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType


class TopicFactory:
    """
    Factory class for creating topic instances from dictionary representations.

    This factory maps topic types to their corresponding classes and provides
    a single entry point for deserializing topics from dictionary data.

    Example:
        >>> topic_data = {
        ...     "name": "my_topic",
        ...     "type": "AgentInputTopic",
        ...     "condition": "..."
        ... }
        >>> topic = TopicFactory.from_dict(topic_data)
        >>> isinstance(topic, InputTopic)
        True
    """

    # Registry mapping TopicType enum values to their corresponding classes
    _TOPIC_REGISTRY: Dict[TopicType, Type[TopicBase]] = {
        TopicType.DEFAULT_TOPIC_TYPE: Topic,
        TopicType.AGENT_INPUT_TOPIC_TYPE: InputTopic,
        TopicType.AGENT_OUTPUT_TOPIC_TYPE: OutputTopic,
        TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE: InWorkflowInputTopic,
        TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE: InWorkflowOutputTopic,
    }

    # Registry mapping string type values to TopicType enums
    _TYPE_STRING_MAP: Dict[str, TopicType] = {
        "Topic": TopicType.DEFAULT_TOPIC_TYPE,
        "AgentInputTopic": TopicType.AGENT_INPUT_TOPIC_TYPE,
        "AgentOutputTopic": TopicType.AGENT_OUTPUT_TOPIC_TYPE,
        "InWorkflowInputTopic": TopicType.IN_WORKFLOW_INPUT_TOPIC_TYPE,
        "InWorkflowOutputTopic": TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE,
    }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> TopicBase:
        """
        Create a topic instance from a dictionary representation.

        This method automatically determines the topic type from the dictionary
        and instantiates the appropriate topic class using its from_dict method.

        Args:
            data (Dict[str, Any]): A dictionary representation of the topic.
                Must contain at least:
                - "type": The topic type (string or TopicType enum value)
                - "name": The topic name
                - "condition": The serialized condition function

        Returns:
            TopicBase: An instance of the appropriate topic subclass.

        Raises:
            ValueError: If the topic type is unknown or not registered.
            KeyError: If required keys are missing from the data dictionary.

        Example:
            >>> data = {
            ...     "name": "user_input",
            ...     "type": "AgentInputTopic",
            ...     "condition": "<serialized_condition>"
            ... }
            >>> topic = await TopicFactory.from_dict(data)
            >>> isinstance(topic, InputTopic)
            True
        """
        # Extract and normalize the type
        topic_type_value = data.get("type")

        if topic_type_value is None:
            raise KeyError("Missing required key 'type' in topic data")

        # Convert string to TopicType enum if necessary
        if isinstance(topic_type_value, str):
            if topic_type_value not in cls._TYPE_STRING_MAP:
                raise ValueError(
                    f"Unknown topic type string: {topic_type_value}. "
                    f"Valid types are: {list(cls._TYPE_STRING_MAP.keys())}"
                )
            topic_type = cls._TYPE_STRING_MAP[topic_type_value]
        elif isinstance(topic_type_value, TopicType):
            topic_type = topic_type_value
        else:
            raise ValueError(
                f"Invalid topic type: {topic_type_value}. "
                f"Expected string or TopicType enum, got {type(topic_type_value)}"
            )

        # Look up the appropriate class
        topic_class = cls._TOPIC_REGISTRY.get(topic_type)

        if topic_class is None:
            raise ValueError(
                f"No topic class registered for type: {topic_type}. "
                f"Registered types: {list(cls._TOPIC_REGISTRY.keys())}"
            )

        # Instantiate using the class's from_dict method
        return await topic_class.from_dict(data)

    @classmethod
    def register_topic_type(
        cls, topic_type: TopicType, topic_class: Type[TopicBase]
    ) -> None:
        """
        Register a custom topic type with the factory.

        This allows extending the factory with new topic types without
        modifying the factory code.

        Args:
            topic_type (TopicType): The TopicType enum value for this class.
            topic_class (Type[TopicBase]): The topic class to register.

        Example:
            >>> class CustomTopic(TopicBase):
            ...     pass
            >>> TopicFactory.register_topic_type(
            ...     TopicType.CUSTOM_TOPIC_TYPE,
            ...     CustomTopic
            ... )
        """
        cls._TOPIC_REGISTRY[topic_type] = topic_class

    @classmethod
    def get_registered_types(cls) -> Dict[TopicType, Type[TopicBase]]:
        """
        Get a copy of the current topic type registry.

        Returns:
            Dict[TopicType, Type[TopicBase]]: A dictionary mapping topic types
                to their registered classes.
        """
        return cls._TOPIC_REGISTRY.copy()
