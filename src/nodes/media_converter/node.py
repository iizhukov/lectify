import pathlib
import tempfile
import os

from pydub import AudioSegment

from src.nodes.basenode import BaseNode
from src.nodes.media_converter.models import MediaConverterInput, MediaConverterOutput
from src.db.models import NodeStatus
from src.utils.storage import get_storage
from src.utils.logging import get_logger


logger = get_logger(__name__)


class MediaConverterNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="media_converter",
            name="Конвертация медиа-файла",
            input_model=MediaConverterInput,
            output_model=MediaConverterOutput
        )

    def run(self, input_data: MediaConverterInput, client) -> MediaConverterOutput:
        file_id = input_data.file_id
        file_path = input_data.file_path
        
        self.update_status(file_id, NodeStatus.RUNNING, "Конвертация медиа-файла в M4A...")
        
        try:
            if file_path.startswith("minio://"):
                local_file_path = self._download_from_minio(file_path, file_id)
                should_cleanup = True  # Удалим файл после обработки
            else:
                local_file_path = file_path
                should_cleanup = False
            
            input_path = pathlib.Path(local_file_path)
            output_path = input_path.with_suffix(".m4a")

            if input_path.suffix.lower() == ".m4a":
                self.update_status(file_id, NodeStatus.COMPLETED, "Конвертация не требуется (файл уже M4A)", str(input_path))
                result = MediaConverterOutput(file_id=file_id, media_path=str(input_path))
            else:
                audio = AudioSegment.from_file(str(input_path))
                audio.export(str(output_path), format="ipod", codec="aac", bitrate="64k")
                self.update_status(file_id, NodeStatus.COMPLETED, "Файл успешно сконвертирован в M4A!", str(output_path))
                result = MediaConverterOutput(file_id=file_id, media_path=str(output_path))
            

            if should_cleanup and os.path.exists(local_file_path):
                os.remove(local_file_path)
                logger.info("temp_file_cleaned_up", file_id=file_id, path=local_file_path)
            
            return result
            
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка при конвертации: {str(e)}")
            logger.error("media_converter_error", file_id=file_id, error=str(e), exc_info=True)
            raise e
    
    def _download_from_minio(self, minio_path: str, file_id: str) -> str:
        """
        Скачивает файл из MinIO и возвращает локальный путь
        
        Args:
            minio_path: Путь в формате minio://path/to/object
            file_id: ID файла для логирования
        
        Returns:
            Локальный путь к скачанному файлу
        """
        # Извлекаем путь объекта из minio://...
        object_name = minio_path.replace("minio://", "")
        
        # Создаём временный файл
        temp_dir = tempfile.gettempdir()
        local_path = os.path.join(temp_dir, f"{file_id}_{os.path.basename(object_name)}")
        
        # Скачиваем из MinIO
        storage = get_storage()
        success = storage.download_artifact(object_name, local_path)
        
        if not success:
            raise Exception(f"Failed to download artifact from MinIO: {object_name}")
        
        logger.info(
            "artifact_downloaded_from_minio",
            file_id=file_id,
            object_name=object_name,
            local_path=local_path
        )
        
        return local_path

