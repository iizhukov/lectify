from generators.services.base import BaseGenerator
from utils import get_service_manifest, get_service_path



class ConfigGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.config.enabled:
            return

        if not self.svc.config.config_service:
            raise ValueError("config.config_service is required when config is enabled")

        config_addr = self.svc.config.config_service if self.docker else "localhost"
        config_port = self._resolve_config_port()

        ctx = {
            "docker": self.docker,
            "config_address": f"{config_addr}:{config_port}",
            "config_service": self.svc.config.config_service,
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
        svc_path = get_service_path(self.svc.config.config_service)
        return get_service_manifest(svc_path).service.grpc.port
