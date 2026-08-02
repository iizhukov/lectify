from generators.services.base import BaseGenerator


class ObservabilityGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.observability.enabled:
            return

        self.write(
            "observability.py",
            self.render("services/observability/observability.py.j2"),
        )
        self.write(
            "middleware.py",
            self.render("services/observability/middleware.py.j2"),
        )
