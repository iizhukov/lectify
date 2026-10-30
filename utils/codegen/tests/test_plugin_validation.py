"""Manifest validation and behavior of the Python emitted for a plugin."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from config.plugin_models import (
    PluginBufferConfig, PluginConfig, PluginManifest, PluginParameterConfig,
)
from generators.plugins.buffer import BufferGenerator
from generators.plugins.main import MainGenerator
from generators.plugins.models import ModelsGenerator


@pytest.mark.parametrize("name", ["not-valid", "1st", "class", "model_config", "dict", "_private"])
def test_parameter_name_must_be_a_python_field(name):
    with pytest.raises(ValidationError):
        PluginParameterConfig(name=name)


@pytest.mark.parametrize("data", [
    {"type": "bool", "default": "false"},
    {"type": "int", "default": True},
    {"type": "string", "default": 42},
    {"type": "float", "default": float("nan")},
    {"type": "dict", "default": {"unsupported": object()}},
])
def test_parameter_default_must_match_type_and_be_json_data(data):
    with pytest.raises(ValidationError):
        PluginParameterConfig(name="value", **data)


@pytest.mark.parametrize("data", [
    {"chunk_size_bytes": 4, "overlap_bytes": 4},
    {"chunk_size_bytes": 4, "overlap_bytes": 5},
    {"strategy": "full", "overlap_bytes": 1},
    {"strategy": "delimiter"},
    {"strategy": "delimiter", "delimiter": ""},
])
def test_buffer_rejects_invalid_manifest(data):
    with pytest.raises(ValidationError):
        PluginBufferConfig(**data)


@pytest.mark.parametrize("field", ["inputs", "outputs", "parameters"])
def test_plugin_rejects_duplicate_names(field):
    with pytest.raises(ValidationError):
        PluginConfig(name="example", **{field: [{"name": "same"}, {"name": "same"}]})


def generate(tmp_path: Path, **plugin_data):
    manifest = PluginManifest(plugin=PluginConfig(name="example", **plugin_data))
    output = tmp_path / "generated"
    ModelsGenerator(manifest, output).generate()
    BufferGenerator(manifest, output).generate()
    MainGenerator(manifest, output).generate()
    return output


def run_generated(tmp_path: Path, script: str):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=tmp_path, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_parameters_execute_with_data_defaults_and_safe_strings(tmp_path):
    description = 'Quotes " and \' and newline\n__import__("os").abort()'
    generate(tmp_path, parameters=[
        {"name": "enabled", "type": "bool", "default": True, "description": description},
        {"name": "options", "type": "dict", "default": {"nested": [False, None, "текст"]}},
        {"name": "optional", "type": "string"},
        {"name": "required_value", "type": "string", "required": True},
    ])
    run_generated(tmp_path, '''
        from generated.models import PluginParameters
        from pydantic import ValidationError
        try:
            PluginParameters()
        except ValidationError:
            pass
        else:
            raise AssertionError("required parameter accepted without a value")
        value = PluginParameters(required_value="present")
        assert value.enabled is True
        assert value.options == {"nested": [False, None, "текст"]}
        assert value.optional is None
        value.options["nested"].append("changed")
        assert PluginParameters(required_value="other").options == {"nested": [False, None, "текст"]}
        try:
            PluginParameters(required_value="present", unknown="typo")
        except ValidationError:
            pass
        else:
            raise AssertionError("unknown parameter silently accepted")
    ''')


def test_generated_delimiter_is_bytes_and_handles_chunk_boundaries(tmp_path):
    output = generate(tmp_path, inputs=[{
        "name": "text", "buffer": {"strategy": "delimiter", "delimiter": "\nтекст\n"},
    }])
    # Inspect the actual constructor expression without importing the plugin handler.
    import ast
    tree = ast.parse((output / "main.py").read_text())
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "StreamBufferAccumulator")
    delimiter = next(keyword.value for keyword in call.keywords if keyword.arg == "delimiter")
    assert eval(compile(ast.Expression(delimiter), "delimiter", "eval")) == "\nтекст\n".encode()
    run_generated(tmp_path, '''
        import asyncio
        from generated.buffer import StreamBufferAccumulator
        from generated.models import StreamChunk
        async def check():
            buffer = StreamBufferAccumulator(strategy="delimiter", delimiter=b"\\n\\n")
            assert await buffer.add_chunk(StreamChunk(stream_name="text", payload=b"first\\n")) == []
            assert await buffer.add_chunk(StreamChunk(stream_name="text", payload=b"\\nsecond\\n\\nend")) == [b"first", b"second"]
            assert await buffer.add_chunk(StreamChunk(stream_name="text", is_last=True)) == [b"end"]
            assert await buffer.flush() is None
        asyncio.run(check())
    ''')


def test_generated_size_buffer_overlap_and_eof(tmp_path):
    generate(tmp_path)
    run_generated(tmp_path, '''
        import asyncio
        from generated.buffer import StreamBufferAccumulator
        from generated.models import StreamChunk
        async def check():
            buffer = StreamBufferAccumulator(chunk_size_bytes=4, overlap_bytes=2)
            assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"abcdef", is_last=True)) == [b"abcd", b"cdef"]
            assert await buffer.flush() is None
            buffer = StreamBufferAccumulator(chunk_size_bytes=4, overlap_bytes=2)
            assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"abcde")) == [b"abcd"]
            assert await buffer.flush() == b"cde"
            assert await buffer.flush() is None
            for kwargs in ({"chunk_size_bytes": 0}, {"overlap_bytes": -1},
                           {"chunk_size_bytes": 4, "overlap_bytes": 4},
                           {"strategy": "delimiter", "delimiter": "text"},
                           {"strategy": "unknown"}):
                try:
                    StreamBufferAccumulator(**kwargs)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"invalid buffer accepted: {kwargs}")
        asyncio.run(check())
    ''')


def test_generated_full_and_time_buffer(tmp_path):
    generate(tmp_path)
    run_generated(tmp_path, '''
        import asyncio
        from unittest.mock import patch
        from generated.buffer import StreamBufferAccumulator
        from generated.models import StreamChunk
        async def check():
            buffer = StreamBufferAccumulator(strategy="full")
            assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"one")) == []
            assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"two", is_last=True)) == [b"onetwo"]
            with patch("generated.buffer.time.monotonic", return_value=10.0) as clock:
                buffer = StreamBufferAccumulator(strategy="time", time_window_ms=100)
                assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"one")) == []
                clock.return_value = 10.2
                assert await buffer.add_chunk(StreamChunk(stream_name="data", payload=b"two")) == [b"onetwo"]
        asyncio.run(check())
    ''')


def test_delimiter_preserves_empty_batches_for_blank_lines(tmp_path):
    generate(tmp_path)
    run_generated(tmp_path, '''
        import asyncio
        from generated.buffer import StreamBufferAccumulator
        from generated.models import StreamChunk
        async def check():
            buffer = StreamBufferAccumulator(strategy="delimiter", delimiter=b"\\n")
            assert await buffer.add_chunk(StreamChunk(stream_name="text", payload=b"first\\n\\nsecond\\n", is_last=True)) == [b"first", b"", b"second"]
        asyncio.run(check())
    ''')
