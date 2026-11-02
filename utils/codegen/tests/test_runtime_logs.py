import asyncio
import sys
import types
import pytest
from templates import env


def module():
    result=types.ModuleType('runtime_logs_test')
    exec(compile(env.get_template('services/runtime_logs.py.j2').render(),'<logs>','exec'),result.__dict__)
    return result


@pytest.mark.asyncio
async def test_process_stdout_stderr_are_drained_bounded_and_redacted():
    logs=module(); captured=[]
    async def sink(level,message,fields): captured.append((level,message,fields))
    secret='fixture-runtime-secret-abcdef'
    process=await asyncio.create_subprocess_exec(sys.executable,'-c',
        "import os,sys; print('x'*2995+os.environ['RUNTIME_TOKEN']); print('compiler diagnostic',file=sys.stderr); print('z'*100000)",
        env={'RUNTIME_TOKEN':secret},stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    collector=logs.ProcessLogs(sink,{'RUNTIME_TOKEN':secret},limit=32768); collector.attach(process)
    await asyncio.wait_for(process.wait(),5); await collector.finish()
    text=''.join(message for _,message,_ in captured)
    assert secret not in text and '[REDACTED]' in text and 'compiler diagnostic' in text
    assert collector.incomplete and any(fields.get('truncated')=='true' for _,_,fields in captured)
    assert all(len(message)<=3000 for _,message,_ in captured)


def test_nested_assignment_pem_bearer_and_url_credentials_never_enter_logs():
    logs=module()
    secret='fixture-user-access-credential'
    values=logs.secret_values({'ASSIGNMENT_JSON':'{"user_access_token":"'+secret+'"}'})
    text=logs.sanitize(secret+' Bearer abcdefghi postgres://user:example-password@host/db\n-----BEGIN PRIVATE KEY-----\nsecret-lines\n-----END PRIVATE KEY-----',values)
    assert secret not in text and 'abcdefghi' not in text and 'example-password' not in text and 'secret-lines' not in text
    assert logs.sanitize_fields({'api_key':'example-value'},values)['api_key']=='[REDACTED]'
    assert secret in logs.secret_values({'user_access_token':secret,'runtime_environment':{'RUNTIME_TOKEN':secret}})
    assert secret[:12] not in logs.sanitize('prefix '+secret[:12],values,truncated=True)
    assert 'partial-private-key' not in logs.sanitize('-----BEGIN PRIVATE KEY-----\npartial-private-key',values,truncated=True)
