import abc
import json

from datetime import datetime, timezone
from typing import Dict, List, Optional, Type, Any, Callable, Union, get_origin, get_args

from pydantic import BaseModel, Field

from src.plugins.datasource import DataSource, DataSourceManifest, OutputSource, OutputManifest


class PluginInput(BaseModel):
    pass


class PluginOutput(BaseModel):
    pass


class PluginContext:
    def __init__(
        self,
        execution_id: str,
        node_id: str,
        manifest: DataSourceManifest,
        minio_client: Any = None,
        db_session: Any = None,
    ):
        self.execution_id = execution_id
        self.node_id = node_id
        self.manifest = manifest
        self.output = OutputManifest()
        self.minio_client = minio_client
        self.db_session = db_session
        self._progress_callback: Optional[Callable] = None
        self._logs: List[Dict] = []

    def set_progress_callback(self, callback: Callable[[int, str], None]):
        self._progress_callback = callback

    def report_progress(self, percent: int, message: str):
        self._logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "info",
            "message": message,
            "progress": percent
        })
        if self._progress_callback:
            self._progress_callback(percent, message)

    def log(self, level: str, message: str, **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            **kwargs
        }

        self._logs.append(entry)

        if level == "error":
            self.report_progress(100, f"Error: {message}")

    def get_logs(self) -> List[Dict]:
        return self._logs

    def save_logs_to_minio(self, minio_path: str):
        if self.minio_client:
            self.minio_client.put_object(
                Bucket=minio_path.split("/")[0],
                Key="/".join(minio_path.split("/")[1:]),
                Body=json.dumps(self._logs, indent=2).encode(),
                ContentType="application/json"
            )


class PluginParameter(BaseModel):
    name: str
    type: str = "string"  # string, int, float, bool, dict, list, file, prompt
    description: str = ""
    required: bool = True
    default: Any = None
    options: Optional[List[Any]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class PluginSchema(BaseModel):
    input_fields: List[PluginParameter] = Field(default_factory=list)
    output_fields: List[PluginParameter] = Field(default_factory=list)
    parameters: List[PluginParameter] = Field(default_factory=list)


class Plugin(abc.ABC):
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    color: str = "#9ca3af"
    icon_svg: str = ""

    system_packages: List[str] = []

    input_model: Any = PluginInput
    output_model: Any = PluginOutput
    parameters_schema: List[PluginParameter] = Field(default_factory=list)
    data_sources: Dict[str, DataSource] = Field(default_factory=dict)
    output_artifacts: Dict[str, OutputSource] = Field(default_factory=dict)

    def get_schema(self) -> PluginSchema:
        return PluginSchema(
            input_fields=self._get_model_fields(self.input_model),
            output_fields=self._get_model_fields(self.output_model),
            parameters=self.parameters_schema
        )

    @staticmethod
    def _get_model_fields(model: Type[BaseModel]) -> List[PluginParameter]:
        
        fields = []
        for name, field_info in model.model_fields.items():
            param_type = "string"
            annotation = field_info.annotation

            origin = get_origin(annotation)
            if origin is Union:
                args = get_args(annotation)

                for arg in args:
                    if arg is not type(None):
                        annotation = arg
                        break

            if annotation == int:
                param_type = "int"
            elif annotation == float:
                param_type = "float"
            elif annotation == bool:
                param_type = "bool"

            default = field_info.default
            if hasattr(field_info, "default_factory") and field_info.default_factory is not None:
                is_required = False
            elif default is None or default is ...:
                is_required = True
            else:
                is_required = False

            fields.append(PluginParameter(
                name=name,
                type=param_type,
                required=is_required,
                description=getattr(field_info, "description", "") or ""
            ))

        return fields

    @abc.abstractmethod
    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> PluginOutput:
        pass
