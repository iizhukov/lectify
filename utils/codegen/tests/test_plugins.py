import pytest
import tempfile
import yaml
from pathlib import Path

from config.plugin_models import (
    PluginManifest,
    PluginConfig,
    PluginInputConfig,
    PluginOutputConfig,
    PluginParameterConfig,
    PluginBufferConfig,
)
from generators.runner import run_plugin
from utils import load_plugin_manifest, validate_plugin_manifest, PluginManifestError
from cli import main as cli_main


def test_plugin_manifest_model():
    manifest_data = {
        "plugin": {
            "name": "speech_to_text",
            "version": "0.1.0",
            "description": "Speech to text",
            "category": "media",
            "language": "python",
            "active": True,
            "inputs": [
                {
                    "name": "audio_chunk",
                    "type": "stream/audio",
                    "required": True,
                    "buffer": {
                        "strategy": "size",
                        "chunk_size_bytes": 1048576,
                        "time_window_ms": 5000,
                    },
                }
            ],
            "outputs": [
                {
                    "name": "transcript",
                    "type": "stream/text",
                }
            ],
            "parameters": [
                {
                    "name": "model",
                    "type": "string",
                    "default": "whisper-1",
                    "required": False,
                    "description": "Whisper model name",
                }
            ],
            "permissions": {
                "llm": {
                    "enabled": True,
                    "allowed_purposes": ["stt"],
                    "allowed_models": ["whisper-1"],
                },
                "storage": {
                    "enabled": True,
                    "upload_artifacts": True,
                },
            },
        }
    }

    manifest = PluginManifest.model_validate(manifest_data)
    assert manifest.plugin.name == "speech_to_text"
    assert manifest.plugin.inputs[0].buffer.strategy == "size"
    assert manifest.plugin.inputs[0].buffer.chunk_size_bytes == 1048576
    assert manifest.plugin.permissions.llm.enabled is True


def test_plugin_generator(tmp_path: Path):
    manifest_data = {
        "plugin": {
            "name": "test_transformer",
            "version": "0.1.0",
            "description": "Test transform plugin",
            "category": "ai",
            "language": "python",
            "active": True,
            "inputs": [
                {
                    "name": "text_stream",
                    "type": "stream/text",
                    "buffer": {
                        "strategy": "delimiter",
                        "delimiter": "\n",
                    },
                }
            ],
            "outputs": [
                {"name": "out_stream", "type": "stream/text"},
                {"name": "out_file", "type": "artifact/file", "filename": "out.txt"},
            ],
            "parameters": [
                {"name": "temperature", "type": "float", "default": 0.7},
            ],
        }
    }

    manifest = PluginManifest.model_validate(manifest_data)
    generated_dir = tmp_path / "generated"

    run_plugin(manifest, generated_dir)

    assert (generated_dir / "models.py").exists()
    assert (generated_dir / "buffer.py").exists()
    assert (generated_dir / "sidecar_client.py").exists()
    assert (generated_dir / "main.py").exists()
    assert (generated_dir / "Dockerfile").exists()
    assert (generated_dir / "requirements.txt").exists()

    # Verify python syntax by compiling
    compile((generated_dir / "models.py").read_text(), "models.py", "exec")
    compile((generated_dir / "buffer.py").read_text(), "buffer.py", "exec")
    compile((generated_dir / "sidecar_client.py").read_text(), "sidecar_client.py", "exec")
    compile((generated_dir / "main.py").read_text(), "main.py", "exec")


def test_plugin_cli_init_and_validate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LECTIFY_ROOT", str(tmp_path))
    plugin_dir = tmp_path / "plugins" / "media" / "mock_plugin"

    # CLI plugin init
    ret = cli_main(["plugin", "init", str(plugin_dir)])
    assert ret == 0
    assert (plugin_dir / "plugin.yaml").exists()
    assert (plugin_dir / "src" / "plugin.py").exists()

    # CLI plugin validate
    ret_val = cli_main(["plugin", "validate", str(plugin_dir)])
    assert ret_val == 0
