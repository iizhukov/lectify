import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

from src.orchestrator.input_resolver import InputResolver
from src.plugins.datasource import DataSource, DataSourceManifest


class TestInputResolverInit:
    def test_uses_global_storage_when_none_provided(self):
        with patch("src.orchestrator.input_resolver.get_storage") as mock_get:
            mock_get.return_value = MagicMock()
            resolver = InputResolver()
            mock_get.assert_called_once()
            assert resolver.storage is mock_get.return_value

    def test_uses_provided_storage(self):
        custom_storage = MagicMock()
        resolver = InputResolver(storage=custom_storage)
        assert resolver.storage is custom_storage


class TestInputResolverResolve:
    """Tests for InputResolver.resolve()."""

    def test_returns_empty_manifest_when_no_data_sources(self):
        """When plugin has no data_sources or it's empty, return empty result."""
        resolver = InputResolver(storage=MagicMock())
        plugin = MagicMock()
        plugin.id = "test_plugin"
        plugin.data_sources = {}

        manifest, extra = resolver.resolve(plugin, {}, Path(tempfile.mkdtemp()))

        assert isinstance(manifest, DataSourceManifest)
        assert manifest.path("audio_file") is None
        assert extra == {}

    def test_returns_empty_when_data_sources_is_not_dict(self):
        """Guard: Pydantic FieldInfo returns something non-dict."""
        from pydantic.fields import FieldInfo
        resolver = InputResolver(storage=MagicMock())
        plugin = MagicMock()
        plugin.id = "test_plugin"
        plugin.data_sources = FieldInfo()  # not a dict

        manifest, extra = resolver.resolve(plugin, {}, Path(tempfile.mkdtemp()))

        assert manifest.path("bad_entry") is None

    def test_non_data_source_entry_is_skipped_with_warning(self):
        """If a data_sources entry is not a DataSource instance, skip it."""
        resolver = InputResolver(storage=MagicMock())
        plugin = MagicMock()
        plugin.id = "test_plugin"
        plugin.data_sources = {"bad_entry": "not a DataSource"}

        with patch("src.orchestrator.input_resolver.logger") as mock_logger:
            manifest, extra = resolver.resolve(plugin, {}, Path(tempfile.mkdtemp()))

        assert manifest.path("bad_entry") is None
        mock_logger.warning.assert_called_once()

    def test_required_file_source_not_found_raises(self):
        """Required file source with no input_data value raises FileNotFoundError."""
        resolver = InputResolver(storage=MagicMock())
        plugin = MagicMock()
        plugin.id = "my_plugin"
        plugin.data_sources = {
            "audio_file": DataSource(type="file", required=True, filename="audio.mp3", source="file_id"),
        }

        with pytest.raises(FileNotFoundError) as exc_info:
            resolver.resolve(plugin, {}, Path(tempfile.mkdtemp()))

        assert "audio_file" in str(exc_info.value)
        assert "my_plugin" in str(exc_info.value)

    def test_optional_file_source_missing_returns_error_in_manifest(self):
        """Optional source that can't be resolved is recorded in manifest.errors."""
        resolver = InputResolver(storage=MagicMock())
        plugin = MagicMock()
        plugin.id = "my_plugin"
        plugin.data_sources = {
            "extra_file": DataSource(type="file", required=False, filename="extra.txt", source="optional_id"),
        }

        manifest, extra = resolver.resolve(plugin, {}, Path(tempfile.mkdtemp()))

        assert "extra_file" in manifest.errors


class TestInputResolverResolveFile:
    """Tests for InputResolver._resolve_file()."""

    def test_minio_download_returns_none_when_file_missing(self, tmp_path):
        """MinIO returns None for missing object."""
        storage = MagicMock()
        storage.get_file_bytes.return_value = None

        resolver = InputResolver(storage=storage)
        plugin = MagicMock()
        plugin.id = "test"
        plugin.data_sources = {
            "doc": DataSource(type="file", required=False, filename="doc.pdf", source="doc_id"),
        }

        input_data = {"doc_id": "minio://uploads/missing.pdf"}
        manifest, extra = resolver.resolve(plugin, input_data, tmp_path)

        assert "doc" in manifest.errors


class TestInputResolverResolvePrompt:
    """Tests for InputResolver._resolve_prompt()."""

    def test_prompt_not_found_returns_error(self, tmp_path):
        """If DBPrompt is not found, return error."""
        storage = MagicMock()

        with patch("src.orchestrator.input_resolver.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = None

            resolver = InputResolver(storage=storage)
            plugin = MagicMock()
            plugin.id = "test"
            plugin.data_sources = {
                "prompt": DataSource(type="prompt", required=False, filename="p.txt", source="prompt_id"),
            }

            input_data = {"prompt_id": "nonexistent-prompt"}
            manifest, extra = resolver.resolve(plugin, input_data, tmp_path)

        assert "prompt" in manifest.errors


class TestInputResolverResolveText:
    """Tests for InputResolver._resolve_text()."""

    def test_text_source_uses_source_value(self, tmp_path):
        """When source.value is set, use it directly."""
        storage = MagicMock()
        resolver = InputResolver(storage=storage)
        plugin = MagicMock()
        plugin.id = "test"
        plugin.data_sources = {
            "static_text": DataSource(type="text", required=True, filename="static.txt", value="Hello, World!"),
        }

        manifest, extra = resolver.resolve(plugin, {}, tmp_path)

        assert manifest.path("static_text") == "/input/static.txt"
        written = (tmp_path / "input" / "static.txt").read_text()
        assert written == "Hello, World!"

    def test_text_source_falls_back_to_input_data(self, tmp_path):
        """When source.value is None, look in input_data by name."""
        storage = MagicMock()
        resolver = InputResolver(storage=storage)
        plugin = MagicMock()
        plugin.id = "test"
        plugin.data_sources = {
            "description": DataSource(type="text", required=True, filename="desc.txt"),
        }

        input_data = {"description": "Input description text"}
        manifest, extra = resolver.resolve(plugin, input_data, tmp_path)

        assert manifest.path("description") == "/input/desc.txt"
        written = (tmp_path / "input" / "desc.txt").read_text()
        assert written == "Input description text"
