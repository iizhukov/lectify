import pytest
from pydantic import ValidationError
from config.models import ServiceManifest


@pytest.mark.parametrize('manifest', [
    {'service': {'name': 'protected', 'user_aut': {'enabled': True}}},
    {'service': {'name': 'protected', 'ticket_ath': {'enabled': True}}},
    {'service': {'name': 'protected'}, 'user_auth': {'enabled': True}},
])
def test_misplaced_or_misspelled_security_settings_are_not_silently_ignored(manifest):
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        ServiceManifest.model_validate(manifest)


def test_business_extensions_remain_supported():
    manifest = ServiceManifest.model_validate({
        'service': {'name': 'provider'}, 'extensions': {'provider': {'allowed_models': ['small']}},
    })
    assert manifest.extensions['provider']['allowed_models'] == ['small']
