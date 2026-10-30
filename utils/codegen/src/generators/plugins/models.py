from generators.plugins.base import BasePluginGenerator


class ModelsGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write(
            "models.py",
            self.render(
                "plugins/models.py.j2",
                default_literals={p.name: repr(p.default) for p in self.plugin.parameters},
                description_literals={p.name: repr(p.description) for p in self.plugin.parameters},
            ),
        )
