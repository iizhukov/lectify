import subprocess
import sys
from templates import env


def test_expiry_uses_both_server_jwt_and_clocks(tmp_path):
    (tmp_path/'ticket.py').write_text(env.get_template('services/ticket_auth/interceptor.py.j2').render())
    script=r'''
import asyncio,sys,types,jwt,structlog
from unittest.mock import AsyncMock
logger=types.ModuleType('generated.logger'); logger.get_logger=structlog.get_logger
sys.modules['generated']=types.ModuleType('generated'); sys.modules['generated.logger']=logger
settings=types.ModuleType('generated.settings')
settings.get_settings=lambda:types.SimpleNamespace(service_name='source',ticket_auth=types.SimpleNamespace(ticket_ttl=300))
sys.modules['generated.settings']=settings
module=types.ModuleType('generated.ticket_auth.client'); module.TicketAuthClient=type('Client',(),{})
sys.modules['generated.ticket_auth']=types.ModuleType('generated.ticket_auth'); sys.modules['generated.ticket_auth.client']=module
import ticket
clock=types.SimpleNamespace(epoch=1000,mono=0)
ticket.time=types.SimpleNamespace(time=lambda:clock.epoch,monotonic=lambda:clock.mono)
def token(exp):return jwt.encode({'exp':exp},'a'*32,algorithm='HS256')
async def main():
    client=ticket.TicketAuthClientInterceptor('source','destination')
    issue=AsyncMock(side_effect=lambda **kwargs:token(clock.epoch+60))
    client._client.request_ticket=issue
    first=await client._get_or_create_ticket()
    assert await client._get_or_create_ticket()==first and issue.await_count==1
    # Host wall time advances across VM suspension, monotonic barely moves.
    clock.epoch+=61; clock.mono+=1
    second=await client._get_or_create_ticket()
    assert first!=second and issue.await_count==2
    # A backward wall jump cannot extend the monotonic cache lifetime.
    clock.epoch-=200; clock.mono+=51
    assert await client._get_or_create_ticket()!=second and issue.await_count==3
    # Opaque/malformed responses are never cached as long-lived authority.
    issue.side_effect=None; issue.return_value='invalid'
    client._ticket_cache.clear()
    assert await client._get_or_create_ticket()=='invalid'
    assert not client._ticket_cache
asyncio.run(main())
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
