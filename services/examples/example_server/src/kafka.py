from aiokafka.structs import ConsumerRecord

from generated.kafka.consumer import ExampleHandler as KafkaMessageHandler
from generated.logger import get_logger


log = get_logger("kafka_handler")


class ExampleHandler(KafkaMessageHandler):
    async def handle(self, msg: ConsumerRecord) -> None:
        value = msg.value.decode() if isinstance(msg.value, bytes) else str(msg.value)
        log.info(
            "user_event",
            topic=msg.topic,
            partition=msg.partition,
            offset=msg.offset,
            value=value,
        )
