from generators.infra.base import BaseGenerator

from context import get_context_manager


class MinioGenerator(BaseGenerator):
    def generate(self) -> None:
        context = get_context_manager()

        buckets = set()
        service_to_buckets: dict[str, list[str]] = dict()

        for manifest in self.manifests:
            if not manifest.service.minio.enabled:
                continue
            
            context.ensure_minio_password(manifest.service.name)

            service_to_buckets[manifest.service.name] = manifest.service.minio.buckets
            buckets.update(manifest.service.minio.buckets)

        self.write(
            "minio/init-script.sh",
            self.render(
                "infra/minio/init-script.sh.j2",
                buckets=buckets,
                service_to_buckets=service_to_buckets,
            ),
            executable=True,
        )
