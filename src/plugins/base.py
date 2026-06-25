"""
Plugin Interface — base classes for all plugins
"""

import abc
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Callable

from pydantic import BaseModel, Field


class PluginInput(BaseModel):
    """Base class for plugin input data"""
    pass


class PluginOutput(BaseModel):
    """Base class for plugin output data"""
    pass


class PluginContext:
    """
    Context passed to plugin during execution.
    Provides access to storage, progress reporting, and logging.
    """

    def __init__(
        self,
        execution_id: str,
        node_id: str,
        minio_client: Any = None,
        db_session: Any = None
    ):
        self.execution_id = execution_id
        self.node_id = node_id
        self.minio_client = minio_client
        self.db_session = db_session
        self._progress_callback: Optional[Callable] = None
        self._logs: List[Dict] = []

    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """Set callback for progress updates"""
        self._progress_callback = callback

    def report_progress(self, percent: int, message: str):
        """Report execution progress"""
        self._logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "info",
            "message": message,
            "progress": percent
        })
        if self._progress_callback:
            self._progress_callback(percent, message)

    def log(self, level: str, message: str, **kwargs):
        """Log a message"""
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
        """Get all logged messages"""
        return self._logs

    def save_logs_to_minio(self, minio_path: str):
        """Save logs to MinIO"""
        if self.minio_client:
            self.minio_client.put_object(
                Bucket=minio_path.split("/")[0],
                Key="/".join(minio_path.split("/")[1:]),
                Body=json.dumps(self._logs, indent=2).encode(),
                ContentType="application/json"
            )


class PluginParameter(BaseModel):
    """Schema for a plugin parameter"""
    name: str
    type: str = "string"  # string, int, float, bool, dict, list, file, prompt
    description: str = ""
    required: bool = True
    default: Any = None
    options: Optional[List[Any]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class PluginSchema(BaseModel):
    """Schema describing plugin's interface"""
    input_fields: List[PluginParameter] = Field(default_factory=list)
    output_fields: List[PluginParameter] = Field(default_factory=list)
    parameters: List[PluginParameter] = Field(default_factory=list)


class Plugin(abc.ABC):
    """
    Base class for all plugins.

    Each plugin must:
    1. Define input_model (PluginInput subclass)
    2. Define output_model (PluginOutput subclass)
    3. Define parameters_schema (list of PluginParameter)
    4. Implement execute() method
    """

    id: str = ""  # Plugin ID (e.g., "media_converter")
    name: str = ""  # Human-readable name
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"  # media, ai, transform, io

    input_model: Type[PluginInput] = PluginInput
    output_model: Type[PluginOutput] = PluginOutput
    parameters_schema: List[PluginParameter] = Field(default_factory=list)

    def get_schema(self) -> PluginSchema:
        """Get full plugin schema for UI generation"""
        return PluginSchema(
            input_fields=self._get_model_fields(self.input_model),
            output_fields=self._get_model_fields(self.output_model),
            parameters=self.parameters_schema
        )

    @staticmethod
    def _get_model_fields(model: Type[BaseModel]) -> List[PluginParameter]:
        """Extract field definitions from Pydantic model"""
        from typing import Union, get_origin, get_args
        fields = []
        for name, field_info in model.model_fields.items():
            param_type = "string"
            annotation = field_info.annotation

            # Handle Optional/Union types by extracting inner type
            origin = get_origin(annotation)
            if origin is Union:
                # Get non-None type from Optional
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

            # Check if field is required based on default value
            default = field_info.default
            if hasattr(field_info, "default_factory") and field_info.default_factory is not None:
                is_required = False  # Has default factory
            elif default is None or default is ...:
                is_required = True  # Required
            else:
                is_required = False  # Has default

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
        input_data: PluginInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> PluginOutput:
        """
        Execute the plugin.

        Args:
            input_data: Input data from previous node
            context: Execution context (progress, logging, storage)
            parameters: Node-specific parameters (from node template)

        Returns:
            PluginOutput: Output data for next nodes
        """
        pass

    def get_dockerfile_template(self) -> str:
        """Return Dockerfile template for this plugin"""
        return """FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "plugin_runner"]
"""