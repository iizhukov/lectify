import os
from pathlib import Path
from typing import Optional
from datetime import datetime
from minio import Minio
from minio.error import S3Error

from src.config import config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MinIOStorage:    
    def __init__(
        self,
        endpoint: str = None,
        access_key: str = None,
        secret_key: str = None,
        secure: bool = None,
        artifacts_bucket: str = None,
        logs_bucket: str = None
    ):
        self.endpoint = endpoint or config.minio_endpoint
        self.access_key = access_key or config.minio_access_key
        self.secret_key = secret_key or config.minio_secret_key
        self.secure = secure if secure is not None else config.minio_secure
        self.artifacts_bucket = artifacts_bucket or config.minio_artifacts_bucket
        self.logs_bucket = logs_bucket or config.minio_logs_bucket
        
        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure
        )
        
        logger.info(
            "minio_client_initialized",
            endpoint=self.endpoint,
            artifacts_bucket=self.artifacts_bucket,
            logs_bucket=self.logs_bucket
        )
    
    def ensure_buckets(self):
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
        if not os.path.exists(file_path):
            logger.error("artifact_file_not_found", file_path=file_path)
            return None
        
        file_name = Path(file_path).name
        object_name = f"{workflow_id}/{node_id}/{artifact_type}/{file_name}"
        
        try:
            content_type = self._get_content_type(file_path)
            
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
    
    def upload_artifact_from_bytes(
        self,
        data: bytes,
        filename: str,
        workflow_id: str,
        node_id: str,
        artifact_type: str
    ) -> Optional[str]:
        import io
        
        object_name = f"{workflow_id}/{node_id}/{artifact_type}/{filename}"
        
        try:
            content_type = self._get_content_type_from_filename(filename)
            
            data_stream = io.BytesIO(data)
            self.client.put_object(
                self.artifacts_bucket,
                object_name,
                data_stream,
                length=len(data),
                content_type=content_type
            )
            
            logger.info(
                "artifact_uploaded_from_bytes",
                workflow_id=workflow_id,
                node_id=node_id,
                artifact_type=artifact_type,
                object_name=object_name,
                file_size=len(data)
            )
            
            return object_name
            
        except S3Error as e:
            logger.error(
                "artifact_upload_from_bytes_failed",
                workflow_id=workflow_id,
                node_id=node_id,
                error=str(e),
                exc_info=True
            )
            return None
    
    def upload_user_file(
        self,
        data: bytes,
        filename: str,
        file_id: str
    ) -> Optional[str]:
        import io

        object_name = f"uploads/{file_id}/{filename}"

        try:
            content_type = self._get_content_type_from_filename(filename)
            data_stream = io.BytesIO(data)
            self.client.put_object(
                self.artifacts_bucket,
                object_name,
                data_stream,
                length=len(data),
                content_type=content_type
            )

            logger.info(
                "user_file_uploaded",
                file_id=file_id,
                filename=filename,
                object_name=object_name,
                file_size=len(data)
            )

            return object_name

        except S3Error as e:
            logger.error(
                "user_file_upload_failed",
                file_id=file_id,
                filename=filename,
                error=str(e),
                exc_info=True
            )
            return None

    def download_artifact(
        self,
        object_name: str,
        destination_path: str
    ) -> bool:
        try:
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

    def get_log_url(self, object_name: str, expires_hours: int = 24) -> Optional[str]:
        try:
            from datetime import timedelta
            
            url = self.client.presigned_get_object(
                self.logs_bucket,
                object_name,
                expires=timedelta(hours=expires_hours)
            )

            return url
        except S3Error as e:
            logger.error("presigned_log_url_failed", object_name=object_name, error=str(e))
            return None

    def log_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.logs_bucket, object_name)
            return True
        except S3Error:
            return False

    def list_workflow_artifacts(self, workflow_id: str) -> list:
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
        execution_id: str,
        attempt: int,
        log_type: str = "node"
    ) -> Optional[str]:
        if not os.path.exists(log_file_path):
            return None

        object_name = f"executions/{execution_id}/{attempt}/{log_type}/node.log"

        try:
            self.client.fput_object(
                self.logs_bucket,
                object_name,
                log_file_path,
                content_type="text/plain"
            )

            logger.info(
                "log_uploaded",
                execution_id=execution_id,
                attempt=attempt,
                log_type=log_type,
                object_name=object_name
            )

            return object_name

        except S3Error as e:
            logger.error(
                "log_upload_failed",
                execution_id=execution_id,
                attempt=attempt,
                log_type=log_type,
                error=str(e)
            )
            return None

    def read_log(self, object_name: str) -> Optional[str]:
        import io  # noqa: F401

        try:
            response = self.client.get_object(self.logs_bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()

            return data.decode("utf-8", errors="replace")
        except S3Error:
            return None

    def get_file_bytes(self, object_name: str) -> Optional[bytes]:
        try:
            response = self.client.get_object(self.artifacts_bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()

            return data
        except S3Error:
            return None

    def _get_content_type(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        
        content_types = {
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".tex": "text/x-tex; charset=utf-8",
            ".pdf": "application/pdf",
            ".json": "application/json; charset=utf-8"
        }
        
        return content_types.get(ext, "application/octet-stream")
    
    def _get_content_type_from_filename(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        
        content_types = {
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".m4a": "audio/mp4",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".wav": "audio/wav",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".tex": "text/x-tex; charset=utf-8",
            ".pdf": "application/pdf",
            ".json": "application/json; charset=utf-8"
        }
        
        return content_types.get(ext, "application/octet-stream")


_storage_instance: Optional[MinIOStorage] = None


def get_storage() -> MinIOStorage:
    global _storage_instance
    
    if _storage_instance is None:
        _storage_instance = MinIOStorage()
        _storage_instance.ensure_buckets()
    
    return _storage_instance
