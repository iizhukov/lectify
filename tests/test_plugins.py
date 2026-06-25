"""
Tests for Plugin System
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path


class TestPluginBase:
    """Tests for Plugin base classes"""

    def test_plugin_input_base_class(self):
        """PluginInput should be instantiable"""
        from src.plugins.base import PluginInput

        inp = PluginInput()
        assert inp is not None

    def test_plugin_output_base_class(self):
        """PluginOutput should be instantiable"""
        from src.plugins.base import PluginOutput

        out = PluginOutput()
        assert out is not None

    def test_plugin_parameter_creation(self):
        """PluginParameter should accept all fields"""
        from src.plugins.base import PluginParameter

        param = PluginParameter(
            name="test_param",
            type="string",
            description="Test parameter",
            required=True,
            default="default_value",
            options=["option1", "option2"]
        )

        assert param.name == "test_param"
        assert param.type == "string"
        assert param.required is True
        assert param.default == "default_value"
        assert param.options == ["option1", "option2"]

    def test_plugin_context_initialization(self):
        """PluginContext should initialize correctly"""
        from src.plugins.base import PluginContext

        context = PluginContext(
            execution_id="exec-123",
            node_id="node-456"
        )

        assert context.execution_id == "exec-123"
        assert context.node_id == "node-456"
        assert context._progress_callback is None
        assert context._logs == []

    def test_plugin_context_progress_callback(self):
        """PluginContext should call progress callback"""
        from src.plugins.base import PluginContext

        callback_calls = []

        def progress_callback(percent, message):
            callback_calls.append((percent, message))

        context = PluginContext(execution_id="exec-1", node_id="node-1")
        context.set_progress_callback(progress_callback)
        context.report_progress(50, "Halfway done")

        assert len(callback_calls) == 1
        assert callback_calls[0] == (50, "Halfway done")

    def test_plugin_context_logging(self):
        """PluginContext should log messages"""
        from src.plugins.base import PluginContext

        context = PluginContext(execution_id="exec-1", node_id="node-1")
        context.log("info", "Test message")

        logs = context.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "info"
        assert logs[0]["message"] == "Test message"

    def test_plugin_context_logging_with_extra_kwargs(self):
        """PluginContext should log with extra kwargs"""
        from src.plugins.base import PluginContext

        context = PluginContext(execution_id="exec-1", node_id="node-1")
        context.log("error", "Something failed", file_id="file-123", error_code=500)

        logs = context.get_logs()
        # log("error") записывает 2 лога: один с kwargs, один с report_progress
        assert len(logs) >= 1
        # Ищем лог с extra kwargs
        error_log = next((l for l in logs if l.get("error_code") == 500), None)
        assert error_log is not None
        assert error_log["file_id"] == "file-123"
        assert error_log["error_code"] == 500


class TestPluginRegistry:
    """Tests for Plugin Registry"""

    def test_registry_is_singleton(self):
        """PluginRegistry should be a singleton"""
        from src.plugins.registry import PluginRegistry

        r1 = PluginRegistry()
        r2 = PluginRegistry()

        assert r1 is r2

    def test_registry_register_plugin(self):
        """Registry should register plugins"""
        from src.plugins.registry import PluginRegistry
        from src.plugins.base import Plugin, PluginInput, PluginOutput

        class TestPlugin(Plugin):
            id = "test_plugin"
            name = "Test Plugin"
            input_model = PluginInput
            output_model = PluginOutput

            async def execute(self, input_data, context, parameters):
                return PluginOutput()

        registry = PluginRegistry()
        initial_count = len(registry.get_all_plugins())

        registry.register(TestPlugin)
        plugins = registry.get_all_plugins()

        assert "test_plugin" in plugins
        assert len(plugins) == initial_count + 1

    def test_registry_get_plugin(self):
        """Registry should return plugin by ID"""
        from src.plugins.registry import get_plugin_registry

        registry = get_plugin_registry()
        plugin_class = registry.get_plugin("media_converter")

        # media_converter should be registered
        assert plugin_class is not None

    def test_registry_get_plugins_by_category(self):
        """Registry should filter plugins by category"""
        from src.plugins.registry import get_plugin_registry

        registry = get_plugin_registry()
        media_plugins = registry.get_plugins_by_category("media")

        # All media plugins should have category "media"
        for pid, pclass in media_plugins.items():
            assert getattr(pclass, "category", None) == "media"

    def test_registry_get_plugins_metadata(self):
        """Registry should return plugins metadata"""
        from src.plugins.registry import get_plugin_registry

        registry = get_plugin_registry()
        metadata = registry.get_plugins_metadata()

        assert len(metadata) > 0
        assert all("id" in m for m in metadata)
        assert all("name" in m for m in metadata)
        assert all("parameters_schema" in m for m in metadata)


class TestMediaConverterPlugin:
    """Tests for Media Converter Plugin"""

    def test_plugin_initialization(self):
        """MediaConverterPlugin should initialize with correct defaults"""
        from src.plugins.plugins.media_converter.plugin import MediaConverterPlugin

        plugin = MediaConverterPlugin()

        assert plugin.id == "media_converter"
        assert plugin.name == "Конвертация медиа"
        assert plugin.category == "media"
        assert plugin.version == "1.0.0"

    def test_plugin_input_model(self):
        """Plugin should use correct input model"""
        from src.plugins.plugins.media_converter.plugin import MediaConverterPlugin

        plugin = MediaConverterPlugin()

        assert plugin.input_model.__name__ == "MediaConverterInput"

    def test_plugin_output_model(self):
        """Plugin should use correct output model"""
        from src.plugins.plugins.media_converter.plugin import MediaConverterPlugin

        plugin = MediaConverterPlugin()

        assert plugin.output_model.__name__ == "MediaConverterOutput"

    def test_plugin_parameters_schema(self):
        """Plugin should have parameters schema"""
        from src.plugins.plugins.media_converter.plugin import MediaConverterPlugin

        plugin = MediaConverterPlugin()

        assert len(plugin.parameters_schema) > 0
        param_names = [p.name for p in plugin.parameters_schema]
        assert "format" in param_names
        assert "bitrate" in param_names

    def test_plugin_get_schema(self):
        """Plugin should return full schema"""
        from src.plugins.plugins.media_converter.plugin import MediaConverterPlugin

        plugin = MediaConverterPlugin()
        schema = plugin.get_schema()

        assert schema.input_fields is not None
        assert schema.output_fields is not None
        assert schema.parameters is not None


class TestLLMRequestPlugin:
    """Tests for LLM Request Plugin"""

    def test_plugin_initialization(self):
        """LLMRequestPlugin should initialize correctly"""
        from src.plugins.plugins.llm_request.plugin import LLMRequestPlugin

        plugin = LLMRequestPlugin()

        assert plugin.id == "llm_request"
        assert plugin.name == "LLM Запрос"
        assert plugin.category == "ai"

    def test_plugin_parameters_schema(self):
        """LLMRequestPlugin should have correct parameters"""
        from src.plugins.plugins.llm_request.plugin import LLMRequestPlugin

        plugin = LLMRequestPlugin()
        param_names = [p.name for p in plugin.parameters_schema]

        assert "model" in param_names
        assert "temperature" in param_names
        assert "max_tokens" in param_names


class TestTransformPlugin:
    """Tests for Transform Plugin"""

    def test_plugin_initialization(self):
        """TransformPlugin should initialize correctly"""
        from src.plugins.plugins.transform_node.plugin import TransformPlugin

        plugin = TransformPlugin()

        assert plugin.id == "transform_node"
        assert plugin.name == "Трансформация данных"
        assert plugin.category == "transform"

    def test_plugin_transform_types(self):
        """TransformPlugin should support all transform types"""
        from src.plugins.plugins.transform_node.plugin import TransformPlugin

        plugin = TransformPlugin()
        param = next(p for p in plugin.parameters_schema if p.name == "transform_type")

        expected_types = ["passthrough", "string", "int", "float", "path_replace", "json_parse", "json_dump", "regex_extract"]
        assert param.options == expected_types


class TestPluginModels:
    """Tests for Plugin models"""

    def test_media_converter_input(self):
        """MediaConverterInput should accept required fields"""
        from src.plugins.plugins.media_converter.models import MediaConverterInput

        inp = MediaConverterInput(
            file_id="file-123",
            file_path="/path/to/file.mp4"
        )

        assert inp.file_id == "file-123"
        assert inp.file_path == "/path/to/file.mp4"

    def test_media_converter_output(self):
        """MediaConverterOutput should accept required fields"""
        from src.plugins.plugins.media_converter.models import MediaConverterOutput

        out = MediaConverterOutput(
            file_id="file-123",
            media_path="/path/to/file.m4a",
            format="m4a",
            duration_ms=60000
        )

        assert out.file_id == "file-123"
        assert out.media_path == "/path/to/file.m4a"
        assert out.format == "m4a"
        assert out.duration_ms == 60000

    def test_llm_request_input(self):
        """LLMRequestInput should accept all fields"""
        from src.plugins.plugins.llm_request.plugin import LLMRequestInput

        inp = LLMRequestInput(
            file_id="file-123",
            prompt_id="prompt-456",
            system_prompt="You are a helpful assistant.",
            user_prompt_template="Summarize: {{text}}",
            variables={"text": "Hello world"}
        )

        assert inp.file_id == "file-123"
        assert inp.prompt_id == "prompt-456"
        assert inp.system_prompt == "You are a helpful assistant."
        assert inp.variables == {"text": "Hello world"}

    def test_transform_input_output(self):
        """TransformInput/Output should work correctly"""
        from src.plugins.plugins.transform_node.plugin import TransformInput, TransformOutput

        inp = TransformInput(file_id="file-123", data="some data")
        out = TransformOutput(file_id="file-123", result="transformed data", transform_type="string")

        assert inp.file_id == "file-123"
        assert out.result == "transformed data"
        assert out.transform_type == "string"