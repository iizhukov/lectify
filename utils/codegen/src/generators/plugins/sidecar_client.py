from generators.plugins.base import BasePluginGenerator


class SidecarClientGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write("transport.py", self.render("plugins/transport.py.j2"))
        self.write(
            "sidecar_client.py",
            self.render("plugins/sidecar_client.py.j2"),
        )
