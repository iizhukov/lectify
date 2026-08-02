from generated.scheduler.decorator import scheduled
from generated.logger import get_logger


log = get_logger("heartbeat")


@scheduled(name="service_heartbeat", seconds=30)
def send_heartbeat():
    """Log a heartbeat metric every 30 seconds."""
    log.info("service_heartbeat", status="alive")
