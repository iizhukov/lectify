from generators.plugins.base import BasePluginGenerator
import json


class MainGenerator(BasePluginGenerator):
    def generate(self) -> None:
        self.write('plugin_manifest.json',json.dumps(self.manifest.model_dump(mode='json'),
            sort_keys=True,separators=(',',':'),allow_nan=False))
        self.write('process_supervisor.py', self.render('services/process_supervisor.py.j2'))
        self.write('json_data.py', self.render('services/json_data.py.j2'))
        self.write('runtime_logs.py',self.render('services/runtime_logs.py.j2'))
        self.write("runtime.py", self.render("plugins/runtime.py.j2"))
        self.write("scoped_server.py", self.render("plugins/scoped_server.py.j2"))
        self.write("server.py", self.render("plugins/server.py.j2"))
        self.write(
            "main.py",
            self.render("plugins/main.py.j2"),
        )
