from generators.services.base import BaseGenerator
from utils import get_service_manifest, get_service_path


class TicketAuthGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.ticket_auth.enabled:
            return

        tas_port = get_service_manifest(get_service_path(self.svc.ticket_auth.tas_service)).service.grpc.port
        tas_addr = self.svc.ticket_auth.tas_service if self.docker else 'localhost'
        ctx = {'docker': self.docker, 'tas_address': f'{tas_addr}:{tas_port}'}

        self.write(
            "ticket_auth/__init__.py",
            self.render("services/ticket_auth/__init__.py.j2"),
        )
        self.write(
            "ticket_auth/client.py",
            self.render("services/ticket_auth/client.py.j2", **ctx),
        )
        self.write(
            "ticket_auth/interceptor.py",
            self.render("services/ticket_auth/interceptor.py.j2"),
        )
