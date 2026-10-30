"""Immutable capabilities granted by the orchestrator to one plugin assignment."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssignmentPolicy:
    execution_id: str
    node_id: str
    owner_id: str
    plugin_name: str
    llm_enabled: bool = False
    storage_enabled: bool = False
    models: frozenset[str] = field(default_factory=frozenset)
    purposes: frozenset[str] = field(default_factory=frozenset)
    file_ids: frozenset[str] = field(default_factory=frozenset)
    prompt_ids: frozenset[str] = field(default_factory=frozenset)
    artifact_names: frozenset[str] = field(default_factory=frozenset)
    max_audio_bytes: int = 25 * 1024 * 1024
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_tokens: int = 8192

    def __post_init__(self):
        for name in ('execution_id', 'node_id', 'owner_id', 'plugin_name'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError('Assignment identifiers must be nonempty bounded strings')
        if not isinstance(self.llm_enabled, bool) or not isinstance(self.storage_enabled, bool):
            raise ValueError('Assignment permission flags must be boolean')
        for name in ('models', 'purposes', 'file_ids', 'prompt_ids', 'artifact_names'):
            source = getattr(self, name)
            if not isinstance(source, (list, tuple, set, frozenset)):
                raise ValueError('Assignment capabilities must be explicit collections')
            values = frozenset(source)
            if len(values) > 256 or any(not isinstance(value, str) or not value or len(value) > 256 for value in values):
                raise ValueError('Assignment capabilities must be bounded nonempty strings')
            object.__setattr__(self, name, values)
        for name, maximum in (('max_audio_bytes', 25 * 1024 * 1024),
                              ('max_artifact_bytes', 256 * 1024 * 1024), ('max_tokens', 32768)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError('Assignment resource limits are invalid')

    def authorize_llm(self, model, purpose):
        if not self.llm_enabled or model not in self.models or purpose not in self.purposes:
            raise PermissionError('Model or purpose is not granted to this assignment')

    def authorize_file(self, file_id):
        if not self.storage_enabled or file_id not in self.file_ids:
            raise PermissionError('File is not granted to this assignment')

    def authorize_prompt(self, prompt_id):
        if not self.llm_enabled or prompt_id not in self.prompt_ids:
            raise PermissionError('Prompt is not granted to this assignment')

    def authorize_artifact(self, name):
        if not self.storage_enabled or name not in self.artifact_names:
            raise PermissionError('Artifact output is not granted to this assignment')

    @classmethod
    def from_manifest(cls, *, execution_id, node_id, owner_id, manifest, file_ids=(), prompt_ids=()):
        plugin = manifest.get('plugin', {})
        permissions = plugin.get('permissions', {})
        llm, storage = permissions.get('llm', {}), permissions.get('storage', {})
        artifacts = ()
        if storage.get('enabled') is True and storage.get('upload_artifacts', True) is True:
            artifacts = [port['name'] for port in plugin.get('outputs', []) if port.get('type') == 'artifact/file']
        return cls(execution_id=execution_id, node_id=node_id, owner_id=owner_id,
                   plugin_name=plugin.get('name', ''), llm_enabled=llm.get('enabled') is True,
                   storage_enabled=storage.get('enabled') is True,
                   models=llm.get('allowed_models', ()), purposes=llm.get('allowed_purposes', ()),
                   file_ids=file_ids, prompt_ids=prompt_ids, artifact_names=artifacts)
