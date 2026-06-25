"""
Transform Node Plugin — transforms data between nodes

Takes one input, produces one output, with optional transformation.
"""

import json
import re
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)


class TransformInput(BaseModel):
    """Input for transform plugin"""
    file_id: str
    data: Any  # Can be any type from previous node output


class TransformOutput(BaseModel):
    """Output from transform plugin"""
    file_id: str
    result: Any
    transform_type: str


class TransformPlugin(Plugin):
    """Transform data from one format to another"""

    id = "transform_node"
    name = "Трансформация данных"
    description = "Преобразует данные из выхода одной ноды в формат другой"
    version = "1.0.0"
    category = "transform"

    input_model = TransformInput
    output_model = TransformOutput

    parameters_schema = [
        PluginParameter(
            name="transform_type",
            type="string",
            description="Тип трансформации",
            required=True,
            default="passthrough",
            options=[
                "passthrough",  # Just pass through
                "string",       # Convert to string
                "int",          # Convert to int
                "float",        # Convert to float
                "path_replace",  # Replace file extension
                "json_parse",   # Parse JSON string
                "json_dump",    # Convert to JSON string
                "regex_extract", # Extract with regex
            ]
        ),
        PluginParameter(
            name="target_type",
            type="string",
            description="Целевой тип (для конвертации)",
            required=False,
            default="string"
        ),
        PluginParameter(
            name="pattern",
            type="string",
            description="Паттерн (для regex/path_replace)",
            required=False,
            default=""
        ),
        PluginParameter(
            name="replacement",
            type="string",
            description="Замена (для regex/path_replace)",
            required=False,
            default=""
        )
    ]

    async def execute(
        self,
        input_data: TransformInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> TransformOutput:
        """Execute data transformation"""
        transform_type = parameters.get("transform_type", "passthrough")
        data = input_data.data

        context.report_progress(10, f"Трансформация: {transform_type}...")

        try:
            result = data

            if transform_type == "passthrough":
                # Just pass through
                pass

            elif transform_type == "string":
                result = str(data)

            elif transform_type == "int":
                result = int(float(str(data)))

            elif transform_type == "float":
                result = float(data)

            elif transform_type == "path_replace":
                # Replace file extension
                pattern = parameters.get("pattern", "")
                replacement = parameters.get("replacement", "")
                if pattern and isinstance(data, str):
                    result = re.sub(rf"\{pattern}$", replacement, data)
                elif isinstance(data, str):
                    # Simple extension replacement
                    ext = parameters.get("replacement", ".txt")
                    result = data.rsplit(".", 1)[0] + ext

            elif transform_type == "json_parse":
                if isinstance(data, str):
                    result = json.loads(data)
                else:
                    result = data

            elif transform_type == "json_dump":
                result = json.dumps(data, ensure_ascii=False)

            elif transform_type == "regex_extract":
                pattern = parameters.get("pattern", "")
                if pattern and isinstance(data, str):
                    match = re.search(pattern, data)
                    result = match.group(0) if match else ""
                else:
                    result = str(data)

            else:
                context.log("warning", f"Unknown transform type: {transform_type}")

            context.report_progress(100, "Трансформация завершена")

            return TransformOutput(
                file_id=input_data.file_id,
                result=result,
                transform_type=transform_type
            )

        except Exception as e:
            context.log("error", f"Transform failed: {str(e)}")
            raise