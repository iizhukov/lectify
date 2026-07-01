from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from src.orchestrator.logs import NodeLogManager
from src.utils.storage import MinIOStorage


class TestNodeLogManagerInit:
    def test_default_initialization_uses_global_storage(self):
        with patch("src.orchestrator.logs.get_storage") as mock_get:
            mock_get.return_value = MagicMock(spec=MinIOStorage)
            manager = NodeLogManager()
            mock_get.assert_called_once()
            assert manager.storage is mock_get.return_value

    def test_custom_storage_is_used(self):
        custom_storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=custom_storage)
        assert manager.storage is custom_storage


class TestNodeLogManagerCreateTempLogFile:
    def test_creates_file_in_correct_directory(self):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_path = manager.create_temp_log_file("exec-123", "node-456")

        expected_dir = Path(tempfile.gettempdir()) / "lectify" / "logs" / "exec-123" / "node-456"
        assert log_path.parent == expected_dir
        assert log_path.name == "node.log"

    def test_creates_parent_directories(self):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_path = manager.create_temp_log_file("exec-new", "node-new")
        assert log_path.parent.exists()


class TestNodeLogManagerAppendLogs:
    def test_appends_to_file(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_file = tmp_path / "test.log"
        log_file.write_text("initial\n")

        manager.append_logs(log_file, "new line 1\nnew line 2\n")

        content = log_file.read_text()
        assert "initial" in content
        assert "new line 1" in content
        assert "new line 2" in content

    def test_append_logs_empty_string_does_nothing(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_file = tmp_path / "test.log"
        log_file.write_text("initial\n")

        manager.append_logs(log_file, "")

        assert log_file.read_text() == "initial\n"

    def test_append_logs_handles_write_error(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_file = tmp_path / "test.log"
        log_file.write_text("initial\n")
        log_file.chmod(0o000)  # make it read-only

        # Should not raise, just log warning
        manager.append_logs(log_file, "new line\n")

        log_file.chmod(0o644)  # restore


class TestNodeLogManagerSaveLogsToMinio:
    def test_returns_none_when_file_missing(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        missing = tmp_path / "nonexistent.log"
        result = manager.save_logs_to_minio(missing, "exec-123", "node-1")

        assert result is None
        storage.upload_log.assert_not_called()

    def test_returns_none_when_file_empty(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        empty_file = tmp_path / "empty.log"
        empty_file.touch()

        result = manager.save_logs_to_minio(empty_file, "exec-123", "node-1")

        assert result is None
        storage.upload_log.assert_not_called()

    def test_upload_log_returns_none_on_s3_error(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        storage.upload_log.return_value = None  # S3Error mapped to None

        manager = NodeLogManager(storage=storage)
        log_file = tmp_path / "node.log"
        log_file.write_text("log\n")

        result = manager.save_logs_to_minio(log_file, "exec-123", "node-1")

        assert result is None


class TestNodeLogManagerCleanupLocal:
    def test_deletes_file_on_disk(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_file = tmp_path / "node.log"
        log_file.write_text("log data\n")

        assert log_file.exists()

        manager.cleanup_local(log_file)

        assert not log_file.exists()

    def test_cleanup_nonexistent_file_does_nothing(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        missing = tmp_path / "nonexistent.log"

        # Should not raise
        manager.cleanup_local(missing)

    def test_cleanup_handles_permission_error(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        manager = NodeLogManager(storage=storage)

        log_file = tmp_path / "node.log"
        log_file.write_text("log\n")
        log_file.chmod(0o000)

        # Should not raise even if unlink fails (may silently succeed as root on macOS)
        try:
            manager.cleanup_local(log_file)
        except FileNotFoundError:
            # On macOS as root, unlink() on 0o000 succeeds silently, then chmod raises ENOENT
            pass
