"""New workflow architecture

Revision ID: 002
Revises: 001
Create Date: 2024-06-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =============================================
    # USERS
    # =============================================
    op.create_table(
        'users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=False, unique=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)

    # =============================================
    # PLUGINS
    # =============================================
    op.create_table(
        'plugins',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('plugin_path', sa.String(), nullable=False),
        sa.Column('input_model', sa.String(), nullable=False),
        sa.Column('output_model', sa.String(), nullable=False),
        sa.Column('parameters_schema', sa.JSON(), nullable=True),
        sa.Column('docker_image', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_plugins_id'), 'plugins', ['id'], unique=True)
    op.create_index(op.f('ix_plugins_name'), 'plugins', ['name'], unique=True)

    # =============================================
    # NODE TEMPLATES (DSL definitions)
    # =============================================
    op.create_table(
        'node_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('plugin_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('input_mapping', sa.JSON(), nullable=True),
        sa.Column('prompt_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['plugin_id'], ['plugins.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_node_templates_id'), 'node_templates', ['id'], unique=True)
    op.create_index(op.f('ix_node_templates_user_id'), 'node_templates', ['user_id'], unique=False)

    # =============================================
    # WORKFLOW TEMPLATES
    # =============================================
    op.create_table(
        'workflow_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('graph', sa.JSON(), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_templates_id'), 'workflow_templates', ['id'], unique=True)
    op.create_index(op.f('ix_workflow_templates_user_id'), 'workflow_templates', ['user_id'], unique=False)

    # =============================================
    # PUBLIC WORKFLOWS (copy of published workflows)
    # =============================================
    op.create_table(
        'workflows_public',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('original_workflow_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('graph', sa.JSON(), nullable=False),
        sa.Column('author_id', sa.String(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflows_public_id'), 'workflows_public', ['id'], unique=True)
    op.create_index(op.f('ix_workflows_public_author_id'), 'workflows_public', ['author_id'], unique=False)

    # =============================================
    # PROMPTS LIBRARY
    # =============================================
    op.create_table(
        'prompts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('user_prompt_template', sa.Text(), nullable=True),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('minio_path', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prompts_id'), 'prompts', ['id'], unique=True)
    op.create_index(op.f('ix_prompts_user_id'), 'prompts', ['user_id'], unique=False)

    # =============================================
    # EXECUTIONS (workflow execution history)
    # =============================================
    op.create_table(
        'executions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workflow_template_id', sa.String(), nullable=True),
        sa.Column('file_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_template_id'], ['workflow_templates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['file_id'], ['files.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_executions_id'), 'executions', ['id'], unique=True)
    op.create_index(op.f('ix_executions_file_id'), 'executions', ['file_id'], unique=False)
    op.create_index(op.f('ix_executions_user_id'), 'executions', ['user_id'], unique=False)
    op.create_index(op.f('ix_executions_status'), 'executions', ['status'], unique=False)

    # =============================================
    # EXECUTION NODES (per-node execution metrics)
    # =============================================
    op.create_table(
        'execution_nodes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('execution_id', sa.String(), nullable=False),
        sa.Column('node_template_id', sa.String(), nullable=False),
        sa.Column('node_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('progress_percent', sa.Integer(), nullable=True),
        sa.Column('progress_message', sa.Text(), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('output_data', sa.JSON(), nullable=True),
        sa.Column('container_id', sa.String(), nullable=True),
        sa.Column('cpu_percent', sa.Float(), nullable=True),
        sa.Column('memory_mb', sa.Float(), nullable=True),
        sa.Column('execution_time_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('logs_path', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['node_template_id'], ['node_templates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_execution_nodes_id'), 'execution_nodes', ['id'], unique=True)
    op.create_index(op.f('ix_execution_nodes_execution_id'), 'execution_nodes', ['execution_id'], unique=False)
    op.create_index(op.f('ix_execution_nodes_node_id'), 'execution_nodes', ['node_id'], unique=False)
    op.create_index(op.f('ix_execution_nodes_status'), 'execution_nodes', ['status'], unique=False)

    # =============================================
    # ADD user_id TO files (for multi-user support)
    # =============================================
    op.add_column('files', sa.Column('user_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_files_user_id'), 'files', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_files_user_id',
        'files', 'users',
        ['user_id'], ['id'],
        ondelete='SET NULL'
    )

    # =============================================
    # ADD new fields TO workflows (for template support)
    # =============================================
    op.add_column('workflows', sa.Column('workflow_template_id', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('execution_id', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('workflows', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('workflows', sa.Column('ended_at', sa.DateTime(), nullable=True))
    op.add_column('workflows', sa.Column('final_artifact_id', sa.String(), nullable=True))

    # =============================================
    # ADD file_id TO workflows_nodes (keep for backwards compat)
    # =============================================
    op.add_column('workflow_nodes', sa.Column('file_id', sa.String(), nullable=True))
    op.add_column('workflow_nodes', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('workflow_nodes', sa.Column('execution_node_id', sa.String(), nullable=True))
    op.add_column('workflow_nodes', sa.Column('progress_percent', sa.Integer(), nullable=True))
    op.add_column('workflow_nodes', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('workflow_nodes', sa.Column('ended_at', sa.DateTime(), nullable=True))

    # =============================================
    # ARTIFACTS - add user_id and execution info
    # =============================================
    op.add_column('artifacts', sa.Column('user_id', sa.String(), nullable=True))
    op.add_column('artifacts', sa.Column('execution_node_id', sa.String(), nullable=True))


def downgrade() -> None:
    # Artifacts
    op.drop_column('artifacts', 'execution_node_id')
    op.drop_column('artifacts', 'user_id')

    # workflow_nodes
    op.drop_column('workflow_nodes', 'progress_percent')
    op.drop_column('workflow_nodes', 'execution_node_id')
    op.drop_column('workflow_nodes', 'user_id')
    op.drop_column('workflow_nodes', 'file_id')
    op.drop_column('workflow_nodes', 'ended_at')
    op.drop_column('workflow_nodes', 'started_at')

    # workflows
    op.drop_column('workflows', 'user_id')
    op.drop_column('workflows', 'execution_id')
    op.drop_column('workflows', 'workflow_template_id')
    op.drop_column('workflows', 'ended_at')
    op.drop_column('workflows', 'started_at')
    op.drop_column('workflows', 'final_artifact_id')

    # files
    op.drop_constraint('fk_files_user_id', 'files', type_='foreignkey')
    op.drop_index(op.f('ix_files_user_id'), table_name='files')
    op.drop_column('files', 'user_id')

    # execution_nodes
    op.drop_index(op.f('ix_execution_nodes_status'), table_name='execution_nodes')
    op.drop_index(op.f('ix_execution_nodes_node_id'), table_name='execution_nodes')
    op.drop_index(op.f('ix_execution_nodes_execution_id'), table_name='execution_nodes')
    op.drop_index(op.f('ix_execution_nodes_id'), table_name='execution_nodes')
    op.drop_table('execution_nodes')

    # executions
    op.drop_index(op.f('ix_executions_status'), table_name='executions')
    op.drop_index(op.f('ix_executions_user_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_file_id'), table_name='executions')
    op.drop_index(op.f('ix_executions_id'), table_name='executions')
    op.drop_table('executions')

    # prompts
    op.drop_index(op.f('ix_prompts_user_id'), table_name='prompts')
    op.drop_index(op.f('ix_prompts_id'), table_name='prompts')
    op.drop_table('prompts')

    # workflows_public
    op.drop_index(op.f('ix_workflows_public_author_id'), table_name='workflows_public')
    op.drop_index(op.f('ix_workflows_public_id'), table_name='workflows_public')
    op.drop_table('workflows_public')

    # workflow_templates
    op.drop_index(op.f('ix_workflow_templates_user_id'), table_name='workflow_templates')
    op.drop_index(op.f('ix_workflow_templates_id'), table_name='workflow_templates')
    op.drop_table('workflow_templates')

    # node_templates
    op.drop_index(op.f('ix_node_templates_user_id'), table_name='node_templates')
    op.drop_index(op.f('ix_node_templates_id'), table_name='node_templates')
    op.drop_table('node_templates')

    # plugins
    op.drop_index(op.f('ix_plugins_name'), table_name='plugins')
    op.drop_index(op.f('ix_plugins_id'), table_name='plugins')
    op.drop_table('plugins')

    # users
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')