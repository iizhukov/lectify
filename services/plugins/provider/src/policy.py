from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    allowed_chat_models: frozenset[str] = frozenset()
    allowed_audio_models: frozenset[str] = frozenset()
    allowed_purposes: frozenset[str] = frozenset()
    default_chat_model: str = ''
    default_audio_model: str = ''
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    max_input_chars: int = Field(default=65536, ge=1, le=262144)
    max_output_bytes: int = Field(default=1048576, ge=1, le=4194304)
    max_audio_bytes: int = Field(default=8388608, ge=1, le=8388608)
    timeout_seconds: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)
    max_concurrent: int = Field(default=4, ge=1, le=32)

    @model_validator(mode='after')
    def defaults_are_allowed(self):
        if self.default_chat_model and self.default_chat_model not in self.allowed_chat_models:
            raise ValueError('Default chat model must be explicitly allowed')
        if self.default_audio_model and self.default_audio_model not in self.allowed_audio_models:
            raise ValueError('Default audio model must be explicitly allowed')
        return self
