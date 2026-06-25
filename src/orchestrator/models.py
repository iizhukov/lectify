"""
Конфигурация оркестратора.
"""
from dataclasses import dataclass


@dataclass
class OrchestratorConfig:
    """Параметры оркестратора из config.cfg"""
    enabled: bool = True
    max_concurrent_workflows: int = 3
    poll_interval_seconds: int = 5
    node_timeout_seconds: int = 600
    auto_retry_failed_nodes: bool = True
    max_node_retries: int = 2
