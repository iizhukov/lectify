from generated.settings import get_settings
from generated.logger import get_logger


log = get_logger("main")


async def main() -> None:
    pool_size = get_settings().database.pool_size
    log.info("Pool size (changed from config)", pool_size=pool_size)
