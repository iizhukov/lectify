"""Wait for every local service's real mTLS listener, without bypassing API authorization."""
import asyncio
import os
import sys
sys.path.insert(0,'/app/services/tools/client')
from generated.transport import create_channel, TLSConfig
from backend import SERVICES


async def main():
    tls = TLSConfig.from_env('LECTIFY_GRPC_CLIENT_TLS')
    channels = {name:create_channel(os.environ[name.upper()+'_ADDRESS'],tls) for name in SERVICES}
    try:
        async with asyncio.timeout(90):
            await asyncio.gather(*(channel.channel_ready() for channel in channels.values()))
        print('All backend gRPC listeners are ready; one host agent is configured.')
    finally:
        await asyncio.gather(*(channel.close() for channel in channels.values()))

if __name__ == '__main__': asyncio.run(main())
