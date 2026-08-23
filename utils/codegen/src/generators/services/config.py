from generators.services.base import BaseGenerator
from utils import get_service_manifest, get_service_path


CONFIG_SERVICE = "infra_config"


class ConfigGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.config.enabled:
            return

        config_addr = CONFIG_SERVICE if self.docker else "localhost"
        config_port = self._resolve_config_port()

        ctx = {
            "docker": self.docker,
            "config_address": f"{config_addr}:{config_port}",
            "config_service": CONFIG_SERVICE,
            "update_interval_seconds": self.svc.config.update_interval_seconds,
        }

        self.write(
            "config/__init__.py",
            self.render("services/config/__init__.py.j2"),
        )
        self.write(
            "config/client.py",
            self.render("services/config/client.py.j2", **ctx),
        )
        self.write(
            "config/flags.py",
            self.render("services/config/flags.py.j2", **ctx),
        )
        self.write(
            "config/interceptor.py",
            self.render("services/config/interceptor.py.j2"),
        )
        self.write(
            "config/tasks.py",
            self.render("services/config/tasks.py.j2", **ctx),
        )

    def _resolve_config_port(self) -> int:
        try:
            svc_path = get_service_path(CONFIG_SERVICE)
            svc_manifest = get_service_manifest(svc_path)
            return svc_manifest.service.grpc.port
        except Exception:
            return 10011
