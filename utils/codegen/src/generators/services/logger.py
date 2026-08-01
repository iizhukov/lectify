from generators.services.base import BaseGenerator


class LoggerGenerator(BaseGenerator):
    def generate(self) -> None:        
        self.write(
            "logger/__init__.py",
            self.render("services/logger/__init__.py.j2")
        )
        
        self.write(
            "logger/logger.py",
            self.render("services/logger/logger.py.j2")
        )
    
        self.write(
            "logger/file.py",
            self.render("services/logger/file.py.j2")
        )
        
        if self.svc.logging.loki.enabled:
            self.write(
                "logger/loki.py",
                self.render("services/logger/loki.py.j2")
            )
        
        self.write(
            "logger/setup.py",
            self.render("services/logger/setup.py.j2")
        )
