from generators.services.base import BaseGenerator


class KafkaProducerGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.kafka_producer.enabled:
            return

        self.write(
            "kafka/producer.py",
            self.render("services/kafka/producer.py.j2"),
        )
