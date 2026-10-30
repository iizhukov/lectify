import subprocess
import sys

from generators.plugins.base import BasePluginGenerator
from utils import get_repo_root


class ProtosGenerator(BasePluginGenerator):
    """Compile the shared plugin/agent contract into each independent image."""

    def generate(self) -> None:
        proto_root = get_repo_root() / "proto"
        proto = proto_root / "plugins" / "index.proto"
        destination = self.output / "protos"
        destination.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                sys.executable, "-m", "grpc_tools.protoc",
                f"-I{proto_root}",
                f"--python_out={destination}",
                f"--grpc_python_out={destination}",
                f"--pyi_out={destination}",
                str(proto),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(f"Plugin protocol compilation failed: {result.stderr}")
        for package in (self.output, destination, destination / "plugins"):
            (package / "__init__.py").touch()
        grpc_module = destination / "plugins" / "index_pb2_grpc.py"
        grpc_module.write_text(
            grpc_module.read_text(encoding="utf-8").replace(
                "from plugins import index_pb2",
                "from generated.protos.plugins import index_pb2",
            ),
            encoding="utf-8",
        )
        self.files_written += 6
