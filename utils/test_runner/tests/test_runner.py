import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('lectify_test_runner', Path(__file__).parents[2] / 'test.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_discovers_both_pytest_filename_patterns_and_ignores_venv(tmp_path):
    for path in ('services/a/tests/test_one.py', 'plugins/b/tests/flow_test.py',
                 'services/a/venv/pkg/tests/test_vendor.py', 'services/a/generated/tests/test_generated.py'):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    assert set(runner.discover(tmp_path)) == {tmp_path / 'services/a', tmp_path / 'plugins/b'}


def test_empty_execution_fails_instead_of_false_success(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    with pytest.raises(SystemExit) as error:
        runner.main(['--no-generate'])
    assert error.value.code != 0
    assert runner.main(['--list']) == 0


def test_suites_run_in_separate_directories_and_failure_is_preserved(tmp_path, monkeypatch):
    suites = [tmp_path / 'services/a', tmp_path / 'services/b']
    for suite in suites:
        tests = suite / 'tests'
        tests.mkdir(parents=True)
        (tests / 'test_service.py').touch()
    calls = []
    def run(command, **kwargs):
        calls.append(kwargs['cwd'])
        return SimpleNamespace(returncode=1 if kwargs['cwd'] == suites[0] else 0)
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main(['--no-generate']) == 1
    assert calls == suites
