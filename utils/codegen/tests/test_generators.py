from config.models import ServiceManifest
from generators.services.requirements import RequirementsGenerator
from generators.services.scheduler import SchedulerGenerator
from generators.services.config import ConfigGenerator
from generators.services.observability import ObservabilityGenerator
from generators.services.main import MainGenerator
from generators.services.dockerfile import DockerfileGenerator


class TestRequirementsGenerator:
    def test_minimal_requirements(self, tmp_path):
        manifest = ServiceManifest.model_validate({"service": {"name": "test_svc"}})
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        req_file = tmp_path / "generated" / "requirements.txt"
        assert req_file.exists()
        content = req_file.read_text()
        assert "pydantic" in content
        assert "structlog" in content

    def test_postgres_requirements(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "postgres": {"enabled": True}}
        })
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        content = (tmp_path / "generated" / "requirements.txt").read_text()
        assert "sqlalchemy" in content
        assert "asyncpg" in content
        assert "alembic" in content

    def test_kafka_requirements(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "kafka_producer": {"enabled": True}}
        })
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        content = (tmp_path / "generated" / "requirements.txt").read_text()
        assert "aiokafka" in content

    def test_config_requirements(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "config": {"config_service": "infra_config", "enabled": True}}
        })
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        content = (tmp_path / "generated" / "requirements.txt").read_text()
        assert "grpcio" in content
        assert "protobuf" in content
        assert "croniter" in content
        assert "opentelemetry-api" in content

    def test_ticket_auth_requirements(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "ticket_auth": {"tas_service": "infra_tas", "enabled": True}}
        })
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        content = (tmp_path / "generated" / "requirements.txt").read_text()
        assert "pyjwt" in content
        assert "cryptography" in content

    def test_merges_user_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("pandas>=2.0.0\nrequests==2.31.0\n")
        manifest = ServiceManifest.model_validate({"service": {"name": "test_svc"}})
        gen = RequirementsGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        content = (tmp_path / "generated" / "requirements.txt").read_text()
        assert "pandas>=2.0.0" in content
        assert "requests==2.31.0" in content
        assert "pydantic" in content


class TestConfigGenerator:
    def test_config_generator_creates_all_files(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "config": {"config_service": "infra_config", "enabled": True, "update_interval_seconds": 15}}
        })
        gen = ConfigGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "config" / "__init__.py").exists()
        assert (tmp_path / "generated" / "config" / "client.py").exists()
        assert (tmp_path / "generated" / "config" / "flags.py").exists()
        assert (tmp_path / "generated" / "config" / "interceptor.py").exists()
        assert (tmp_path / "generated" / "config" / "tasks.py").exists()

        tasks_content = (tmp_path / "generated" / "config" / "tasks.py").read_text()
        assert "update_feature_flags" in tasks_content
        assert "seconds=15" in tasks_content

    def test_config_generator_skipped_when_disabled(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "config": {"enabled": False}}
        })
        gen = ConfigGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert not (tmp_path / "generated" / "config").exists()


class TestSchedulerGenerator:
    def test_scheduler_generated_for_config_even_if_scheduler_disabled(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {
                "name": "test_svc",
                "scheduler": {"enabled": False},
                "config": {"config_service": "infra_config", "enabled": True},
            }
        })
        gen = SchedulerGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "scheduler" / "registry.py").exists()
        assert (tmp_path / "generated" / "scheduler" / "scheduler.py").exists()
        assert (tmp_path / "generated" / "scheduler" / "decorator.py").exists()
        registry = (tmp_path / "generated" / "scheduler" / "registry.py").read_text()
        assert "generated.config.tasks" in registry

    def test_scheduler_with_database_storage_generates_models(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {
                "name": "test_svc",
                "postgres": {"enabled": True},
                "scheduler": {"enabled": True, "storage": "database"},
            }
        })
        gen = SchedulerGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "scheduler" / "models.py").exists()


class TestObservabilityGenerator:
    def test_observability_generation(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "observability": {"enabled": True}}
        })
        gen = ObservabilityGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "observability" / "__init__.py").exists()
        assert (tmp_path / "generated" / "observability" / "observability.py").exists()
        assert (tmp_path / "generated" / "observability" / "middleware.py").exists()


class TestMainGenerator:
    def test_main_generator_creates_makefile_and_entrypoint(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "main": {"enabled": True}}
        })
        gen = MainGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "main.py").exists()
        assert (tmp_path / "Makefile").exists()
        assert (tmp_path / ".gitignore").exists()
        assert (tmp_path / "generated" / "main.py").exists()


from generators.services.testing import TestingGenerator


class TestTestingGenerator:
    def test_testing_generator_with_all_modules(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {
                "name": "full_test_svc",
                "config": {"config_service": "infra_config", "enabled": True},
                "postgres": {"enabled": True},
                "kafka_producer": {"enabled": True, "topics": ["test.topic"]},
            }
        })
        gen = TestingGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "testing" / "__init__.py").exists()
        assert (tmp_path / "generated" / "testing" / "context.py").exists()
        assert (tmp_path / "generated" / "testing" / "fixtures.py").exists()
        assert (tmp_path / "generated" / "testing" / "flags.py").exists()
        assert (tmp_path / "generated" / "testing" / "db.py").exists()
        assert (tmp_path / "generated" / "testing" / "kafka.py").exists()
        assert (tmp_path / "pytest.ini").exists()
        assert (tmp_path / "tests" / "conftest.py").exists()

    def test_testing_generator_minimal(self, tmp_path):
        manifest = ServiceManifest.model_validate({"service": {"name": "minimal_svc"}})
        gen = TestingGenerator(manifest, tmp_path / "generated", docker=False)
        gen.generate()

        assert (tmp_path / "generated" / "testing" / "__init__.py").exists()
        assert (tmp_path / "generated" / "testing" / "context.py").exists()
        assert (tmp_path / "generated" / "testing" / "fixtures.py").exists()
        assert not (tmp_path / "generated" / "testing" / "flags.py").exists()
        assert not (tmp_path / "generated" / "testing" / "db.py").exists()
        assert not (tmp_path / "generated" / "testing" / "kafka.py").exists()


class TestDockerfileGenerator:
    def test_dockerfile_generation(self, tmp_path):
        manifest = ServiceManifest.model_validate({
            "service": {"name": "test_svc", "python": {"major": 3, "minor": 12}}
        })
        gen = DockerfileGenerator(manifest, tmp_path / "generated", docker=True)
        gen.generate()

        dockerfile = tmp_path / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text()
        assert "python:3.12-slim" in content
        assert "COPY generated/ /app/generated/" in content
        assert 'CMD ["python", "main.py"]' in content
