from generators.base import BaseGenerator


class S3Generator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.minio.enabled:
            return

        self.write(
            "s3/s3.py",
            self.render("s3/s3.py.j2"),
        )
