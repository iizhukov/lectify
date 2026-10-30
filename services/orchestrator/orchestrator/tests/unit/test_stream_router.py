import asyncio
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('local_stream_router', Path(__file__).parents[2] / 'src/engine/stream_router.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Channel = module.StreamChannel
Chunk = module.StreamChunkData
Router = module.StreamRouter
Aborted = module.StreamAbortedError
Closed = module.StreamClosedError


@pytest.mark.parametrize('capacity', [0, -1, True, 1.5])
def test_positive_bounded_capacity_required(capacity):
    with pytest.raises(ValueError):
        Channel('channel', capacity)


def test_channel_keys_do_not_collide():
    router = Router('execution')
    first = router.get_or_create_channel('a:b', 'c')
    second = router.get_or_create_channel('a', 'b:c')
    assert first is not second
    assert first is router.get_or_create_channel('a:b', 'c')


@pytest.mark.asyncio
async def test_concurrent_publishers_fan_out_same_order_and_eof():
    channel = Channel('fanout', 1)
    first, second = channel.subscribe(), channel.subscribe()

    async def consume(queue):
        received = []
        while True:
            chunk = await queue.get()
            received.append(chunk.payload)
            if chunk.is_last:
                return received

    consumers = [asyncio.create_task(consume(queue)) for queue in (first, second)]
    await asyncio.wait_for(asyncio.gather(*[
        channel.publish(Chunk('out', str(index).encode())) for index in range(20)
    ]), 2)
    await channel.publish(Chunk('out', b'end', is_last=True))
    received = await asyncio.wait_for(asyncio.gather(*consumers), 2)
    assert received[0] == received[1] == [str(index).encode() for index in range(20)] + [b'end']
    with pytest.raises(Closed):
        await channel.publish(Chunk('out', b'late'))
    with pytest.raises(Closed):
        channel.subscribe()


@pytest.mark.asyncio
async def test_abort_releases_full_queue_blocked_publisher_and_waiting_readers():
    router = Router('execution')
    channel = router.get_or_create_channel('node', 'out')
    channel.max_buffer_chunks = 1
    queue = channel.subscribe()
    await channel.publish(Chunk('out', b'first'))
    blocked = asyncio.create_task(channel.publish(Chunk('out', b'blocked')))
    await asyncio.sleep(0)
    assert not blocked.done()
    await asyncio.wait_for(router.close_all('cancelled'), 0.5)
    with pytest.raises(Aborted, match='cancelled'):
        await asyncio.wait_for(blocked, 0.5)
    with pytest.raises(Aborted, match='cancelled'):
        await queue.get()
    with pytest.raises(Closed):
        router.get_or_create_channel('new', 'out')

    idle = Channel('idle')
    subscription = idle.subscribe()
    reads = [asyncio.create_task(subscription.get()) for _ in range(3)]
    await asyncio.sleep(0)
    await idle.abort('failed')
    results = await asyncio.wait_for(asyncio.gather(*reads, return_exceptions=True), 0.5)
    assert all(isinstance(result, Aborted) for result in results)


@pytest.mark.asyncio
async def test_unsubscribe_releases_backpressure_and_other_subscriber_continues():
    channel = Channel('channel', 1)
    abandoned, live = channel.subscribe(), channel.subscribe()
    await channel.publish(Chunk('out', b'first'))
    assert (await live.get()).payload == b'first'
    publishing = asyncio.create_task(channel.publish(Chunk('out', b'second')))
    await asyncio.sleep(0)
    assert not publishing.done()
    channel.unsubscribe(abandoned)
    await asyncio.wait_for(publishing, 0.5)
    assert (await live.get()).payload == b'second'
    with pytest.raises(Aborted):
        await abandoned.get()
    await channel.close()
    assert (await live.get()).is_last


@pytest.mark.asyncio
async def test_cancelled_partial_fanout_aborts_every_subscriber():
    channel = Channel('channel', 1)
    first, second = channel.subscribe(), channel.subscribe()
    await channel.publish(Chunk('out', b'first'))
    await first.get()
    publishing = asyncio.create_task(channel.publish(Chunk('out', b'partial')))
    await asyncio.sleep(0.01)
    publishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await publishing
    for queue in (first, second):
        with pytest.raises(Aborted):
            await queue.get()
