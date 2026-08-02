from generators.services.base import BaseGenerator


class SchedulerGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.scheduler.enabled:
            return

        self.write("scheduler/__init__.py", self.render("services/scheduler/__init__.py.j2"))
        self.write("scheduler/registry.py", self.render("services/scheduler/registry.py.j2"))
        self.write("scheduler/scheduler.py", self.render("services/scheduler/scheduler.py.j2"))
        self.write("scheduler/decorator.py", self.render("services/scheduler/decorator.py.j2"))

        if self.svc.postgres.enabled and self.svc.scheduler.storage == "database":
            self.write("scheduler/models.py", self.render("services/scheduler/models.py.j2"))
