from generators.services.base import BaseGenerator


class HttpGenerator(BaseGenerator):
    def generate(self) -> None:
        if self.svc.http.enabled:
            self.write('http/__init__.py', '')
            self.write('http/client.py', self.render('services/http/client.py.j2'))
