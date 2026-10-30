"""Two isolated containers test generated mTLS transport through Docker DNS."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'services/orchestrator/orchestrator'))
from generated.docker_sandbox import DockerSandbox

PROBE = '''import asyncio, os
import grpc
from generated.transport import TLSConfig, create_channel, bind_server

async def main():
    role = os.environ['ROLE']
    tls = TLSConfig.from_files('certs/'+role+'.crt','certs/'+role+'.key','certs/ca.crt')
    if role == 'server':
        async def ping(request, context): return b'pong'
        server = grpc.aio.server()
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('tls.Test',{
            'Ping':grpc.unary_unary_rpc_method_handler(ping)}),))
        bind_server(server,'0.0.0.0:5000',tls)
        await server.start()
        await server.wait_for_termination()
    else:
        channel = create_channel('api_auth:5000',tls)
        try:
            await asyncio.wait_for(channel.channel_ready(),10)
            assert await channel.unary_unary('/tls.Test/Ping')(b'ping',timeout=5) == b'pong'
        finally: await channel.close()
        wrong = create_channel('wrong_auth:5000',tls)
        try:
            try: await wrong.unary_unary('/tls.Test/Ping')(b'ping',timeout=1)
            except grpc.aio.AioRpcError: pass
            else: raise AssertionError('Wrong Docker DNS hostname accepted')
        finally: await wrong.close()
        print('Docker DNS mTLS: api_auth accepted, wrong_auth rejected.')
asyncio.run(main())
'''


def docker(*args):
    return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.STDOUT).strip()


async def probe(image, network):
    sandbox = DockerSandbox()
    async with sandbox.allocated(execution_id=uuid.uuid4().hex,node_id='server',fence=1,
            attempt_id=uuid.uuid4().hex,image=image,environment={'ROLE':'server'},network=network,
            network_aliases=['api_auth','wrong_auth']) as server:
        await sandbox.start(server)
        async with sandbox.allocated(execution_id=uuid.uuid4().hex,node_id='client',fence=1,
                attempt_id=uuid.uuid4().hex,image=image,environment={'ROLE':'client'},network=network) as client:
            output = await asyncio.to_thread(docker,'start','--attach',client)
            assert docker('inspect','--format','{{.State.ExitCode}}',client) == '0'
            print(output)


def main():
    image, network = None, None
    with tempfile.TemporaryDirectory(prefix='lectify-docker-tls-') as directory:
        root = Path(directory)
        certs, context = root/'authority', root/'build'
        certs.mkdir()
        (context/'certs').mkdir(parents=True)
        def openssl(*args):
            subprocess.run(['openssl',*args],cwd=certs,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        openssl('req','-x509','-nodes','-newkey','rsa:2048','-keyout','ca.key','-out','ca.crt',
            '-days','1','-subj','/CN=Ephemeral Integration CA')
        for name in ('server','client'):
            openssl('req','-nodes','-newkey','rsa:2048','-keyout',name+'.key','-out',name+'.csr','-subj','/CN='+name)
            (certs/'extensions.cnf').write_text('subjectAltName=DNS:api_auth\nextendedKeyUsage='+
                ('serverAuth' if name=='server' else 'clientAuth')+'\n')
            openssl('x509','-req','-in',name+'.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial',
                '-out',name+'.crt','-days','1','-extfile','extensions.cnf')
            for suffix in ('.crt','.key'):
                shutil.copyfile(certs/(name+suffix),context/'certs'/(name+suffix))
        shutil.copyfile(certs/'ca.crt',context/'certs/ca.crt')
        generated = context/'generated'
        generated.mkdir()
        (generated/'__init__.py').touch()
        shutil.copyfile(ROOT/'services/api/execution/generated/transport.py',generated/'transport.py')
        shutil.copyfile(ROOT/'plugins/format/text_to_md/generated/requirements.txt',context/'requirements.txt')
        (context/'probe.py').write_text(PROBE)
        (context/'Dockerfile').write_text('''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --disable-pip-version-check --timeout 15 --retries 1 --no-cache-dir -r /tmp/requirements.txt
COPY --chown=1000:1000 . /app
ENV PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
ENTRYPOINT ["python", "probe.py"]
'''+'LABEL lectify.integration-build="'+uuid.uuid4().hex+'"\n')
        try:
            subprocess.run(['docker','build','--pull=false','--progress=plain','--iidfile',str(root/'image.id'),
                str(context)],check=True,timeout=600)
            image = (root/'image.id').read_text().strip()
            network = 'lectify-tls-'+uuid.uuid4().hex[:12]
            docker('network','create','--internal',network)
            asyncio.run(probe(image,network))
        finally:
            if network:
                docker('network','rm',network)
            if image:
                docker('image','rm',image)


if __name__ == '__main__':
    main()
