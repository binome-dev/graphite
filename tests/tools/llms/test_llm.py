"""
Tests for LLM base class utility functions.
"""

from pydantic import BaseModel

from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm import add_additional_properties


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    age: int


class NestedModel(BaseModel):
    """Nested Pydantic model for testing."""

    user: SampleModel
    active: bool


class TestAddAdditionalProperties:
    """Test suite for add_additional_properties function."""

    def test_add_additional_properties_simple_object(self):
        """Test adding additionalProperties to a simple object schema."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        result = add_additional_properties(schema)

        assert result["additionalProperties"] is False
        assert result["type"] == "object"
        assert "properties" in result

    def test_add_additional_properties_nested_objects(self):
        """Test adding additionalProperties to nested object schemas."""
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            },
        }

        result = add_additional_properties(schema)

        assert result["additionalProperties"] is False
        assert result["properties"]["user"]["additionalProperties"] is False

    def test_add_additional_properties_with_defs(self):
        """Test adding additionalProperties to schemas with $defs."""
        schema = {
            "type": "object",
            "properties": {"ref_field": {"$ref": "#/$defs/SubSchema"}},
            "$defs": {
                "SubSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                }
            },
        }

        result = add_additional_properties(schema)

        assert result["additionalProperties"] is False
        assert result["$defs"]["SubSchema"]["additionalProperties"] is False

    def test_add_additional_properties_only_when_missing_true(self):
        """Test that existing additionalProperties is not overwritten when only_when_missing=True."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": True,
        }

        result = add_additional_properties(schema, False, only_when_missing=True)

        # Should keep existing value
        assert result["additionalProperties"] is True

    def test_add_additional_properties_only_when_missing_false(self):
        """Test that existing additionalProperties is overwritten when only_when_missing=False."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": True,
        }

        result = add_additional_properties(schema, False, only_when_missing=False)

        # Should overwrite with new value
        assert result["additionalProperties"] is False

    def test_add_additional_properties_skip_unevaluated_properties(self):
        """Test that additionalProperties is not added when unevaluatedProperties is present."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "unevaluatedProperties": False,
        }

        result = add_additional_properties(
            schema, False, skip_when_unevaluated_present=True
        )

        # Should not add additionalProperties when unevaluatedProperties exists
        assert "additionalProperties" not in result
        assert result["unevaluatedProperties"] is False

    def test_add_additional_properties_with_unevaluated_skip_false(self):
        """Test that additionalProperties is added even when unevaluatedProperties present if skip=False."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "unevaluatedProperties": False,
        }

        result = add_additional_properties(
            schema, False, skip_when_unevaluated_present=False
        )

        # Should add additionalProperties even with unevaluatedProperties
        assert result["additionalProperties"] is False
        assert result["unevaluatedProperties"] is False

    def test_add_additional_properties_with_custom_value(self):
        """Test adding custom value for additionalProperties."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        result = add_additional_properties(schema, {"type": "string"})

        assert result["additionalProperties"] == {"type": "string"}

    def test_add_additional_properties_allof(self):
        """Test adding additionalProperties to allOf schemas."""
        schema = {
            "allOf": [
                {"type": "object", "properties": {"name": {"type": "string"}}},
                {"type": "object", "properties": {"age": {"type": "integer"}}},
            ]
        }

        result = add_additional_properties(schema)

        assert result["allOf"][0]["additionalProperties"] is False
        assert result["allOf"][1]["additionalProperties"] is False

    def test_add_additional_properties_anyof(self):
        """Test adding additionalProperties to anyOf schemas."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"name": {"type": "string"}}},
                {"type": "string"},
            ]
        }

        result = add_additional_properties(schema)

        assert result["anyOf"][0]["additionalProperties"] is False
        # Second schema is not an object, should remain unchanged
        assert "additionalProperties" not in result["anyOf"][1]

    def test_add_additional_properties_oneof(self):
        """Test adding additionalProperties to oneOf schemas."""
        schema = {
            "oneOf": [
                {"type": "object", "properties": {"id": {"type": "integer"}}},
                {"type": "object", "properties": {"uuid": {"type": "string"}}},
            ]
        }

        result = add_additional_properties(schema)

        assert result["oneOf"][0]["additionalProperties"] is False
        assert result["oneOf"][1]["additionalProperties"] is False

    def test_add_additional_properties_does_not_modify_original(self):
        """Test that the original schema is not modified."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        result = add_additional_properties(schema)

        # Original schema should be unchanged
        assert "additionalProperties" not in schema
        assert result is not schema
        assert result != schema

    def test_add_additional_properties_with_pattern_properties(self):
        """Test adding additionalProperties with patternProperties."""
        schema = {
            "type": "object",
            "patternProperties": {"^S_": {"type": "string"}},
        }

        result = add_additional_properties(schema)

        assert result["additionalProperties"] is False

    def test_add_additional_properties_items_schema(self):
        """Test adding additionalProperties with items containing objects."""
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }

        result = add_additional_properties(schema)

        # Should add to the object inside items
        assert result["items"]["additionalProperties"] is False

    def test_add_additional_properties_prefix_items(self):
        """Test adding additionalProperties with prefixItems."""
        schema = {
            "type": "array",
            "prefixItems": [
                {"type": "object", "properties": {"id": {"type": "integer"}}},
                {"type": "object", "properties": {"name": {"type": "string"}}},
            ],
        }

        result = add_additional_properties(schema)

        assert result["prefixItems"][0]["additionalProperties"] is False
        assert result["prefixItems"][1]["additionalProperties"] is False


class TestLLMSerializeChatParams:
    """Test suite for LLM._serialize_chat_params method."""

    def test_serialize_chat_params_primitives(self):
        """Test serializing primitive values."""
        llm = LLM(model="test-model")
        params = {
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }

        result = llm._serialize_chat_params(params)

        assert result == params
        assert result["temperature"] == 0.7
        assert result["max_tokens"] == 100

    def test_serialize_chat_params_pydantic_instance(self):
        """Test serializing Pydantic model instance."""
        llm = LLM(model="test-model")
        sample = SampleModel(name="John", age=30)
        params = {"response_format": sample}

        result = llm._serialize_chat_params(params)

        assert result["response_format"] == {"name": "John", "age": 30}
        assert isinstance(result["response_format"], dict)

    def test_serialize_chat_params_pydantic_class(self):
        """Test serializing Pydantic model class."""
        llm = LLM(model="test-model")
        params = {"response_format": SampleModel}

        result = llm._serialize_chat_params(params)

        assert result["response_format"]["type"] == "json_schema"
        assert result["response_format"]["json_schema"]["name"] == "SampleModel"
        assert result["response_format"]["json_schema"]["strict"] is True
        assert "schema" in result["response_format"]["json_schema"]

    def test_serialize_chat_params_nested_dict(self):
        """Test serializing nested dictionaries with Pydantic models."""
        llm = LLM(model="test-model")
        sample = SampleModel(name="Jane", age=25)
        params = {
            "advanced": {
                "response_format": sample,
                "temperature": 0.5,
            }
        }

        result = llm._serialize_chat_params(params)

        assert result["advanced"]["response_format"] == {"name": "Jane", "age": 25}
        assert result["advanced"]["temperature"] == 0.5

    def test_serialize_chat_params_list_with_instances(self):
        """Test serializing list containing Pydantic instances."""
        llm = LLM(model="test-model")
        samples = [
            SampleModel(name="Alice", age=20),
            SampleModel(name="Bob", age=30),
        ]
        params = {"examples": samples}

        result = llm._serialize_chat_params(params)

        assert len(result["examples"]) == 2
        assert result["examples"][0] == {"name": "Alice", "age": 20}
        assert result["examples"][1] == {"name": "Bob", "age": 30}

    def test_serialize_chat_params_list_with_classes(self):
        """Test serializing list containing Pydantic classes."""
        llm = LLM(model="test-model")
        params = {"response_formats": [SampleModel, NestedModel]}

        result = llm._serialize_chat_params(params)

        assert len(result["response_formats"]) == 2
        assert "json_schema" in result["response_formats"][0]
        assert "json_schema" in result["response_formats"][1]

    def test_serialize_chat_params_mixed_list(self):
        """Test serializing list with mixed primitive and Pydantic values."""
        llm = LLM(model="test-model")
        sample = SampleModel(name="Charlie", age=35)
        params = {"mixed": ["string_value", 42, sample, True]}

        result = llm._serialize_chat_params(params)

        assert result["mixed"][0] == "string_value"
        assert result["mixed"][1] == 42
        assert result["mixed"][2] == {"name": "Charlie", "age": 35}
        assert result["mixed"][3] is True

    def test_serialize_chat_params_empty_dict(self):
        """Test serializing empty dictionary."""
        llm = LLM(model="test-model")
        params = {}

        result = llm._serialize_chat_params(params)

        assert result == {}

    def test_serialize_chat_params_none_values(self):
        """Test serializing None values."""
        llm = LLM(model="test-model")
        params = {"optional_param": None, "temperature": 0.7}

        result = llm._serialize_chat_params(params)

        assert result["optional_param"] is None
        assert result["temperature"] == 0.7

    def test_serialize_chat_params_deeply_nested(self):
        """Test serializing deeply nested structures."""
        llm = LLM(model="test-model")
        sample = SampleModel(name="Deep", age=40)
        params = {
            "level1": {"level2": {"level3": {"response_format": sample, "value": 123}}}
        }

        result = llm._serialize_chat_params(params)

        assert result["level1"]["level2"]["level3"]["response_format"] == {
            "name": "Deep",
            "age": 40,
        }
        assert result["level1"]["level2"]["level3"]["value"] == 123

    def test_serialize_chat_params_preserves_other_types(self):
        """Test that other JSON-serializable types are preserved."""
        llm = LLM(model="test-model")
        params = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
        }

        result = llm._serialize_chat_params(params)

        assert result == params
        assert result["string"] == "test"
        assert result["number"] == 42
        assert result["float"] == 3.14
        assert result["boolean"] is True
        assert result["null"] is None
        assert result["list"] == [1, 2, 3]
        assert result["dict"] == {"key": "value"}

    def test_serialize_chat_params_used_in_to_dict(self):
        """Test that _serialize_chat_params is properly used in to_dict method."""
        sample = SampleModel(name="Test", age=50)
        llm = LLM(model="test-model", chat_params={"response_format": sample})

        result = llm.to_dict()

        # chat_params should be serialized
        assert "chat_params" in result
        assert result["chat_params"]["response_format"] == {"name": "Test", "age": 50}
