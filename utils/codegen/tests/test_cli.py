from cli import main


class TestInitCommand:
    def test_init_creates_service_yaml_and_src(self, tmp_path):
        svc_dir = tmp_path / "my_new_service"

        rc = main(["init", str(svc_dir)])
        assert rc == 0
        assert (svc_dir / "service.yaml").exists()
        assert (svc_dir / "src" / "__init__.py").exists()

        content = (svc_dir / "service.yaml").read_text()
        assert "name: my_new_service" in content
        assert "config:" in content
        assert "observability:" in content

    def test_init_does_not_overwrite_existing(self, tmp_path):
        svc_dir = tmp_path / "existing_svc"
        svc_dir.mkdir()
        existing = svc_dir / "service.yaml"
        existing.write_text("service:\n  name: custom_existing_name\n")

        rc = main(["init", str(svc_dir)])
        assert rc == 0
        assert "custom_existing_name" in existing.read_text()


class TestValidateCommand:
    def test_validate_valid_manifest(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: valid_service\n"
            "  version: 1.0.0\n"
            "  active: true\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["validate"])
        assert rc == 0

    def test_validate_invalid_manifest(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: Invalid_Service_Name!\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["validate"])
        assert rc == 1

    def test_validate_missing_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = main(["validate"])
        assert rc == 1


class TestServiceCommand:
    def test_service_missing_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = main(["service"])
        assert rc == 1

    def test_service_minimal_generation(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_minimal_svc\n"
            "  observability:\n"
            "    enabled: true\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "main.py").exists()
        assert (tmp_path / "generated" / "settings" / "base.py").exists()
        assert (tmp_path / "generated" / "settings" / "__init__.py").exists()
        assert (tmp_path / "generated" / "logger" / "logger.py").exists()
        assert (tmp_path / "generated" / "requirements.txt").exists()
        assert (tmp_path / "Dockerfile").exists()

    def test_service_with_config_generates_tasks_flags_and_scheduler(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_config_svc\n"
            "  config:\n"
            "    config_service: infra_config\n"
            "    enabled: true\n"
            "    update_interval_seconds: 20\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "config" / "__init__.py").exists()
        assert (tmp_path / "generated" / "config" / "client.py").exists()
        assert (tmp_path / "generated" / "config" / "flags.py").exists()
        assert (tmp_path / "generated" / "config" / "interceptor.py").exists()
        assert (tmp_path / "generated" / "config" / "tasks.py").exists()
        assert (tmp_path / "generated" / "scheduler" / "registry.py").exists()

        tasks_content = (tmp_path / "generated" / "config" / "tasks.py").read_text()
        assert "update_feature_flags" in tasks_content
        assert "seconds=20" in tasks_content

        flags_content = (tmp_path / "generated" / "config" / "flags.py").read_text()
        assert "class BaseFeatureFlag" in flags_content
        assert "def feature_flag" in flags_content

        registry_content = (tmp_path / "generated" / "scheduler" / "registry.py").read_text()
        assert "import generated.config.tasks" in registry_content

    def test_service_with_postgres_generates_db_module(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_db_svc\n"
            "  postgres:\n"
            "    enabled: true\n"
            "    pool_size: 15\n"
            "    pool_max_overflow: 8\n"
            "    pool_mode: transaction\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "db" / "connection.py").exists()
        assert (tmp_path / "generated" / "db" / "base.py").exists()
        assert (tmp_path / "generated" / "db" / "__init__.py").exists()

        conn_content = (tmp_path / "generated" / "db" / "connection.py").read_text()
        assert "create_async_engine" in conn_content
        assert "async_sessionmaker" in conn_content

    def test_service_with_kafka_generates_producer_and_consumer(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_kafka_svc\n"
            "  kafka_producer:\n"
            "    enabled: true\n"
            "    topics:\n"
            "      - user.events\n"
            "  kafka_consumer:\n"
            "    enabled: true\n"
            "    topics:\n"
            "      - order.events\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "kafka" / "producer.py").exists()
        assert (tmp_path / "generated" / "kafka" / "consumer.py").exists()

    def test_service_with_vault_generates_agent_hcl(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_vault_svc\n"
            "  vault:\n"
            "    enabled: true\n"
            "    vars:\n"
            "      - APP_SECRET_KEY\n"
            "      - DB_PASSWORD\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "vault" / "agent-test_vault_svc.local.hcl").exists()
        assert (tmp_path / "generated" / "vault" / "agent-test_vault_svc.docker.hcl").exists()

        hcl_content = (tmp_path / "generated" / "vault" / "agent-test_vault_svc.local.hcl").read_text()
        assert "APP_SECRET_KEY" in hcl_content
        assert "DB_PASSWORD" in hcl_content

    def test_service_with_ticket_auth_generates_tas_client_and_interceptors(self, tmp_path, monkeypatch):
        (tmp_path / "service.yaml").write_text(
            "service:\n"
            "  name: test_tas_svc\n"
            "  ticket_auth:\n"
            "    enabled: true\n"
            "    tas_service: infra_tas\n"
            "    ticket_ttl: 90\n"
        )
        monkeypatch.chdir(tmp_path)

        rc = main(["service"])
        assert rc == 0
        assert (tmp_path / "generated" / "ticket_auth" / "__init__.py").exists()
        assert (tmp_path / "generated" / "ticket_auth" / "client.py").exists()
        assert (tmp_path / "generated" / "ticket_auth" / "interceptor.py").exists()

        client_content = (tmp_path / "generated" / "ticket_auth" / "client.py").read_text()
        assert "TicketAuthClient" in client_content
        interceptor_content = (tmp_path / "generated" / "ticket_auth" / "interceptor.py").read_text()
        assert "TicketAuthServerInterceptor" in interceptor_content
        assert "TicketAuthClientInterceptor" in interceptor_content


class TestInfraCommand:
    def test_infra_generates_init_scripts(self, tmp_path, monkeypatch):
        repo_root = tmp_path
        svc_dir = repo_root / "services" / "infra" / "config"
        svc_dir.mkdir(parents=True)
        (svc_dir / "service.yaml").write_text(
            "service:\n"
            "  name: infra_config\n"
            "  active: true\n"
            "  postgres:\n"
            "    enabled: true\n"
            "  minio:\n"
            "    enabled: true\n"
            "    buckets:\n"
            "      - test_bucket\n"
            "  kafka_producer:\n"
            "    enabled: true\n"
            "    topics:\n"
            "      - test_topic\n"
        )
        monkeypatch.setenv("CODEGEN_ROOT", str(repo_root))
        monkeypatch.chdir(repo_root)

        rc = main(["infra"])
        assert rc == 0
        assert (repo_root / "infra" / "kafka" / "init-script.sh").exists()
        assert (repo_root / "infra" / "minio" / "init-script.sh").exists()
        assert (repo_root / "infra" / "postgres" / "init-script.sh").exists()

        pg_script = (repo_root / "infra" / "postgres" / "init-script.sh").read_text()
        assert "infra_config" in pg_script


class TestProjectCommand:
    def test_project_generates_active_services(self, tmp_path, monkeypatch):
        repo_root = tmp_path
        svc1 = repo_root / "services" / "api" / "svc_one"
        svc1.mkdir(parents=True)
        (svc1 / "service.yaml").write_text(
            "service:\n"
            "  name: svc_one\n"
            "  active: true\n"
            "  observability:\n"
            "    enabled: true\n"
        )

        svc2_inactive = repo_root / "services" / "api" / "svc_two"
        svc2_inactive.mkdir(parents=True)
        (svc2_inactive / "service.yaml").write_text(
            "service:\n"
            "  name: svc_two\n"
            "  active: false\n"
        )

        monkeypatch.setenv("CODEGEN_ROOT", str(repo_root))
        monkeypatch.chdir(repo_root)

        rc = main(["project"])
        assert rc == 0
        assert (svc1 / "generated" / "main.py").exists()
        assert not (svc2_inactive / "generated").exists()


class TestTestCommand:
    def test_test_command_runs_service_tests(self, tmp_path, monkeypatch):
        repo_root = tmp_path
        svc = repo_root / "services" / "examples" / "test_runner_svc"
        svc.mkdir(parents=True)
        (svc / "service.yaml").write_text(
            "service:\n"
            "  name: test_runner_svc\n"
            "  active: true\n"
        )
        tests_dir = svc / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text("def test_ok(): assert True\n")

        monkeypatch.setenv("CODEGEN_ROOT", str(repo_root))
        monkeypatch.chdir(repo_root)

        rc = main(["test", "test_runner_svc"])
        assert rc == 0

    def test_test_command_missing_service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEGEN_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        rc = main(["test", "non_existent_service"])
        assert rc == 1
