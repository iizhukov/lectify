from generators.base import BaseGenerator


class DbGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.postgres.enabled:
            return

        self.write("db/__init__.py", self.render("sqlalchemy/__init__.py.j2"))
        self.write("db/base.py", self.render("sqlalchemy/base.py.j2"))
        self.write("db/connection.py", self.render("sqlalchemy/connection.py.j2"))

        migrations_dir = self.svc.postgres.migration_dir or "migrations"
        self.write_root(f"{migrations_dir}/__init__.py", "")

#     def _render_initial_migration(self) -> str:
#         return '''"""0001_initial — create all tables from models."""
# from src.db.base import BaseModel
# from src.db.connection import get_engine

# import src.db as db_models  # noqa: F401 — imports all subclasses of BaseModel


# async def upgrade() -> None:
#     engine = get_engine()
#     async with engine.begin() as tx:
#         await tx.run_sync(BaseModel.metadata.create_all)

# async def downgrade() -> None:
#     engine = get_engine()
#     async with engine.begin() as tx:
#         await tx.run_sync(BaseModel.metadata.drop_all)
# '''
