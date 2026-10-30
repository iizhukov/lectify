# pytest fixtures for orchestrator
from generated.testing.fixtures import *  # noqa: F401, F403
from generated.testing.context import MockServicerContext
from types import SimpleNamespace
import pytest


class AuthenticatedContext(MockServicerContext):
    def __init__(self):
        super().__init__()
        self.lectify_principal = SimpleNamespace(user_id='user_1', is_admin=True)


@pytest.fixture
def mock_context():
    return AuthenticatedContext()
