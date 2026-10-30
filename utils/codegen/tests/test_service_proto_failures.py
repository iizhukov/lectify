from pathlib import Path

import pytest

from config.models import ServiceManifest
from generators.services import grpc_server
from generators.services.grpc_client import GrpcClientGenerator


def manifest():
    return ServiceManifest.model_validate({'service': {'name': 'proto_failure', 'grpc': {'enabled': True}}})


def test_missing_server_protocol_does_not_produce_successful_wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr(grpc_server, 'get_service_proto', lambda _: tmp_path / 'missing.proto')
    generator = grpc_server.GrpcServerGenerator(manifest(), tmp_path / 'generated')
    with pytest.raises(FileNotFoundError, match='protocol not found'):
        generator.generate()
    assert not (tmp_path / 'generated/grpc_server/grpc_app.py').exists()


def test_invalid_server_protocol_propagates_compiler_failure(tmp_path, monkeypatch):
    proto = tmp_path / 'index.proto'
    proto.write_text('syntax = "proto3"; service Broken { invalid syntax }')
    monkeypatch.setattr(grpc_server, 'get_service_proto', lambda _: proto)
    generator = grpc_server.GrpcServerGenerator(manifest(), tmp_path / 'generated')
    with pytest.raises(RuntimeError, match='protocol compilation failed'):
        generator.generate()
    assert not (tmp_path / 'generated/grpc_server/grpc_app.py').exists()


def test_invalid_client_protocol_propagates_compiler_failure(tmp_path):
    proto = tmp_path / 'index.proto'
    proto.write_text('invalid protocol')
    output = tmp_path / 'generated/protos/client'
    output.mkdir(parents=True)
    generator = GrpcClientGenerator(manifest(), tmp_path / 'generated')
    with pytest.raises(RuntimeError, match='protocol compilation failed'):
        generator._generate_proto_stubs({'name': 'broken', 'proto_path': str(proto)}, output)


def test_service_runtime_requirements_match_protocol_compiler(tmp_path):
    from importlib.metadata import version
    from generators.services.requirements import RequirementsGenerator
    generator = RequirementsGenerator(manifest(), tmp_path / 'generated')
    generator.generate()
    requirements = (tmp_path / 'generated/requirements.txt').read_text()
    assert f"grpcio>={version('grpcio-tools')}" in requirements
    assert f"protobuf>={version('protobuf')}" in requirements
