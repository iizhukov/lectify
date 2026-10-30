from generated.config import BaseFeatureFlag, feature_flag


class OrchestratorFeatureFlags(BaseFeatureFlag):
    enable_streaming_buffers = feature_flag
    max_concurrent_nodes: int = feature_flag(default=10)
    auto_retry_failed_nodes = feature_flag(default=True)
    container_timeout_seconds: int = feature_flag(default=600)


flags = OrchestratorFeatureFlags()
