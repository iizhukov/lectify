
from generators.services.base import BaseGenerator


class KafkaConsumerGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.kafka_consumer.enabled:
            return

        self.write(
            "kafka/consumer.py",
            self.render("services/kafka/consumer.py.j2"),
        )
