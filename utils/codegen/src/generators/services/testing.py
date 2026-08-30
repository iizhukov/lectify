from generators.services.base import BaseGenerator


class TestingGenerator(BaseGenerator):
    __test__ = False

    def generate(self) -> None:
        # Generate TestKit inside generated/testing/
        self.write(
            "testing/__init__.py",
            self.render("services/testing/__init__.py.j2"),
        )
        self.write(
            "testing/context.py",
            self.render("services/testing/context.py.j2"),
        )
        self.write(
            "testing/fixtures.py",
            self.render("services/testing/fixtures.py.j2"),
        )

        if self.svc.config.enabled:
            self.write(
                "testing/flags.py",
                self.render("services/testing/flags.py.j2"),
            )

        if self.svc.postgres.enabled:
            self.write(
                "testing/db.py",
                self.render("services/testing/db.py.j2"),
            )

        if self.svc.kafka_producer.enabled:
            self.write(
                "testing/kafka.py",
                self.render("services/testing/kafka.py.j2"),
            )

        # Generate service-level pytest setup
        self.write_root(
            "pytest.ini",
            self.render("services/testing/pytest.ini.j2"),
            skip_exist=True,
        )
        self.write_root(
            "tests/conftest.py",
            self.render("services/testing/conftest.py.j2"),
            skip_exist=True,
        )
