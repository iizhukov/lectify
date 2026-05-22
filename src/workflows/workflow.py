from typing import List, Set
from src.nodes.basenode import BaseNode
from src.workflows.converter import get_converter


class Workflow:
    def __init__(self, name: str, root_node: BaseNode):
        self.name = name
        self.root_node = root_node
        self.all_nodes: List[BaseNode] = []
        self._collect_and_validate_nodes(root_node, set())

    def _collect_and_validate_nodes(self, node: BaseNode, visited: Set[str]):
        if node.node_id in visited:
            return

        visited.add(node.node_id)
        self.all_nodes.append(node)
        
        for child in node.children:
            converter = get_converter(node.output_model, child.input_model)

            if not converter:
                raise TypeError(
                    f"Валидация Workflow провалена! Нет зарегистрированного конвертера "
                    f"из {node.output_model.__name__} (выход {node.node_id}) в "
                    f"{child.input_model.__name__} (вход {child.node_id})"
                )

            self._collect_and_validate_nodes(child, visited)
