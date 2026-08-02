import re
import subprocess
import sys

from pathlib import Path

from google.protobuf import descriptor_pb2

from generators.services.base import BaseGenerator
from utils import get_service_proto, get_service_path, get_service_manifest, get_repo_root


class GrpcClientGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.grpc_client.enabled:
            return

        client_services = self._build_service_list()
        if not client_services:
            return

        protos_out = self.output / "protos" / "clients"
        protos_out.mkdir(parents=True, exist_ok=True)
        (protos_out / "__init__.py").write_text("")

        for svc in client_services:
            out = protos_out / str(svc["name"])
            out.mkdir(parents=True, exist_ok=True)
            self._generate_proto_stubs(svc, out)

        self.write(
            "grpc_client/grpc_clients.py",
            self.render("services/grpc/client/grpc_clients.py.j2", client_services=client_services),
        )

    def _build_service_list(self) -> list[dict]:
        result = []

        services = list(self.svc.grpc_client.services)

        if self.svc.ticket_auth.enabled and "infra_tas" not in services:
            services.append("infra_tas")

        for svc_name in services:
            svc_path = get_service_path(svc_name)
            svc_manifest = get_service_manifest(svc_path)
            proto_path = get_service_proto(svc_path)

            if not proto_path.exists():
                print(f"[codegen] gRPC client: proto not found for service '{svc_name}' at {proto_path}, skipping")
                continue

            methods = self._parse_proto_methods(proto_path)
            pkg, svc_cls = self._parse_proto_package_and_service(proto_path)

            svc_addr = svc_name if self.docker else "localhost"
            svc_port = svc_manifest.service.grpc.port

            result.append({
                "name": svc_name,
                "address": f"{svc_addr}:{svc_port}",
                "proto_path": str(proto_path),
                "proto_module": proto_path.stem,
                "proto_package": pkg,
                "proto_service_name": svc_cls,
                "methods": methods,
                "name_snake": _to_snake(svc_name),
            })

        return result

    def _generate_proto_stubs(self, svc: dict, protos_out: Path) -> None:
        proto_path = Path(svc["proto_path"])

        result = subprocess.run(
            [
                sys.executable, "-m", "grpc_tools.protoc",
                f"-I{proto_path.parent}",
                f"--python_out={protos_out}",
                f"--grpc_python_out={protos_out}",
                f"--pyi_out={protos_out}",
                f"--proto_path={proto_path.parent}",
                str(proto_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[codegen] gRPC client: protoc failed for {svc['name']}:\n{result.stderr}", file=sys.stderr)
            return

        # Fix imports in pb2_grpc
        for gf in protos_out.glob(f"{proto_path.stem}_pb2_grpc.py"):
            content = gf.read_text()
            fixed = re.sub(
                r"import (\w+)_pb2 as \1__pb2",
                f"from generated.protos.clients.{svc['name']} " + r"import \1_pb2 as \1__pb2",
                content,
            )
            if content != fixed:
                gf.write_text(fixed)

        self._fix_pb2_descriptor_name(protos_out, proto_path, svc['name'])

    def _parse_proto_methods(self, proto_path: Path) -> list[dict]:
        content = proto_path.read_text(encoding="utf-8")
        methods = []
        rpc_pattern = re.compile(
            r"rpc\s+([A-Z][a-zA-Z0-9]*)\s*\(\s*(?:stream\s+)?([A-Z][A-Za-z0-9]*)\s*\)\s*"
            r"returns\s*\(\s*(?:stream\s+)?([A-Z][A-Za-z0-9]*)\s*\)\s*;"
        )
        for m in rpc_pattern.finditer(content):
            methods.append({
                "name": m.group(1),
                "input_type": m.group(2),
                "output_type": m.group(3),
            })
        return methods


    def _fix_pb2_descriptor_name(self, protos_out: Path, proto_path: Path, service_name: str) -> None:
        proto_root = get_repo_root() / "proto"
        try:
            unique_name = str(proto_path.relative_to(proto_root))
        except ValueError:
            unique_name = f"{service_name}/{proto_path.name}"

        for pb2_file in protos_out.glob(f"{proto_path.stem}_pb2.py"):
            content = pb2_file.read_text(encoding="utf-8")
            match = re.search(r"AddSerializedFile\(b'(.*?)'\)", content, re.DOTALL)
            if not match:
                continue

            serialized_repr = match.group(1)
            raw_bytes = serialized_repr.encode('latin1').decode('unicode_escape')

            fdp = descriptor_pb2.FileDescriptorProto()
            fdp.ParseFromString(raw_bytes.encode('latin1'))

            if fdp.name != unique_name:
                fdp.name = unique_name
                new_serialized = fdp.SerializeToString()
                new_escaped = new_serialized.decode('latin1').encode('unicode_escape').decode('latin1')
                content = content.replace(
                    f"AddSerializedFile(b'{serialized_repr}')",
                    f"AddSerializedFile(b'{new_escaped}')",
                )
                pb2_file.write_text(content, encoding="utf-8")
                print(f"[codegen] gRPC client: fixed descriptor name for {service_name}: {unique_name}")


    def _parse_proto_package_and_service(self, proto_path: Path) -> tuple[str, str]:
        content = proto_path.read_text(encoding="utf-8")
        pkg_match = re.search(r"package\s+([a-zA-Z0-9._]+)\s*;", content)
        pkg = pkg_match.group(1) if pkg_match else ""
        svc_match = re.search(r"service\s+([A-Z][a-zA-Z0-9]*)\s*\{", content)
        svc_cls = svc_match.group(1) if svc_match else ""
        return pkg, svc_cls


def _to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("_", "", s1).lower()
