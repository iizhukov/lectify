"""
Prometheus Pushgateway integration for plugin containers

Since plugins run in isolated Docker containers that are destroyed after execution,
they cannot expose metrics via HTTP endpoint. Instead, they push metrics to Pushgateway.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, push_to_gateway
import os
from typing import Optional


class PushgatewayMetrics:
    """
    Metrics that are pushed to Pushgateway from plugin containers.

    Usage:
        metrics = PushgatewayMetrics(plugin_id="text_to_md", execution_id="exec-123")
        metrics.llm_request("summarize", duration=5.2, status="success")
        metrics.push()  # Send to Pushgateway
    """

    def __init__(self, plugin_id: str, execution_id: str, pushgateway_url: Optional[str] = None):
        self.plugin_id = plugin_id
        self.execution_id = execution_id
        self.pushgateway_url = pushgateway_url or os.getenv("PUSHGATEWAY_URL", "localhost:9091")

        # Create separate registry for this container
        self.registry = CollectorRegistry()

        # LLM metrics
        self.llm_requests = Counter(
            'lectify_llm_api_requests_total',
            'LLM API requests from plugins',
            ['plugin_id', 'purpose', 'status'],
            registry=self.registry
        )

        self.llm_duration = Histogram(
            'lectify_llm_api_duration_seconds',
            'LLM API duration from plugins',
            ['plugin_id', 'purpose'],
            buckets=(1, 5, 10, 30, 60, 120, 300),
            registry=self.registry
        )

        self.llm_errors = Counter(
            'lectify_llm_api_errors_total',
            'LLM API errors from plugins',
            ['plugin_id', 'purpose', 'error_type'],
            registry=self.registry
        )

    def llm_request(self, purpose: str, duration: float, status: str = "success", error_type: Optional[str] = None):
        """Record LLM API request"""
        self.llm_requests.labels(
            plugin_id=self.plugin_id,
            purpose=purpose,
            status=status
        ).inc()

        if status == "success":
            self.llm_duration.labels(
                plugin_id=self.plugin_id,
                purpose=purpose
            ).observe(duration)

        if status == "error" and error_type:
            self.llm_errors.labels(
                plugin_id=self.plugin_id,
                purpose=purpose,
                error_type=error_type
            ).inc()

    def push(self):
        """Push metrics to Pushgateway"""
        try:
            push_to_gateway(
                self.pushgateway_url,
                job='lectify_plugins',
                registry=self.registry,
                grouping_key={
                    'plugin_id': self.plugin_id,
                    'execution_id': self.execution_id
                }
            )
        except Exception as e:
            # Don't fail plugin execution if metrics push fails
            print(f"Warning: Failed to push metrics to Pushgateway: {e}")


def get_pushgateway_metrics(plugin_id: str, execution_id: str) -> PushgatewayMetrics:
    """Get PushgatewayMetrics instance for current plugin execution"""
    return PushgatewayMetrics(plugin_id=plugin_id, execution_id=execution_id)
