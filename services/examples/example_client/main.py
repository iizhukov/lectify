import asyncio
import json
import time

from generated.logger import get_logger
import generated.protos.clients.example_server.index_pb2 as index_pb2


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
    from generated.grpc_client.grpc_clients import get_grpc_clients

    clients = get_grpc_clients()
    stub = clients.exampleserver

    # 1. Ping / Pong
    ping_resp = await stub.Ping(index_pb2.PingRequest(message="hello from client"))
    log.info("ping_ok", reply=ping_resp.message, ts=ping_resp.timestamp)

    # 2. CreateUser
    ts = int(time.time())
    user = await stub.CreateUser(
        index_pb2.CreateUserRequest(
            username=f"test_user_{ts}",
            email=f"test_{ts}@example.com",
            full_name="Test User",
        )
    )
    log.info("user_created", id=user.id, username=user.username, email=user.email)

    # 3. GetUser
    fetched = await stub.GetUser(index_pb2.GetUserRequest(id=user.id))
    log.info("user_fetched", id=fetched.id, username=fetched.username, email=fetched.email)

    # 4. GetUser — not found
    try:
        await stub.GetUser(index_pb2.GetUserRequest(id=99999))
    except Exception as e:
        log.info("get_user_404_expected", error=str(e))

    await clients.close_all()


async def main() -> None:
    log.info("example_client_started")

    await run_kafka_producer()
    await run_grpc_calls()

    log.info("example_client_done")
