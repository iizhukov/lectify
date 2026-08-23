import asyncio
import json
import time

from generated.logger import get_logger
import generated.protos.clients.example_server.index_pb2 as index_pb2
import generated.protos.clients.infra_config.index_pb2 as config_pb2
from generated.grpc_client.grpc_clients import get_grpc_clients


log = get_logger("main")


async def run_kafka_producer() -> None:
    from generated.kafka.producer import get_producer

    producer = await get_producer(topics=["example"])
    try:
        for i in range(5):
            payload = {
                "event": "user_action",
                "user_id": i + 1,
                "action": f"test_action_{i}",
                "timestamp": time.time(),
            }
            ok = await producer.send(
                topic="example",
                value=json.dumps(payload),
                key=str(i).encode(),
            )
            log.info(
                "kafka_sent",
                topic="example",
                key=str(i),
                action=payload["event"],
                success=ok,
            )
            await asyncio.sleep(1)
    finally:
        await producer.stop()


async def run_grpc_calls() -> None:
    clients = get_grpc_clients()
    server_stub = clients.exampleserver
    config_stub = clients.infraconfig

    target_svc = "example_server"

    # =========================================================================
    # 1. Запрос на получение СТАРОГО значения Feature Flag через gRPC
    # =========================================================================
    log.info("--- 1. Получение старого значения Feature Flag (gRPC GetFeatureFlags) ---")
    resp_old = await config_stub.GetFeatureFlags(
        config_pb2.GetFeatureFlagsRequest(service_name=target_svc)
    )
    old_flag_val = resp_old.flags.get("use_new_logic", False)
    log.info("old_feature_flag_value", service=target_svc, flag="use_new_logic", value=old_flag_val)

    # Вызов Ping до изменения флага (сервер вернет стандартный ответ)
    ping_resp1 = await server_stub.Ping(index_pb2.PingRequest(message="first call (before flag change)"))
    log.info("ping_response_before", reply=ping_resp1.message, ts=ping_resp1.timestamp)

    # =========================================================================
    # 2. Запрос на ИЗМЕНЕНИЕ Feature Flag через gRPC (gRPC SetFeatureFlag)
    # =========================================================================
    log.info("--- 2. Изменение значения Feature Flag на True (gRPC SetFeatureFlag) ---")
    new_target_value = not old_flag_val
    set_resp = await config_stub.SetFeatureFlag(
        config_pb2.SetFeatureFlagRequest(
            service_name=target_svc,
            flag_name="use_new_logic",
            enabled=new_target_value,
        )
    )
    log.info("feature_flag_update_result", flag="use_new_logic", new_value=new_target_value, success=set_resp.success)

    # =========================================================================
    # 3. Запрос на получение НОВОГО значения Feature Flag через gRPC
    # =========================================================================
    log.info("--- 3. Получение нового значения Feature Flag (gRPC GetFeatureFlags) ---")
    resp_new = await config_stub.GetFeatureFlags(
        config_pb2.GetFeatureFlagsRequest(service_name=target_svc)
    )
    new_flag_val = resp_new.flags.get("use_new_logic", False)
    log.info("new_feature_flag_value", service=target_svc, flag="use_new_logic", value=new_flag_val)

    # Вызов Ping после изменения флага (сервер вернет ответ с учетом флага)
    ping_resp2 = await server_stub.Ping(index_pb2.PingRequest(message="second call (after flag change)"))
    log.info("ping_response_after", reply=ping_resp2.message, ts=ping_resp2.timestamp)

    # =========================================================================
    # 4. Базовые CRUD-вызовы (CreateUser, GetUser)
    # =========================================================================
    ts = int(time.time())
    user = await server_stub.CreateUser(
        index_pb2.CreateUserRequest(
            username=f"test_user_{ts}",
            email=f"test_{ts}@example.com",
            full_name="Test User",
        )
    )
    log.info("user_created", id=user.id, username=user.username, email=user.email)

    fetched = await server_stub.GetUser(index_pb2.GetUserRequest(id=user.id))
    log.info("user_fetched", id=fetched.id, username=fetched.username, email=fetched.email)

    try:
        await server_stub.GetUser(index_pb2.GetUserRequest(id=99999))
    except Exception as e:
        log.info("get_user_404_expected", error=str(e))

    await clients.close_all()


async def main() -> None:
    log.info("example_client_started")

    # await run_kafka_producer()
    await run_grpc_calls()

    log.info("example_client_done")
