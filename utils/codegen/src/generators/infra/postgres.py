from generators.infra.base import BaseGenerator

from context import get_context_manager


class PostgresGenerator(BaseGenerator):
    def generate(self) -> None:
        context = get_context_manager()

        services: list[str] = list()

        for manifest in self.manifests:
            if not manifest.service.postgres.enabled:
                continue
            
            context.ensure_postgres_password(manifest.service.name)

            services.append(manifest.service.name)

        self.write(
            "postgres/init-script.sh",
            self.render(
                "infra/postgres/init-script.sh.j2",
                services=services,
            ),
            executable=True,
        )
