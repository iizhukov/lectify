from config.models import ServiceManifest
from generators.services.testing import TestingGenerator


def test_isolated_tests_do_not_import_checkout_generated(tmp_path):
    manifest = ServiceManifest.model_validate({'service': {
        'name': 'isolated', 'testing': {'generated_fixtures': False},
    }})
    generator = TestingGenerator(manifest, tmp_path / 'generated')
    generator.generate()
    conftest = tmp_path / 'tests/conftest.py'
    assert 'from generated' not in conftest.read_text()
    exec(compile(conftest.read_text(), str(conftest), 'exec'), {})
    conftest.write_text('custom_fixture = True\n')
    generator.generate()
    assert conftest.read_text() == 'custom_fixture = True\n'


def test_default_scaffold_keeps_existing_fixture_contract(tmp_path):
    manifest = ServiceManifest.model_validate({'service': {'name': 'default'}})
    TestingGenerator(manifest, tmp_path / 'generated').generate()
    assert 'from generated.testing.fixtures import *' in (tmp_path / 'tests/conftest.py').read_text()
