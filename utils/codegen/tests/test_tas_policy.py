"""Tests for TAS policy loader and automatic permission extraction from service.yaml."""

import sys
from pathlib import Path

codegen_dir = Path(__file__).resolve().parent.parent
repo_root = codegen_dir.parent.parent
tas_root = repo_root / "services" / "infra" / "tas"

if str(tas_root) not in sys.path:
    sys.path.insert(0, str(tas_root))

from src.policy.loader import _parse_service_yaml, load_default_rules
from src.policy.models import PermissionEffect


class TestTasPolicyLoader:
    def test_parse_grpc_client_services(self, tmp_path):
        manifest = tmp_path / "service.yaml"
        manifest.write_text(
            "service:\n"
            "  name: client_svc\n"
            "  grpc_client:\n"
            "    enabled: true\n"
            "    services:\n"
            "      - server_a\n"
            "      - server_b\n"
        )

        result = _parse_service_yaml(manifest)
        assert result is not None
        source, targets = result
        assert source == "client_svc"
        assert "server_a" in targets
        assert "server_b" in targets

    def test_parse_auto_includes_tas_when_ticket_auth_enabled(self, tmp_path):
        manifest = tmp_path / "service.yaml"
        manifest.write_text(
            "service:\n"
            "  name: secure_svc\n"
            "  ticket_auth:\n"
            "    enabled: true\n"
            "    tas_service: infra_tas\n"
        )

        result = _parse_service_yaml(manifest)
        assert result is not None
        source, targets = result
        assert source == "secure_svc"
        assert "infra_tas" in targets

    def test_parse_auto_includes_config_and_tas_when_config_enabled(self, tmp_path):
        manifest = tmp_path / "service.yaml"
        manifest.write_text(
            "service:\n"
            "  name: feature_flagged_svc\n"
            "  config:\n"
            "    enabled: true\n"
        )

        result = _parse_service_yaml(manifest)
        assert result is not None
        source, targets = result
        assert source == "feature_flagged_svc"
        assert "infra_config" in targets
        assert "infra_tas" in targets

    def test_load_default_rules_scans_repo(self, tmp_path):
        repo_root = tmp_path
        svc_a = repo_root / "services" / "api" / "service_a"
        svc_a.mkdir(parents=True)
        (svc_a / "service.yaml").write_text(
            "service:\n"
            "  name: service_a\n"
            "  grpc_client:\n"
            "    services:\n"
            "      - service_b\n"
            "  config:\n"
            "    enabled: true\n"
        )

        svc_b = repo_root / "services" / "api" / "service_b"
        svc_b.mkdir(parents=True)
        (svc_b / "service.yaml").write_text(
            "service:\n"
            "  name: service_b\n"
            "  ticket_auth:\n"
            "    enabled: true\n"
        )

        rules = load_default_rules(repo_root)
        rule_pairs = [(r.source_service, r.target_service) for r in rules]

        assert ("service_a", "service_b") in rule_pairs
        assert ("service_a", "infra_config") in rule_pairs
        assert ("service_a", "infra_tas") in rule_pairs
        assert ("service_b", "infra_tas") in rule_pairs

        for r in rules:
            assert r.effect == PermissionEffect.ALLOW
            assert r.is_default is True

