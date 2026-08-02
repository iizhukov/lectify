from generators.services.base import BaseGenerator


class TicketAuthGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.ticket_auth.enabled:
            return

        tas_port = 10010  # TODO: fix in future
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
