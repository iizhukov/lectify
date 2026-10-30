from generators.plugins.base import BasePluginGenerator


class DockerfileGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write(
            "Dockerfile",
            self.render("plugins/Dockerfile.j2"),
        )
