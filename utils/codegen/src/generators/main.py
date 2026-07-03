from generators.base import BaseGenerator


class MainGenerator(BaseGenerator):
    def generate(self) -> None:
        if self.svc.main.enabled:
            self.write_root(
                "src/main.py",
                self.render("main/user_main.py.j2"),
                skip_exist=True
            )

        self.write_root(
            "main.py",
            self.render("main/main.py.j2"),
        )
