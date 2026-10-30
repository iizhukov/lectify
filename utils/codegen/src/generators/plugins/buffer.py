from generators.plugins.base import BasePluginGenerator


class BufferGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write(
            "buffer.py",
            self.render("plugins/buffer.py.j2"),
        )
