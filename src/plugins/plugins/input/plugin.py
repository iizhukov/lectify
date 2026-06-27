"""
Input Plugin — динамический источник данных для workflow

Плагин-источник для передачи файлов в граф.
Получает file_id через input_mapping и возвращает метаданные файла.
"""

from typing import Any, Dict, Optional

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter,
)
from src.plugins.plugins.input.models import InputPluginInput, InputPluginOutput


class InputPlugin(Plugin):
    """
    Источник данных для workflow.

    Получает file_id через input_mapping при запуске execution,
    загружает метаданные файла из БД и передаёт downstream нодам:
      - file_id
      - file_path (minio:// URL)
      - input_type
    """

    id = "input"
    name = "Входные данные"
    description = "Источник данных для workflow — передаёт файл дальше по графу"
    version = "1.0.0"
    category = "io"
    color = "#10b981"  # Зелёный цвет для source node
    icon_svg = (
        '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>'
        '</svg>'
    )

    input_model = InputPluginInput
    output_model = InputPluginOutput

    parameters_schema = [
        PluginParameter(
            name="input_type",
            type="string",
            description="Тип ожидаемого файла",
            required=True,
            default="any",
            options=["audio", "video", "pdf", "text", "image", "any"],
        ),
    ]

    async def execute(
        self,
        input_data: InputPluginInput,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> InputPluginOutput:
        """
        Загружает метаданные файла и возвращает их.

        file_id и метаданные должны быть переданы через input_mapping в node definition.
        Оркестратор передаёт все метаданные через __input, чтобы плагин не обращался к БД.
        """
        input_type = parameters.get("input_type", "any")

        # file_id приходит через input_data (InputPluginInput)
        file_id = input_data.file_id

        if not file_id:
            raise ValueError(
                "file_id не передан. Input плагин требует file_id через input_mapping "
                "при создании execution. Пример: {'target_field': 'file_id', 'source': '$__input.{node_id}.file_id'}"
            )

        context.report_progress(20, f"Загрузка файла: {file_id}")

        # Метаданные файла должны быть переданы оркестратором через input_data
        # Если они не переданы, попробуем загрузить из БД (fallback для обратной совместимости)
        if input_data.minio_path:
            minio_path = input_data.minio_path
            filename = input_data.filename or "unknown"
            file_path = f"minio://{minio_path}"
        else:
            # Fallback: загрузить из БД (может не работать в контейнере)
            file_metadata = self._load_file_from_db(file_id, context)
            if not file_metadata:
                raise ValueError(
                    f"Файл с id={file_id} не найден. "
                    "Убедитесь что файл был загружен и что оркестратор передал метаданные через input_mapping."
                )
            minio_path = file_metadata["minio_path"]
            filename = file_metadata["filename"]
            file_path = f"minio://{minio_path}"

        context.report_progress(100, f"Файл «{filename}» загружен")

        return InputPluginOutput(
            file_id=file_id,
            file_path=file_path,
            input_type=input_type,
        )

    def _load_file_from_db(self, file_id: str, context: PluginContext) -> Optional[dict]:
        """Загружает метаданные файла из БД по file_id."""
        try:
            from src.db.database import SessionLocal
            from src.db.entity import DBFile

            session = SessionLocal()
            try:
                db_file = session.query(DBFile).filter(DBFile.id == file_id).first()
                if db_file:
                    return {
                        "filename": db_file.filename,
                        "minio_path": db_file.minio_path,
                        "size": db_file.size,
                        "content_type": db_file.content_type,
                    }
            finally:
                session.close()
        except Exception as e:
            context.log("error", f"Failed to load file from DB: {str(e)}")
            return None
        return None
