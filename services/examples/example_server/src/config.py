from generated.settings import DatabaseSettings
from pydantic import Field


class MyDatabaseSettings(DatabaseSettings):
    pool_size: int = Field(default=1, ge=1)
