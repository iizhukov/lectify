from generators.base import BaseGenerator


class DbGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.postgres.enabled:
            return

        self.write("db/__init__.py", self.render("services/sqlalchemy/__init__.py.j2"))
        self.write("db/base.py", self.render("services/sqlalchemy/base.py.j2"))
        self.write("db/connection.py", self.render("services/sqlalchemy/connection.py.j2"))

        migrations_dir = self.svc.postgres.migration_dir or "migrations"
        self.write_root(f"{migrations_dir}/__init__.py", "")
