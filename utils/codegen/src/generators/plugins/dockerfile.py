from generators.plugins.base import BasePluginGenerator


class DockerfileGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write('Dockerfile.controlled', self.render('plugins/Dockerfile.controlled.j2'))
        self.write(
            "Dockerfile",
            self.render("plugins/Dockerfile.j2"),
        )
