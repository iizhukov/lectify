from generators.services.base import BaseGenerator


class UserAuthGenerator(BaseGenerator):
    def generate(self) -> None:
        if not self.svc.user_auth.enabled:
            return
        for filename in ('__init__.py', 'client.py', 'interceptor.py'):
            self.write(f'user_auth/{filename}', self.render(f'services/user_auth/{filename}.j2'))
