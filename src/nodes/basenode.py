import abc
from typing import List, Type
from pydantic import BaseModel
from src.db.repository import DBRepository
from src.db.models import NodeStatus


class BaseNode(abc.ABC):
    def __init__(self, node_id: str, name: str, input_model: Type[BaseModel], output_model: Type[BaseModel]):
        self.node_id = node_id
        self.name = name
        self.input_model = input_model
        self.output_model = output_model
        self.children = []
        self._repository = DBRepository()

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

    def update_status(self, file_id: str, status: NodeStatus, message: str = None, artifact_path: str = None):
        """
        Обновляет статус выполнения ноды в базе данных для отслеживания на UI.
        """
        return self._repository.update_node(
            file_id=file_id,
            node_id=self.node_id,
            status=status,
            message=message,
            artifact_path=artifact_path
        )
