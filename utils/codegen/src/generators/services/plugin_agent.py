from config.plugin_models import PluginConfig, PluginManifest
from generators.plugins.protos import ProtosGenerator
from generators.services.base import BaseGenerator


class PluginAgentGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.plugin_agent.enabled and not self.svc.plugin_runtime_client.enabled:
            return
        shared = ProtosGenerator(PluginManifest(plugin=PluginConfig(name=self.svc.name)), self.output)
        shared.generate()
        self.files_written += shared.files_written
        self.write('transport.py', self.render('plugins/transport.py.j2'))
        self.write('process_supervisor.py', self.render('services/process_supervisor.py.j2'))
        if self.svc.plugin_runtime_client.enabled:
            self.write('plugin_runtime_client.py', self.render('services/plugin_runtime_client.py.j2'))
            self.write('plugin_control_client.py', self.render('services/plugin_control_client.py.j2'))
            self.write('docker_sandbox.py', self.render('services/docker_sandbox.py.j2'))
            self.write('docker_workers.py', self.render('services/docker_workers.py.j2'))
            for module in ('stream_dag', 'stream_router', 'stream_pipeline'):
                self.write(module + '.py', self.render('services/' + module + '.py.j2'))
        if not self.svc.plugin_agent.enabled:
            return
        self.write('scoped_server.py', self.render('plugins/scoped_server.py.j2'))
        self.write('plugin_agent/__init__.py', '')
        self.write('plugin_agent/proxy.py', self.render('services/plugin_agent/proxy.py.j2'))
        self.write('plugin_agent/backends.py', self.render('services/plugin_agent/backends.py.j2'))
        self.write('plugin_agent/server.py', self.render('services/plugin_agent/server.py.j2'))
        self.write('plugin_agent/controller.py', self.render('services/plugin_agent/controller.py.j2'))
