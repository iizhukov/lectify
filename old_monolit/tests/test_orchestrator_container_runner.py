import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from src.orchestrator.container_runner import (
    ContainerRunnerOrchestrator,
    _parse_prometheus_text,
    _parameters_for_artifact_type,
    _replace_paths_in_dict,
)
from src.docker.runner import PollingContainerRunner
from src.utils.storage import MinIOStorage


class TestParsePrometheusText:
    """Tests for _parse_prometheus_text()."""

    def test_parses_metric_with_labels(self):
        text = 'lectify_llm_api_requests_total{purpose="transcription",status="success"} 42\n'
        result = _parse_prometheus_text(text)

        assert "lectify_llm_api_requests_total" in result
        entry = result["lectify_llm_api_requests_total"][0]
        assert entry["labels"]["purpose"] == "transcription"
        assert entry["labels"]["status"] == "success"
        assert entry["value"] == 42.0

    def test_skips_comment_lines(self):
        text = '# HELP lectify_llm_api_requests_total LLM API requests\n'
        result = _parse_prometheus_text(text)
        assert result == {}

    def test_skips_empty_lines(self):
        text = "\n\n  \n"
        result = _parse_prometheus_text(text)
        assert result == {}

    def test_aggregates_multiple_values_same_metric(self):
        text = (
            'lectify_llm_api_requests_total{purpose="a"} 1\n'
            'lectify_llm_api_requests_total{purpose="b"} 2\n'
        )
        result = _parse_prometheus_text(text)
        assert len(result["lectify_llm_api_requests_total"]) == 2

    def test_multiple_labels_parsed(self):
        text = 'lectify_llm_api_errors_total{purpose="tts",error_type="timeout",region="us"} 5\n'
        result = _parse_prometheus_text(text)
        entry = result["lectify_llm_api_errors_total"][0]
        assert entry["labels"]["purpose"] == "tts"
        assert entry["labels"]["error_type"] == "timeout"
        assert entry["labels"]["region"] == "us"


class TestParametersForArtifactType:
    """Tests for _parameters_for_artifact_type()."""

    @pytest.mark.parametrize("ext,expected", [
        ("m4a", "audio"), ("mp3", "audio"), ("wav", "audio"), ("ogg", "audio"),
        ("mp4", "video"), ("mkv", "video"), ("avi", "video"), ("mov", "video"),
        ("txt", "text"), ("md", "text"), ("tex", "text"),
        ("pdf", "pdf"),
    ])
    def test_known_extensions(self, ext, expected):
        assert _parameters_for_artifact_type(ext) == expected

    def test_unknown_extension_defaults_to_data(self):
        assert _parameters_for_artifact_type("xyz") == "data"
        assert _parameters_for_artifact_type("csv") == "data"

    def test_case_insensitive(self):
        assert _parameters_for_artifact_type("MP3") == "audio"
        assert _parameters_for_artifact_type("PDF") == "pdf"


class TestReplacePathsInDict:
    """Tests for _replace_paths_in_dict()."""

    def test_replaces_matching_filename_in_string(self):
        uploaded = {"/output/audio.mp3": "minio://artifacts/audio.mp3"}
        data = "/output/audio.mp3"
        result = _replace_paths_in_dict(data, uploaded)
        assert result == "minio://artifacts/audio.mp3"

    def test_partial_filename_match(self):
        uploaded = {"audio.mp3": "minio://audio.mp3"}
        data = "/output/audio.mp3"
        result = _replace_paths_in_dict(data, uploaded)
        assert result == "minio://audio.mp3"

    def test_no_match_returns_original(self):
        uploaded = {"audio.mp3": "minio://audio.mp3"}
        data = "/other/path/file.txt"
        result = _replace_paths_in_dict(data, uploaded)
        assert result == "/other/path/file.txt"

    def test_replaces_in_nested_dict(self):
        uploaded = {"audio.mp3": "minio://audio.mp3"}
        data = {"key": "/output/audio.mp3", "other": "unchanged"}
        result = _replace_paths_in_dict(data, uploaded)
        assert result["key"] == "minio://audio.mp3"
        assert result["other"] == "unchanged"

    def test_replaces_in_list(self):
        uploaded = {"audio.mp3": "minio://audio.mp3"}
        data = ["/output/audio.mp3", "unchanged"]
        result = _replace_paths_in_dict(data, uploaded)
        assert result[0] == "minio://audio.mp3"
        assert result[1] == "unchanged"

    def test_replaces_in_deeply_nested_structure(self):
        uploaded = {"audio.mp3": "minio://audio.mp3"}
        data = {"outer": [{"inner": "/output/audio.mp3"}]}
        result = _replace_paths_in_dict(data, uploaded)
        assert result["outer"][0]["inner"] == "minio://audio.mp3"

    def test_non_string_non_dict_returns_unchanged(self):
        uploaded = {"x": "y"}
        assert _replace_paths_in_dict(123, uploaded) == 123
        assert _replace_paths_in_dict(None, uploaded) is None
        assert _replace_paths_in_dict(True, uploaded) is True


class TestContainerRunnerOrchestratorInit:
    def test_default_initialization(self):
        with patch("src.orchestrator.container_runner.PollingContainerRunner"), \
             patch("src.orchestrator.container_runner.ExecutionRepository"), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository"), \
             patch("src.orchestrator.container_runner.get_storage"), \
             patch("src.orchestrator.container_runner.NodeLogManager"):
            orch = ContainerRunnerOrchestrator()
            assert orch.docker_runner is not None
            assert orch.exec_repo is not None
            assert orch.node_repo is not None
            assert orch.storage is not None
            assert orch.log_manager is not None

    def test_custom_initialization(self):
        runner = MagicMock(spec=PollingContainerRunner)
        exec_repo = MagicMock()
        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)

        orch = ContainerRunnerOrchestrator(
            docker_runner=runner,
            execution_repo=exec_repo,
            execution_node_repo=node_repo,
            storage=storage,
        )

        assert orch.docker_runner is runner
        assert orch.exec_repo is exec_repo
        assert orch.node_repo is node_repo
        assert orch.storage is storage


class TestContainerRunnerOrchestratorRun:
    def _run_with_mocks(self, **runner_run_kwargs):
        """Helper: call orch.run() with mocked internals."""
        runner = MagicMock(spec=PollingContainerRunner)
        runner.run_plugin.return_value = {"status": "ok", "output": "result"}

        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)
        storage.upload_artifact.return_value = "exec123/node1/data/output.json"

        log_manager = MagicMock()
        log_manager.create_temp_log_file.return_value = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.PollingContainerRunner", return_value=runner), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository", return_value=node_repo), \
             patch("src.orchestrator.container_runner.MinIOStorage", return_value=storage), \
             patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(
                docker_runner=runner,
                execution_node_repo=node_repo,
                storage=storage,
            )
            orch.log_manager = log_manager

            return orch.run(
                node_exec_id="node-exec-1",
                plugin_id="plugin-1",
                input_data={"text": "hello"},
                parameters={"output_type": "text"},
                execution_id="exec-123",
                node_id="node-1",
                **runner_run_kwargs
            ), runner, node_repo, storage, log_manager

    def test_run_exception_still_triggers_log_upload(self):
        runner = MagicMock(spec=PollingContainerRunner)
        runner.run_plugin.side_effect = RuntimeError("docker error")

        log_manager = MagicMock()
        log_path = Path(tempfile.mktemp(suffix=".log"))
        log_manager.create_temp_log_file.return_value = log_path

        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)

        with patch("src.orchestrator.container_runner.PollingContainerRunner", return_value=runner), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository", return_value=node_repo), \
             patch("src.orchestrator.container_runner.MinIOStorage", return_value=storage), \
             patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(
                docker_runner=runner,
                execution_node_repo=node_repo,
                storage=storage,
            )
            orch.log_manager = log_manager

            with pytest.raises(RuntimeError, match="docker error"):
                orch.run(
                    node_exec_id="node-exec-1",
                    plugin_id="plugin-1",
                    input_data={},
                    parameters={},
                    execution_id="exec-123",
                    node_id="node-1",
                )

            log_manager.save_logs_to_minio.assert_called_once()


class TestContainerRunnerOrchestratorUploadLogs:
    def test_upload_node_logs_returns_object_name(self):
        storage = MagicMock(spec=MinIOStorage)
        storage.upload_log.return_value = "node/2026/06/25/exec_node.log"

        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = "node/2026/06/25/exec_node.log"
        log_path = Path(tempfile.mktemp(suffix=".log"))
        log_path.write_text("some logs")

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(storage=storage)
            orch.log_manager = log_manager

            result = orch._upload_node_logs(log_path, "exec-123", "node-1")

        assert result == "node/2026/06/25/exec_node.log"
        log_manager.save_logs_to_minio.assert_called_once()
        log_manager.cleanup_local.assert_called_once_with(log_path)

    def test_upload_node_logs_cleans_up_on_success(self):
        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = "node/2026/06/25/exec_node.log"
        log_path = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator()
            orch.log_manager = log_manager

            orch._upload_node_logs(log_path, "exec-123", "node-1")

        log_manager.cleanup_local.assert_called_once_with(log_path)

    def test_upload_node_logs_skips_cleanup_when_minio_fails(self):
        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = None
        log_path = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator()
            orch.log_manager = log_manager

            result = orch._upload_node_logs(log_path, "exec-123", "node-1")

        assert result is None
        log_manager.cleanup_local.assert_not_called()


class TestCreateDbFile:
    """Tests for _create_db_file()."""

    def test_creates_db_file_record(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        storage.artifacts_bucket = "artifacts"

        with patch("src.orchestrator.container_runner.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            test_file = tmp_path / "test_audio.mp3"
            test_file.write_bytes(b"fake audio content")

            orch = ContainerRunnerOrchestrator(storage=storage)

            with patch("src.orchestrator.container_runner.os.stat") as mock_stat:
                mock_stat.return_value = MagicMock(st_size=1024)
                file_id = orch._create_db_file(str(test_file), "exec/node/audio.mp3")

            assert file_id is not None
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    def test_creates_db_file_pdf_mime_type(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)

        with patch("src.orchestrator.container_runner.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            test_file = tmp_path / "document.pdf"
            test_file.write_bytes(b"pdf content")

            with patch("src.orchestrator.container_runner.os.stat") as mock_stat:
                mock_stat.return_value = MagicMock(st_size=2048)
                orch = ContainerRunnerOrchestrator(storage=storage)
                orch._create_db_file(str(test_file), "exec/node/document.pdf")

            added_db_file = mock_session.add.call_args[0][0]
            assert added_db_file.mime_type == "application/pdf"

    def test_creates_db_file_unknown_extension_octet_stream(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)

        with patch("src.orchestrator.container_runner.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            test_file = tmp_path / "unknown.xyz"
            test_file.write_bytes(b"content")

            with patch("src.orchestrator.container_runner.os.stat") as mock_stat:
                mock_stat.return_value = MagicMock(st_size=512)
                orch = ContainerRunnerOrchestrator(storage=storage)
                orch._create_db_file(str(test_file), "exec/node/unknown.xyz")

            added_db_file = mock_session.add.call_args[0][0]
            assert added_db_file.mime_type == "application/octet-stream"


class TestForwardPluginMetrics:
    """Tests for _forward_plugin_metrics()."""

    def test_skips_when_metrics_file_missing(self):
        storage = MagicMock(spec=MinIOStorage)
        orch = ContainerRunnerOrchestrator(storage=storage)

        temp_dir = Path(tempfile.mkdtemp())
        # No metrics.json file
        orch._forward_plugin_metrics(temp_dir, "my_plugin", "exec-123")

    def test_parses_and_forwards_duration_metrics(self):
        storage = MagicMock(spec=MinIOStorage)
        with patch("src.orchestrator.container_runner.get_metrics") as mock_get_m:
            mock_metrics = MagicMock()
            mock_get_m.return_value = mock_metrics

            temp_dir = Path(tempfile.mkdtemp())
            metrics_file = temp_dir / "output" / "metrics.json"
            metrics_file.parent.mkdir(parents=True)
            metrics_file.write_text(
                'lectify_llm_api_duration_seconds{purpose="transcription"} 1.23\n'
            )

            orch = ContainerRunnerOrchestrator(storage=storage)
            orch._forward_plugin_metrics(temp_dir, "my_plugin", "exec-123")

            mock_metrics.llm_api_duration.labels(purpose="transcription").observe.assert_called_once_with(1.23)

    def test_parses_and_forwards_error_metrics(self):
        storage = MagicMock(spec=MinIOStorage)
        with patch("src.orchestrator.container_runner.get_metrics") as mock_get_m:
            mock_metrics = MagicMock()
            mock_get_m.return_value = mock_metrics

            temp_dir = Path(tempfile.mkdtemp())
            metrics_file = temp_dir / "output" / "metrics.json"
            metrics_file.parent.mkdir(parents=True)
            metrics_file.write_text(
                'lectify_llm_api_errors_total{purpose="tts",error_type="timeout"} 3\n'
            )

            orch = ContainerRunnerOrchestrator(storage=storage)
            orch._forward_plugin_metrics(temp_dir, "my_plugin", "exec-123")

            mock_metrics.llm_api_errors.labels(purpose="tts", error_type="timeout").inc.assert_called_once_with(3)

    def test_handles_malformed_metrics_file(self):
        storage = MagicMock(spec=MinIOStorage)
        with patch("src.orchestrator.container_runner.get_metrics") as mock_get_m:
            mock_metrics = MagicMock()
            mock_get_m.return_value = mock_metrics

            temp_dir = Path(tempfile.mkdtemp())
            metrics_file = temp_dir / "output" / "metrics.json"
            metrics_file.parent.mkdir(parents=True)
            metrics_file.write_text("not valid prometheus text\nmetric{/} 999\n")

            # Should not raise
            orch = ContainerRunnerOrchestrator(storage=storage)
            orch._forward_plugin_metrics(temp_dir, "my_plugin", "exec-123")

            # No metrics forwarded
            mock_metrics.llm_api_requests.labels.assert_not_called()


class TestUpdateOutputDataFields:
    """Tests for _update_output_data_fields()."""

    def test_keeps_existing_file_id_when_present(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        temp_dir = tmp_path / "exec" / "node"
        temp_dir.mkdir(parents=True)

        output_data = {"file_id": "existing-id-999", "result": "/output/data.txt"}
        uploaded = {"data.txt": ("new-id", "minio://data.txt")}

        orch = ContainerRunnerOrchestrator(storage=storage)
        result = orch._update_output_data_fields(output_data, uploaded, temp_dir)

        assert result["file_id"] == "existing-id-999"

    def test_preserves_non_path_values(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        temp_dir = tmp_path / "exec" / "node"
        temp_dir.mkdir(parents=True)

        output_data = {"count": 42, "enabled": True, "data": None}
        uploaded = {}

        orch = ContainerRunnerOrchestrator(storage=storage)
        result = orch._update_output_data_fields(output_data, uploaded, temp_dir)

        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["data"] is None


class TestUploadOutputFiles:
    """Tests for _upload_output_files()."""

    def test_returns_empty_when_output_data_is_none(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        orch = ContainerRunnerOrchestrator(storage=storage)
        result = orch._upload_output_files(None, tmp_path, "exec-1", "node-1")  # type: ignore[arg-type]
        assert result == {}

    def test_returns_early_when_output_dir_missing(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        orch = ContainerRunnerOrchestrator(storage=storage)
        output_data = {"key": "value"}
        result = orch._upload_output_files(output_data, tmp_path, "exec-1", "node-1")
        assert result == {"key": "value"}

    def test_uploads_declared_artifacts_to_minio(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        storage.artifacts_bucket = "artifacts"
        storage.upload_artifact.return_value = "exec/node/audio.mp3"

        temp_dir = tmp_path / "exec123" / "node1"
        output_dir = temp_dir / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "transcript.txt").write_text("transcript content")

        output_data = {"transcript": "/tmp/lectify/exec123/node1/output/transcript.txt"}

        with patch("src.orchestrator.container_runner.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            orch = ContainerRunnerOrchestrator(storage=storage)
            result = orch._upload_output_files(
                output_data, temp_dir, "exec123", "node1",
                {"transcript": {"filename": "transcript.txt", "target_field": "transcript_id"}}
            )

        storage.upload_artifact.assert_called_once()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_skips_missing_artifact_files_with_warning(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        storage.artifacts_bucket = "artifacts"

        temp_dir = tmp_path / "exec" / "node"
        (temp_dir / "output").mkdir(parents=True)
        # transcript.txt does NOT exist

        output_data = {}
        output_artifacts = {"transcript": {"filename": "transcript.txt", "target_field": "tid"}}

        with patch("src.orchestrator.container_runner.logger") as mock_logger:
            orch = ContainerRunnerOrchestrator(storage=storage)
            result = orch._upload_output_files(output_data, temp_dir, "exec", "node", output_artifacts)

        # Should return original output_data unchanged
        assert result == {}
        storage.upload_artifact.assert_not_called()
        mock_logger.warning.assert_called()

    def test_returns_original_data_when_no_artifacts_uploaded(self, tmp_path):
        storage = MagicMock(spec=MinIOStorage)
        storage.artifacts_bucket = "artifacts"

        temp_dir = tmp_path / "exec" / "node"
        (temp_dir / "output").mkdir(parents=True)
        # No files in output dir

        output_data = {"text": "hello"}
        output_artifacts = {"some_artifact": {"filename": "missing.txt"}}

        with patch("src.orchestrator.container_runner.logger"):
            orch = ContainerRunnerOrchestrator(storage=storage)
            result = orch._upload_output_files(output_data, temp_dir, "exec", "node", output_artifacts)

        assert result == {"text": "hello"}
