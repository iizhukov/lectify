from generators.services.base import BaseGenerator


class DockerfileGenerator(BaseGenerator):
    def generate(self) -> None:
        self.write_root(
            "Dockerfile",
            self.render("services/dockerfile/Dockerfile.j2"),
        )
