"""
MinIO клиент для хранения артефактов и логов
"""
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
from minio import Minio
from minio.error import S3Error

from src.utils.logging import get_logger

logger = get_logger(__name__)


class MinIOStorage:
    """Класс для работы с MinIO объектным хранилищем"""
    
    def __init__(
        self,
        endpoint: str = "localhost:9000",
        access_key: str = "minioadmin",
        secret_key: str = "minioadmin",
        secure: bool = False
    ):
        """
        Инициализация MinIO клиента
        
        Args:
            endpoint: Адрес MinIO сервера
            access_key: Access key
            secret_key: Secret key
            secure: Использовать HTTPS
        """
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        
        self.artifacts_bucket = "artifacts"
        self.logs_bucket = "logs"
        
        logger.info(
            "minio_client_initialized",
            endpoint=endpoint,
            artifacts_bucket=self.artifacts_bucket,
            logs_bucket=self.logs_bucket
        )
    
    def ensure_buckets(self):
        """Проверка и создание бакетов если их нет"""
        for bucket in [self.artifacts_bucket, self.logs_bucket]:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info("bucket_created", bucket=bucket)
            except S3Error as e:
                logger.error("bucket_creation_failed", bucket=bucket, error=str(e))
    
    def upload_artifact(
        self,
        file_path: str,
        workflow_id: str,
        node_id: str,
        artifact_type: str
    ) -> Optional[str]:
        """
        Загрузка артефакта в MinIO
        
        Args:
            file_path: Путь к файлу
            workflow_id: ID воркфлоу
            node_id: ID ноды
            artifact_type: Тип артефакта (audio, text, markdown, latex, pdf)
        
        Returns:
            Путь к объекту в MinIO или None при ошибке
        """
        if not os.path.exists(file_path):
            logger.error("artifact_file_not_found", file_path=file_path)
            return None
        
        # Структура: artifacts/{workflow_id}/{node_id}/{artifact_type}/{filename}
        file_name = Path(file_path).name
        object_name = f"{workflow_id}/{node_id}/{artifact_type}/{file_name}"
        
        try:
            # Определяем content type
            content_type = self._get_content_type(file_path)
            
            # Загружаем файл
            self.client.fput_object(
                self.artifacts_bucket,
                object_name,
                file_path,
                content_type=content_type
            )
            
            logger.info(
                "artifact_uploaded",
                workflow_id=workflow_id,
                node_id=node_id,
                artifact_type=artifact_type,
                object_name=object_name,
                file_size=os.path.getsize(file_path)
            )
            
            return object_name
            
        except S3Error as e:
            logger.error(
                "artifact_upload_failed",
                workflow_id=workflow_id,
                node_id=node_id,
                error=str(e),
                exc_info=True
            )
            return None
    
    def download_artifact(
        self,
        object_name: str,
        destination_path: str
    ) -> bool:
        """
        Скачивание артефакта из MinIO
        
        Args:
            object_name: Путь к объекту в MinIO
            destination_path: Путь для сохранения файла
        
        Returns:
            True если успешно, False при ошибке
        """
        try:
            # Создаём директорию если её нет
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
            
            self.client.fget_object(
                self.artifacts_bucket,
                object_name,
                destination_path
            )
            
            logger.info(
                "artifact_downloaded",
                object_name=object_name,
                destination=destination_path
            )
            
            return True
            
        except S3Error as e:
            logger.error(
                "artifact_download_failed",
                object_name=object_name,
                error=str(e),
                exc_info=True
            )
            return False
    
    def get_artifact_url(self, object_name: str, expires_hours: int = 24) -> Optional[str]:
        """
        Получить presigned URL для скачивания артефакта
        
        Args:
            object_name: Путь к объекту в MinIO
            expires_hours: Время жизни ссылки в часах
        
        Returns:
            URL для скачивания или None при ошибке
        """
        try:
            from datetime import timedelta
            
            url = self.client.presigned_get_object(
                self.artifacts_bucket,
                object_name,
                expires=timedelta(hours=expires_hours)
            )
            
            return url
            
        except S3Error as e:
            logger.error(
                "presigned_url_generation_failed",
                object_name=object_name,
                error=str(e)
            )
            return None
    
    def list_workflow_artifacts(self, workflow_id: str) -> list:
        """
        Получить список всех артефактов воркфлоу
        
        Args:
            workflow_id: ID воркфлоу
        
        Returns:
            Список объектов
        """
        try:
            objects = self.client.list_objects(
                self.artifacts_bucket,
                prefix=f"{workflow_id}/",
                recursive=True
            )
            
            artifacts = []
            for obj in objects:
                artifacts.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag
                })
            
            return artifacts
            
        except S3Error as e:
            logger.error(
                "list_artifacts_failed",
                workflow_id=workflow_id,
                error=str(e)
            )
            return []
    
    def delete_workflow_artifacts(self, workflow_id: str) -> bool:
        """
        Удалить все артефакты воркфлоу
        
        Args:
            workflow_id: ID воркфлоу
        
        Returns:
            True если успешно
        """
        try:
            objects = self.client.list_objects(
                self.artifacts_bucket,
                prefix=f"{workflow_id}/",
                recursive=True
            )
            
            for obj in objects:
                self.client.remove_object(self.artifacts_bucket, obj.object_name)
            
            logger.info("workflow_artifacts_deleted", workflow_id=workflow_id)
            return True
            
        except S3Error as e:
            logger.error(
                "delete_artifacts_failed",
                workflow_id=workflow_id,
                error=str(e)
            )
            return False
    
    def upload_log(
        self,
        log_file_path: str,
        log_type: str = "application"
    ) -> Optional[str]:
        """
        Загрузка лог-файла в MinIO
        
        Args:
            log_file_path: Путь к лог-файлу
            log_type: Тип лога (application, system, etc.)
        
        Returns:
            Путь к объекту в MinIO или None при ошибке
        """
        if not os.path.exists(log_file_path):
            return None
        
        # Структура: logs/{log_type}/{date}/{filename}
        date_str = datetime.now().strftime("%Y/%m/%d")
        file_name = Path(log_file_path).name
        object_name = f"{log_type}/{date_str}/{file_name}"
        
        try:
            self.client.fput_object(
                self.logs_bucket,
                object_name,
                log_file_path,
                content_type="text/plain"
            )
            
            logger.info(
                "log_uploaded",
                log_type=log_type,
                object_name=object_name
            )
            
            return object_name
            
        except S3Error as e:
            logger.error(
                "log_upload_failed",
                log_type=log_type,
                error=str(e)
            )
            return None
    
    def _get_content_type(self, file_path: str) -> str:
        """Определить content type по расширению файла"""
        ext = Path(file_path).suffix.lower()
        
        content_types = {
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".tex": "text/x-tex",
            ".pdf": "application/pdf",
            ".json": "application/json"
        }
        
        return content_types.get(ext, "application/octet-stream")


# Глобальный экземпляр MinIO клиента
_storage_instance: Optional[MinIOStorage] = None


def get_storage() -> MinIOStorage:
    """Получить глобальный экземпляр MinIO клиента"""
    global _storage_instance
    
    if _storage_instance is None:
        _storage_instance = MinIOStorage()
        _storage_instance.ensure_buckets()
    
    return _storage_instance
