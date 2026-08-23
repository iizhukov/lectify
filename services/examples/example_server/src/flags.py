from generated.config import BaseFeatureFlag, feature_flag


class ServerFeatureFlags(BaseFeatureFlag):
    """Feature flags for example_server."""

    use_new_logic = feature_flag
    extended_ping: bool = feature_flag(default=False, description="Enable extended ping formatting")

