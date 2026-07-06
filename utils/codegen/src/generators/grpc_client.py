import re
import subprocess
import sys

from pathlib import Path

from generators.base import BaseGenerator
from utils import get_service_proto, get_service_path, get_service_manifest


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
            self.render("grpc/client/grpc_clients.py.j2", client_services=client_services),
        )

    def _build_service_list(self) -> list[dict]:
        result = []

        for svc_name in self.svc.grpc_client.services:
            svc_path = get_service_path(svc_name)
            svc_manifest = get_service_manifest(svc_path)
            proto_path = get_service_proto(svc_path)

            if not proto_path.exists():
                print(f"[codegen] gRPC client: proto not found for service '{svc_name}' at {proto_path}, skipping")
                continue

            methods = self._parse_proto_methods(proto_path)
            pkg, svc_cls = self._parse_proto_package_and_service(proto_path)

            svc_addr = "localhost"
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

    def _parse_proto_package_and_service(self, proto_path: Path) -> tuple[str, str]:
        content = proto_path.read_text(encoding="utf-8")
        pkg_match = re.search(r"package\s+([a-zA-Z0-9._]+)\s*;", content)
        pkg = pkg_match.group(1) if pkg_match else ""
        svc_match = re.search(r"service\s+([A-Z][a-zA-Z0-9]*)\s*\{", content)
        svc_cls = svc_match.group(1) if svc_match else ""
        return pkg, svc_cls


def _to_snake(name: str) -> str:
    """Convert PascalCase or kebab-case to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("_", "", s1).lower()
