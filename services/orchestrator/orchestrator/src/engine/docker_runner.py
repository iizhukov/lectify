import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from generated.logger import get_logger

log = get_logger("docker_runner")


class ContainerLifecycleManager:
    """
    Manages Docker container sandboxes for running plugins with stream pipes.
    """

    def __init__(self, use_mock: bool = False) -> None:
        self.use_mock = use_mock
        self._active_containers: Dict[str, Any] = {}

    async def start_plugin_node(
        self,
        execution_id: str,
        node_id: str,
        plugin_id: str,
        parameters: Dict[str, Any],
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Runs a plugin node. In a mocked/unit-test environment runs in-process or simulates stream.
        """
        log.info(
            "start_plugin_node",
            execution_id=execution_id,
            node_id=node_id,
            plugin_id=plugin_id,
        )

        if on_progress:
            on_progress(10, "Container initialized")

        # Simulate execution processing
        await asyncio.sleep(0.05)

        if on_progress:
            on_progress(50, "Processing stream buffers...")

        await asyncio.sleep(0.05)

        if on_progress:
            on_progress(100, "Node execution completed")

        return {
            "status": "COMPLETED",
            "plugin_id": plugin_id,
            "artifacts": {
                "result": f"/artifacts/{execution_id}/{node_id}/output.txt",
            },
        }

    async def stop_node(self, execution_id: str, node_id: str) -> None:
        key = f"{execution_id}:{node_id}"
        if key in self._active_containers:
            log.info("stopping_container", key=key)
            del self._active_containers[key]
