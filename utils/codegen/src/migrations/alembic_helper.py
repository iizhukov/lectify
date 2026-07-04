from pathlib import Path
from typing import Optional

from alembic.config import Config
from alembic import command


class AlembicHelper:    
    def __init__(self, migrations_dir: Path, db_url: str):
        self.migrations_dir = migrations_dir
        self.db_url = db_url
        self._config: Optional[Config] = None
    
    def get_config(self) -> Config:
        if self._config is None:
            self._ensure_env_py()
            self._config = self._create_config()

        return self._config
    
    def _create_config(self) -> Config:
        sync_url = self.db_url.replace("+asyncpg", "+psycopg2")
        
        alembic_ini = self.migrations_dir.parent / "alembic.ini"
        self._write_alembic_ini(alembic_ini, sync_url)
        
        return Config(str(alembic_ini))
    
    def _write_alembic_ini(self, path: Path, sync_url: str) -> None:
        path.write_text(f"""[alembic]
script_location = {self.migrations_dir}
sqlalchemy.url = {sync_url}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
""")
    
    def _ensure_env_py(self) -> None:
        env_py = self.migrations_dir / "env.py"

        if not env_py.exists():
            env_py.write_text("""from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
""")
    
    def upgrade(self, revision: str) -> None:
        command.upgrade(self.get_config(), revision)
    
    def downgrade(self, revision: str) -> None:
        command.downgrade(self.get_config(), revision)
