from opentelemetry import metrics


meter = metrics.get_meter("business")

USERS_CREATED = meter.create_counter(
    "users.created",
    description="Total users created",
)

USER_CREATION_DURATION = meter.create_histogram(
    "user.creation.duration",
    description="User creation time",
    unit="s",
)
