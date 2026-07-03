import re
import subprocess
import sys

from pathlib import Path

from generators.base import BaseGenerator
from utils import get_service_proto


class GrpcServerGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.grpc.enabled:
            return

        proto_path = get_service_proto(self.output.parent)
        protos_out = self.output / "protos" / "server"
        protos_out.mkdir(parents=True, exist_ok=True)

        if not proto_path.exists():
            print(f"[codegen] gRPC: proto file not found at {proto_path}, skipping")
            return

        proto_info = self._parse_proto(proto_path)
        proto_info["pb2_grpc_module"] = proto_path.stem + "_pb2_grpc"

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
            print(f"[codegen] gRPC: protoc failed:\n{result.stderr}", file=sys.stderr)
        else:
            self._fix_pb2_grpc_imports(protos_out)
            print(f"[codegen] gRPC: generated pb2 files in {protos_out}")

        (protos_out / "__init__.py").write_text("")

        self.write(
            "grpc_server/grpc_app.py",
            self.render("grpc/server/grpc_app.py.j2", proto=proto_info),
        )
        self.write(
            "grpc_server/grpc_server.py",
            self.render("grpc/server/grpc_server.py.j2", proto=proto_info),
        )

    def _fix_pb2_grpc_imports(self, protos_out: Path) -> None:
        grpc_files = list(protos_out.glob("*_pb2_grpc.py"))

        for gf in grpc_files:
            content = gf.read_text()
            fixed = re.sub(
                r"import (\w+)_pb2 as \1__pb2",
                r"from generated.protos.server import \1_pb2 as \1__pb2",
                content,
            )

            if content != fixed:
                gf.write_text(fixed)

    def _parse_proto(self, proto_path: Path) -> dict:
        content = proto_path.read_text(encoding="utf-8")

        pkg_match = re.search(r"package\s+([a-zA-Z0-9._]+)\s*;", content)
        package = pkg_match.group(1) if pkg_match else ""

        svc_match = re.search(r"service\s+([A-Z][a-zA-Z0-9]*)\s*\{", content)
        service_name = svc_match.group(1) if svc_match else ""

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

        return {"package": package, "service_name": service_name, "methods": methods}
