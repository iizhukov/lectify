from generators.base import BaseGenerator


class MainGenerator(BaseGenerator):
    def generate(self) -> None:
        if self.svc.main.enabled:
            self.write_root(
                "main.py",
                self.render("services/main/user_main.py.j2"),
                skip_exist=True
            )

        self.write(
            "main.py",
            self.render("services/main/main.py.j2"),
        )
        self.write_root(
            "Makefile",
            self.render("services/main/Makefile.j2"),
        )
