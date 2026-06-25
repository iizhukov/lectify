import abc
from typing import Type, Optional
from pydantic import BaseModel
from src.db.repository import Repository
from src.db.models import NodeStatus
from src.utils.storage import get_storage
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BaseNode(abc.ABC):
    def __init__(self, node_id: str, name: str, input_model: Type[BaseModel], output_model: Type[BaseModel]):
        self.node_id = node_id
        self.name = name
        self.input_model = input_model
        self.output_model = output_model
        self.children = []
        self._repository = Repository()
        self._storage = get_storage()

    def add_child(self, child: 'BaseNode'):
        """Добавляет дочернюю ноду"""
        self.children.append(child)

    @abc.abstractmethod
    def run(self, input_data: BaseModel, client) -> BaseModel:
        """
        Метод выполнения ноды. Принимает Pydantic модель на вход и 
        возвращает другую Pydantic модель на выход.
        """
        pass

    def update_status(
        self,
        workflow_id: str,
        status: NodeStatus,
        message: str = None,
        artifact_path: str = None
    ):
        """
        Обновляет статус выполнения ноды в базе данных для отслеживания на UI.
        """
        return self._repository.update_node(
            workflow_id=workflow_id,
            node_id=self.node_id,
            status=status,
            message=message,
            artifact_path=artifact_path
        )
    
    def save_artifact(
        self,
        file_id: str,
        workflow_id: str,
        artifact_path: str,
        artifact_type: str
    ) -> Optional[str]:
        """
        Сохраняет артефакт в MinIO и создаёт запись в БД
        
        Args:
            file_id: ID файла
            workflow_id: ID воркфлоу
            artifact_path: Локальный путь к артефакту
            artifact_type: Тип артефакта (audio, text, markdown, latex, pdf)
        
        Returns:
            MinIO путь к артефакту или None при ошибке
        """
        try:
            # Загружаем в MinIO
            minio_path = self._storage.upload_artifact(
                file_path=artifact_path,
                workflow_id=workflow_id,
                node_id=self.node_id,
                artifact_type=artifact_type
            )
            
            if minio_path:
                # Создаём запись в БД
                self._repository.create_artifact(
                    workflow_id=workflow_id,
                    file_id=file_id,
                    node_id=self.node_id,
                    path=artifact_path,
                    minio_path=minio_path
                )
                
                logger.info(
                    "artifact_saved",
                    workflow_id=workflow_id,
                    node_id=self.node_id,
                    artifact_type=artifact_type,
                    minio_path=minio_path
                )
                
                return minio_path
            
            return None
            
        except Exception as e:
            logger.error(
                "artifact_save_failed",
                workflow_id=workflow_id,
                node_id=self.node_id,
                error=str(e),
                exc_info=True
            )
            return None
