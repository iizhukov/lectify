from generators.services.base import BaseGenerator


class SettingsGenerator(BaseGenerator):
    def generate(self) -> None:
        # topics_producer = self.svc.kafka_producer.topics if self.svc.kafka_producer.enabled else []
        # topics_consumer = self.svc.kafka_consumer.topics if self.svc.kafka_consumer.enabled else []

        self.write(
            "settings/base.py",
            self.render("services/settings/base.py.j2",
                topics_producer=[],
                topics_consumer=[],
            ),
        )
        self.write(
            "settings/__init__.py",
            self.render("services/settings/settings.py.j2"),
        )
