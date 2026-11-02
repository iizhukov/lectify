import json
import keyword
from typing import Any, Literal
from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator, model_serializer


BufferStrategy = Literal["size", "time", "delimiter", "full"]


class PluginBufferConfig(BaseModel):
    strategy: BufferStrategy = "size"
    chunk_size_bytes: int = Field(default=5242880, ge=1)  # 5 MB
    time_window_ms: int = Field(default=10000, ge=100)    # 10s
    delimiter: str | None = None
    overlap_bytes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_buffer(self):
        if self.overlap_bytes >= self.chunk_size_bytes:
            raise ValueError("overlap_bytes must be smaller than chunk_size_bytes")
        if self.overlap_bytes and self.strategy != "size":
            raise ValueError("overlap_bytes requires the size strategy")
        if self.strategy == "delimiter" and not self.delimiter:
            raise ValueError("the delimiter strategy requires a nonempty delimiter")
        return self


class PluginInputConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    type: str = "stream/binary"
    required: bool = True
    buffer: PluginBufferConfig = Field(default_factory=PluginBufferConfig)


class PluginOutputConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    type: str = "stream/text"
    filename: str | None = None
    target_field: str | None = None


class PluginParameterConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    type: Literal["string", "int", "float", "bool", "dict", "list"] = "string"
    default: Any = None
    required: bool = False
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if keyword.iskeyword(value) or hasattr(BaseModel, value) or value.startswith("model_"):
            raise ValueError("parameter name must be an unreserved Python field name")
        return value

    @model_validator(mode="after")
    def validate_default(self):
        if self.default is not None:
            annotation = {"string": str, "int": int, "float": float,
                          "bool": bool, "dict": dict, "list": list}[self.type]
            value = TypeAdapter(annotation).validate_python(self.default, strict=True)
            try:
                # Defaults are data. Normalize to JSON values before rendering Python literals.
                self.default = json.loads(json.dumps(value, allow_nan=False))
            except (TypeError, ValueError) as exc:
                raise ValueError("parameter defaults must contain finite JSON values") from exc
        return self


class PluginLLMPermission(BaseModel):
    enabled: bool = False
    allowed_purposes: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)


class PluginStoragePermission(BaseModel):
    enabled: bool = False
    upload_artifacts: bool = True


class PluginDatabasePermission(BaseModel):
    enabled: bool = False
    allowed_entities: list[str] = Field(default_factory=list)


class PluginNetworkPermission(BaseModel):
    egress: bool = False
    allowed_hosts: list[str] = Field(default_factory=list)


class PluginPermissionsConfig(BaseModel):
    llm: PluginLLMPermission = Field(default_factory=PluginLLMPermission)
    storage: PluginStoragePermission = Field(default_factory=PluginStoragePermission)
    database: PluginDatabasePermission = Field(default_factory=PluginDatabasePermission)
    network: PluginNetworkPermission = Field(default_factory=PluginNetworkPermission)


class PluginConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    version: str = "0.1.0"
    description: str = ""
    category: str = Field(default="general",max_length=64)
    language: Literal["python", "go", "rust", "nodejs"] = "python"
    active: bool = True
    system_packages: list[str] = Field(default_factory=list,max_length=64)

    @field_validator('system_packages')
    @classmethod
    def validate_system_packages(cls, values):
        import re
        if len(values)!=len(set(values)) or any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]{0,127}',v) for v in values):
            raise ValueError('System packages must be unique package names without options')
        return values

    @model_serializer(mode='wrap')
    def serialize(self, handler):
        result=handler(self)
        # Preserve canonical manifests and image hashes for existing versions.
        if not self.system_packages: result.pop('system_packages',None)
        return result

    inputs: list[PluginInputConfig] = Field(default_factory=list)
    outputs: list[PluginOutputConfig] = Field(default_factory=list)
    parameters: list[PluginParameterConfig] = Field(default_factory=list)
    permissions: PluginPermissionsConfig = Field(default_factory=PluginPermissionsConfig)

    @field_validator('category','description')
    @classmethod
    def validate_registry_text(cls,value):
        if '\x00' in value:
            raise ValueError('Registry text cannot contain NUL')
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ValueError('Registry text must be valid UTF-8') from None
        return value

    @model_validator(mode="after")
    def validate_names(self):
        for field in ("inputs", "outputs", "parameters"):
            names = [item.name for item in getattr(self, field)]
            if len(names) != len(set(names)):
                raise ValueError(f"{field} must have unique names")
        return self


class PluginManifest(BaseModel):
    plugin: PluginConfig
