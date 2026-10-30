from importlib.metadata import version

from generators.plugins.base import BasePluginGenerator


class RequirementsGenerator(BasePluginGenerator):
    def generate(self) -> None:
        user_req_file = self.plugin_dir / "requirements.txt"
        user_reqs = ""
        if user_req_file.exists():
            user_reqs = user_req_file.read_text(encoding="utf-8")

        self.write(
            "requirements.txt",
            self.render(
                "plugins/requirements.txt.j2", user_requirements=user_reqs,
                grpc_version=version("grpcio-tools"), protobuf_version=version("protobuf"),
            ),
        )
