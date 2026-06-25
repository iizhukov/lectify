import pytest
from datetime import datetime
from pydantic import ValidationError


class TestPydanticModels:
    """Tests for Pydantic models"""

    def test_user_model(self):
        """UserModel should accept all fields"""
        from src.db.models import UserModel

        user = UserModel(
            id="user-123",
            username="testuser",
            email="test@example.com"
        )

        assert user.id == "user-123"
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    def test_plugin_model(self):
        """PluginModel should accept all fields"""
        from src.db.models import PluginModel

        plugin = PluginModel(
            id="test_plugin",
            name="Test Plugin",
            description="A test plugin",
            version="1.0.0",
            plugin_path="plugins/test_plugin",
            input_model="TestInput",
            output_model="TestOutput",
            parameters_schema={"param1": {"type": "string", "required": True}},
            is_active=True
        )

        assert plugin.id == "test_plugin"
        assert plugin.name == "Test Plugin"
        assert plugin.version == "1.0.0"
        assert plugin.is_active is True

    def test_input_mapping_rule(self):
        """InputMappingRule should accept all fields"""
        from src.db.models import InputMappingRule

        rule = InputMappingRule(
            target_field="media_path",
            source="$media_converter.output.media_path",
            transform="passthrough"
        )

        assert rule.target_field == "media_path"
        assert rule.source == "$media_converter.output.media_path"
        assert rule.transform == "passthrough"

    def test_input_mapping_rule_default_transform(self):
        """InputMappingRule should have default transform"""
        from src.db.models import InputMappingRule

        rule = InputMappingRule(
            target_field="file_id",
            source="$node.output.file_id"
        )

        assert rule.transform == "passthrough"

    def test_node_template_model(self):
        """NodeTemplateModel should accept all fields"""
        from src.db.models import NodeTemplateModel

        template = NodeTemplateModel(
            id="node-123",
            plugin_id="media_converter",
            name="Convert Media",
            description="Convert media to M4A",
            parameters={"format": "m4a"},
            input_mapping=[
                {"target_field": "file_path", "source": "$input.output.file_path"}
            ]
        )

        assert template.id == "node-123"
        assert template.plugin_id == "media_converter"
        assert template.parameters == {"format": "m4a"}
        assert len(template.input_mapping) == 1

    def test_prompt_model(self):
        """PromptModel should accept all fields"""
        from src.db.models import PromptModel

        prompt = PromptModel(
            id="prompt-123",
            name="Test Prompt",
            system_prompt="You are a helpful assistant.",
            user_prompt_template="Summarize: {{text}}",
            variables=["text"]
        )

        assert prompt.id == "prompt-123"
        assert prompt.name == "Test Prompt"
        assert prompt.variables == ["text"]

    def test_workflow_graph_node(self):
        """WorkflowGraphNode should accept all fields"""
        from src.db.models import WorkflowGraphNode

        node = WorkflowGraphNode(
            id="node_1",
            template_id="template-123",
            position_x=100,
            position_y=200
        )

        assert node.id == "node_1"
        assert node.position_x == 100
        assert node.position_y == 200

    def test_workflow_graph_edge(self):
        """WorkflowGraphEdge should accept all fields"""
        from src.db.models import WorkflowGraphEdge

        edge = WorkflowGraphEdge(
            from_node="node_1",
            to_node="node_2"
        )

        assert edge.from_node == "node_1"
        assert edge.to_node == "node_2"

    def test_workflow_graph(self):
        """WorkflowGraph should contain nodes and edges"""
        from src.db.models import WorkflowGraph, WorkflowGraphNode, WorkflowGraphEdge

        graph = WorkflowGraph(
            nodes=[
                WorkflowGraphNode(id="node_1", template_id="t1"),
                WorkflowGraphNode(id="node_2", template_id="t2")
            ],
            edges=[
                WorkflowGraphEdge(from_node="node_1", to_node="node_2")
            ]
        )

        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1

    def test_workflow_template_model(self):
        """WorkflowTemplateModel should accept all fields"""
        from src.db.models import WorkflowTemplateModel, WorkflowGraph

        template = WorkflowTemplateModel(
            id="workflow-123",
            name="Test Workflow",
            description="A test workflow",
            graph=WorkflowGraph(nodes=[], edges=[]),
            is_public=False
        )

        assert template.id == "workflow-123"
        assert template.name == "Test Workflow"
        assert template.is_public is False

    def test_execution_node_model(self):
        """ExecutionNodeModel should accept all fields"""
        from src.db.models import ExecutionNodeModel

        node = ExecutionNodeModel(
            id="exec-node-123",
            execution_id="exec-123",
            node_id="node_1",
            status="running",
            progress_percent=50,
            progress_message="Processing..."
        )

        assert node.id == "exec-node-123"
        assert node.status == "running"
        assert node.progress_percent == 50

    def test_execution_model(self):
        """ExecutionModel should accept all fields"""
        from src.db.models import ExecutionModel

        execution = ExecutionModel(
            id="exec-123",
            workflow_template_id="workflow-123",
            file_id="file-123",
            status="running"
        )

        assert execution.id == "exec-123"
        assert execution.status == "running"


class TestEnums:
    """Tests for enum types"""

    def test_execution_status_values(self):
        """ExecutionStatus should have correct values"""
        from src.db.models import ExecutionStatus

        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.RUNNING == "running"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.CANCELLED == "cancelled"

    def test_node_execution_status_values(self):
        """NodeExecutionStatus should have correct values"""
        from src.db.models import NodeExecutionStatus

        assert NodeExecutionStatus.PENDING == "pending"
        assert NodeExecutionStatus.RUNNING == "running"
        assert NodeExecutionStatus.COMPLETED == "completed"
        assert NodeExecutionStatus.FAILED == "failed"
        assert NodeExecutionStatus.SKIPPED == "skipped"


class TestSQLAlchemyEntities:
    """Tests for SQLAlchemy entities"""

    def test_db_user_creation(self):
        """DBUser should be createable"""
        from src.db.entities import DBUser

        user = DBUser(
            id="user-123",
            username="testuser",
            email="test@example.com"
        )

        assert user.id == "user-123"
        assert user.username == "testuser"

    def test_db_plugin_creation(self):
        """DBPlugin should be createable"""
        from src.db.entities import DBPlugin

        plugin = DBPlugin(
            id="test_plugin",
            name="Test Plugin",
            version="1.0.0",
            plugin_path="plugins/test",
            input_model="Input",
            output_model="Output",
            is_active=True
        )

        assert plugin.id == "test_plugin"
        assert plugin.is_active is True

    def test_db_node_template_creation(self):
        """DBNodeTemplate should be createable"""
        from src.db.entities import DBNodeTemplate

        template = DBNodeTemplate(
            id="node-123",
            plugin_id="plugin-123",
            name="Test Node",
            parameters={}
        )

        assert template.id == "node-123"
        assert template.plugin_id == "plugin-123"

    def test_db_workflow_template_creation(self):
        """DBWorkflowTemplate should be createable"""
        from src.db.entities import DBWorkflowTemplate

        template = DBWorkflowTemplate(
            id="wf-123",
            name="Test Workflow",
            graph={"nodes": [], "edges": []},
            is_public=False
        )

        assert template.id == "wf-123"
        assert template.is_public is False

    def test_db_execution_creation(self):
        """DBExecution should be createable"""
        from src.db.entities import DBExecution

        execution = DBExecution(
            id="exec-123",
            workflow_template_id="wf-123",
            file_id="file-123",
            status="pending"
        )

        assert execution.id == "exec-123"
        assert execution.status == "pending"

    def test_db_execution_node_creation(self):
        """DBExecutionNode should be createable"""
        from src.db.entities import DBExecutionNode

        node = DBExecutionNode(
            id="exec-node-123",
            execution_id="exec-123",
            node_id="node_1",
            status="pending"
        )

        assert node.id == "exec-node-123"
        assert node.status == "pending"


class TestModelValidation:
    """Tests for Pydantic model validation"""

    def test_required_fields_validation(self):
        """Should validate required fields"""
        from src.db.models import NodeTemplateModel

        with pytest.raises(ValidationError):
            NodeTemplateModel(
                id="node-123"
                # Missing required fields
            )

    def test_optional_fields_default(self):
        """Optional fields should have correct defaults"""
        from src.db.models import PluginModel

        plugin = PluginModel(
            id="test",
            name="Test",
            version="1.0",
            plugin_path="path",
            input_model="Input",
            output_model="Output"
        )

        assert plugin.description is None
        assert plugin.parameters_schema is None
        assert plugin.docker_image is None
        assert plugin.is_active is True

    def test_workflow_graph_empty_nodes(self):
        """WorkflowGraph should allow empty nodes/edges"""
        from src.db.models import WorkflowGraph

        graph = WorkflowGraph(nodes=[], edges=[])
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0