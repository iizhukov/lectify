from generators.plugins.base import BasePluginGenerator


class MainGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write('process_supervisor.py', self.render('services/process_supervisor.py.j2'))
        self.write('json_data.py', self.render('services/json_data.py.j2'))
        self.write("runtime.py", self.render("plugins/runtime.py.j2"))
        self.write("scoped_server.py", self.render("plugins/scoped_server.py.j2"))
        self.write("server.py", self.render("plugins/server.py.j2"))
        self.write(
            "main.py",
            self.render("plugins/main.py.j2"),
        )
