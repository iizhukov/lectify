from generators.services.base import BaseGenerator


class WorkflowValidationGenerator(BaseGenerator):
    def generate(self):
        if self.svc.workflow_validation.enabled:
            self.write('workflow_validation/__init__.py', self.render('services/workflow_validation.py.j2'))
