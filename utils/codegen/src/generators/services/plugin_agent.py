from config.plugin_models import PluginConfig, PluginManifest
from generators.plugins.protos import ProtosGenerator
from generators.services.base import BaseGenerator


class PluginAgentGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.plugin_agent.enabled:
            return
        shared = ProtosGenerator(PluginManifest(plugin=PluginConfig(name=self.svc.name)), self.output)
        shared.generate()
        self.files_written += shared.files_written
        self.write('transport.py', self.render('plugins/transport.py.j2'))
        self.write('scoped_server.py', self.render('plugins/scoped_server.py.j2'))
        self.write('plugin_agent/__init__.py', '')
        self.write('plugin_agent/proxy.py', self.render('services/plugin_agent/proxy.py.j2'))
        self.write('plugin_agent/backends.py', self.render('services/plugin_agent/backends.py.j2'))
        self.write('plugin_agent/server.py', self.render('services/plugin_agent/server.py.j2'))
