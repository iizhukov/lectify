import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "workflow_dag_unit", Path(__file__).parents[2] / "src/engine/dag.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
WorkflowDAG = module.WorkflowDAG
DAGValidationError = module.DAGValidationError


@pytest.mark.parametrize("nodes", [
    [], [{"id": "a"}, {"id": "a"}], [{"id": ""}], [{"id": " "}], [{}], [{"id": 1}],
])
def test_invalid_node_identity_is_rejected(nodes):
    with pytest.raises(DAGValidationError):
        WorkflowDAG(nodes, [])


def test_sort_is_repeatable_and_keeps_dependency_ports():
    edge = {"from_node_id": "a", "to_node_id": "b", "from_output": "text", "to_input": "input"}
    graph = WorkflowDAG([{"id": "b"}, {"id": "a"}], [edge])
    assert [node["id"] for node in graph.topological_sort()] == ["a", "b"]
    assert [node["id"] for node in graph.topological_sort()] == ["a", "b"]
    assert graph.get_dependencies("b") == [edge]


def test_unknown_nodes_and_cycles_are_rejected():
    with pytest.raises(DAGValidationError, match="unknown"):
        WorkflowDAG([{"id": "a"}], [{"from_node_id": "a", "to_node_id": "missing"}])
    graph = WorkflowDAG([{"id": "a"}], [{"from_node_id": "a", "to_node_id": "a", "from_output": "out", "to_input": "in"}])
    with pytest.raises(DAGValidationError, match="cycles"):
        graph.topological_sort()


@pytest.mark.parametrize("edge", [
    {}, {"from_node_id": [], "to_node_id": "a"},
    {"from_node_id": "a", "to_node_id": "b"},
    {"from_node_id": "a", "to_node_id": "b", "from_output": " ", "to_input": "in"},
])
def test_malformed_edges_are_domain_errors(edge):
    with pytest.raises(DAGValidationError):
        WorkflowDAG([{"id": "a"}, {"id": "b"}], [edge])


def test_duplicate_edges_rejected_but_distinct_ports_allowed():
    edge = {"from_node_id": "a", "to_node_id": "b", "from_output": "out", "to_input": "in"}
    with pytest.raises(DAGValidationError, match="Duplicate"):
        WorkflowDAG([{"id": "a"}, {"id": "b"}], [edge, dict(edge)])
    graph = WorkflowDAG([{"id": "a"}, {"id": "b"}], [edge, dict(edge, to_input="other")])
    assert [node["id"] for node in graph.topological_sort()] == ["a", "b"]
