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
        # Keep connection credentials in memory. ConfigParser needs literal
        # percent signs escaped, e.g. when a URL contains percent-encoded data.
        config=Config()
        config.set_main_option('script_location',str(self.migrations_dir))
        config.set_main_option('sqlalchemy.url',sync_url.replace('%','%%'))
        return config
    
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
