from generators.infra.base import BaseGenerator
from context import get_context_manager


class KafkaGenerator(BaseGenerator):
    def generate(self) -> None:
        context = get_context_manager()

        service_to_topics: dict[str, list[str]] = {}

        for manifest in self.manifests:
            svc = manifest.service
            topics: list[str] = []

            if svc.kafka_producer.enabled:
                context.ensure_kafka_password(svc.name)
                topics.extend(svc.kafka_producer.topics)

            if svc.kafka_consumer.enabled:
                context.ensure_kafka_password(svc.name)
                topics.extend(svc.kafka_consumer.topics)

            if topics:
                service_to_topics[svc.name] = list(set(topics))

        if not service_to_topics:
            return

        self.write(
            "kafka/init-script.sh",
            self.render(
                "infra/kafka/init-script.sh.j2",
                service_to_topics=service_to_topics,
            ),
            executable=True,
        )
