"""One-computer backend deployment with one host agent. No project secrets are copied."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/backend'
PROJECT = 'lectify-mvp'
NETWORK = 'lectify-mvp-local'
SERVICES = {
    'infra_tas':'services/infra/tas', 'infra_config':'services/infra/config',
    'api_auth':'services/api/auth', 'api_file':'services/api/file',
    'api_prompt':'services/api/prompt', 'api_workflow':'services/api/workflow',
    'api_execution':'services/api/execution', 'orchestrator':'services/orchestrator/orchestrator',
    'orchestrator_worker':'services/orchestrator/worker',
    'plugins_provider':'services/plugins/provider',
}
PLUGINS = {'text_input':'io/text_input','file_input':'io/file_input',
           'text_to_md':'format/text_to_md','text_output':'io/text_output','file_output':'io/file_output',
           'prompt_selector':'io/prompt_selector','llm_request':'ai/llm_request','media_converter':'media/media_converter',
           'input':'io/input','text_to_md_llm':'ai/text_to_md','text_to_latex':'ai/text_to_latex',
           'latex_to_pdf':'format/latex_to_pdf','speech_to_text_v1':'media/speech_to_text_v1',
           'media_converter_v1_1':'media/media_converter_v1_1',
           'speech_to_text_v1_1':'media/speech_to_text_v1_1'}

def run(*args, **kwargs):
    return subprocess.run(args,check=True,**kwargs)

def compose(*args):
    return run('docker','compose','-p',PROJECT,'-f',str(LOCAL/'compose.yaml'),*args)

def private_file(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as stream: stream.write(data)

def certificates():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    directory = LOCAL/'config/tls'
    if (directory/'service.key').exists(): return
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Local backend CA')])
    ca = (x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
        .sign(ca_key,hashes.SHA256()))
    private_file(directory/'ca.pem',ca.public_bytes(serialization.Encoding.PEM).decode())
    for role in ('service','agent','runtime'):
        key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,role)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
            .not_valid_after(now+timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name) for name in
                [*SERVICES,'localhost','*.plugins.internal']]),False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH,ExtendedKeyUsageOID.SERVER_AUTH]),False)
            .sign(ca_key,hashes.SHA256()))
        private_file(directory/(role+'.pem'),cert.public_bytes(serialization.Encoding.PEM).decode())
        private_file(directory/(role+'.key'),key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())

def copy_sources():
    stage = LOCAL/'build/project'
    # Only explicit runtime source areas; never copy the checkout wholesale.
    for name, relative in {**SERVICES,'agent':'services/orchestrator/agent','client':'services/tools/client'}.items():
        source, destination = ROOT/relative, stage/relative
        for part in ('src','generated','migrations'):
            if (source/part).exists():
                shutil.copytree(source/part,destination/part,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','vault','*.log'))
        shutil.copy(source/'service.yaml',destination/'service.yaml')
        if (source/'requirements.txt').exists():
            shutil.copy(source/'requirements.txt',destination/'requirements.txt')
    for relative in PLUGINS.values():
        source, destination = ROOT/'plugins'/relative, stage/'plugins'/relative
        for part in ('src','generated'):
            shutil.copytree(source/part,destination/part,dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy(source/'plugin.yaml',destination/'plugin.yaml')
        if (source/'requirements.txt').exists():
            shutil.copy(source/'requirements.txt',destination/'requirements.txt')
    for relative in ('proto','utils/codegen/src','infra/local'):
        shutil.copytree(ROOT/relative,stage/relative,dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy(ROOT/'infra/local/Dockerfile',LOCAL/'build/Dockerfile')
    requirements = set(['psycopg2-binary>=2.9','PyYAML>=6'])
    for relative in [*SERVICES.values(),'services/orchestrator/agent',*['plugins/'+path for path in PLUGINS.values()]]:
        for path in (ROOT/relative/'generated/requirements.txt',ROOT/relative/'requirements.txt'):
            if path.exists():
                requirements.update(line for line in path.read_text().splitlines()
                                    if line and not line.startswith(('#','-r ')))
    (LOCAL/'build/requirements.txt').write_text('\n'.join(sorted(requirements))+'\n')

def prepare(test_provider=False):
    LOCAL.mkdir(parents=True,exist_ok=True)
    LOCAL.chmod(0o700)
    private_file(LOCAL/'config/mode.json',json.dumps({'offline_test_provider':test_provider}))
    run(sys.executable,str(ROOT/'utils/codegen/src/cli.py'),'project',cwd=ROOT,
        env=dict(os.environ,CODEGEN_ROOT=str(ROOT)))
    certificates()
    secret_path = LOCAL/'config/secrets.json'
    if not secret_path.exists():
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        private_file(secret_path,json.dumps({'database':secrets.token_urlsafe(24),'s3':secrets.token_urlsafe(24),
            'execution':Fernet.generate_key().decode(),'admin':secrets.token_urlsafe(24),
            'tas':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()).decode()}))
    credentials = json.loads(secret_path.read_text())
    copy_sources()
    init = LOCAL/'config/init.sql'
    init.write_text('\n'.join('CREATE DATABASE "'+name+'";' for name,relative in SERVICES.items()
        if (ROOT/relative/'migrations/versions').exists()))
    services = {
        'postgres':{'image':'postgres:16-alpine','environment':{'POSTGRES_PASSWORD':credentials['database']},
            'volumes':['pg:/var/lib/postgresql/data',str(init)+':/docker-entrypoint-initdb.d/init.sql:ro'],
            'healthcheck':{'test':['CMD-SHELL','pg_isready -U postgres'],'interval':'2s','timeout':'3s','retries':30}},
        'minio':{'image':'minio/minio:latest','command':['server','/data'],
            'environment':{'MINIO_ROOT_USER':'local-backend','MINIO_ROOT_PASSWORD':credentials['s3']},
            'volumes':['s3:/data']},
        'collector':{'image':'otel/opentelemetry-collector-contrib:0.106.0',
            'command':['--config=/etc/local.yaml'],'volumes':[str(LOCAL/'config/collector.yaml')+':/etc/local.yaml:ro']},
        'prometheus':{'image':'prom/prometheus:v2.52.0','ports':['127.0.0.1:19090:9090'],
            'volumes':[str(LOCAL/'config/prometheus.yaml')+':/etc/prometheus/prometheus.yml:ro']},
        'loki':{'image':'grafana/loki:3.0.0','command':['-config.file=/etc/local.yaml'],
            'volumes':[str(LOCAL/'config/loki.yaml')+':/etc/local.yaml:ro','loki:/loki']},
    }
    (LOCAL/'config/loki.yaml').write_text(yaml.safe_dump({'auth_enabled':False,
        'server':{'http_listen_port':3100},'common':{'path_prefix':'/loki','replication_factor':1,
            'ring':{'kvstore':{'store':'inmemory'}},
            'storage':{'filesystem':{'chunks_directory':'/loki/chunks','rules_directory':'/loki/rules'}}},
        'schema_config':{'configs':[{'from':'2024-01-01','store':'tsdb','object_store':'filesystem',
            'schema':'v13','index':{'prefix':'index_','period':'24h'}}]},
        'limits_config':{'allow_structured_metadata':False}}))
    collector = {'receivers':{'otlp':{'protocols':{'grpc':{'endpoint':'0.0.0.0:4317'}}}},
        'exporters':{'prometheus':{'endpoint':'0.0.0.0:8889','resource_to_telemetry_conversion':{'enabled':True}},
                     'debug':{'verbosity':'basic'}},
        'service':{'pipelines':{'metrics':{'receivers':['otlp'],'exporters':['prometheus']},
                                'traces':{'receivers':['otlp'],'exporters':['debug']}}}}
    (LOCAL/'config/collector.yaml').write_text(yaml.safe_dump(collector))
    (LOCAL/'config/prometheus.yaml').write_text(yaml.safe_dump({'global':{'scrape_interval':'2s'},
        'scrape_configs':[{'job_name':'backend','static_configs':[{'targets':['collector:8889']}]}]}))
    ports = {}
    packages=sorted({package for relative in PLUGINS.values() for package in
        yaml.safe_load((ROOT/'plugins'/relative/'plugin.yaml').read_text())['plugin'].get('system_packages',[])})
    for name,relative in SERVICES.items():
        manifest = yaml.safe_load((ROOT/relative/'service.yaml').read_text())['service']
        ports[name] = manifest['grpc']['port']
    for name,relative in SERVICES.items():
        env = {name.upper()+'_DB_URL':f"postgresql+asyncpg://postgres:{credentials['database']}@postgres:5432/{name}",
            'LOCAL_DB_URL':f"postgresql+asyncpg://postgres:{credentials['database']}@postgres:5432/{name}",
            'LOCAL_SERVICE':name,'LECTIFY_GRPC_LISTEN_ADDRESS':'0.0.0.0:'+str(ports[name]),
            'LOKI_URL':'http://loki:3100',
            'LECTIFY_TAS_ADDRESS':'infra_tas:'+str(ports['infra_tas']),
            'LECTIFY_CONFIG_ADDRESS':'infra_config:'+str(ports['infra_config']),
            name.upper()+'_OBS_OTLP_ENDPOINT':'http://collector:4317',
            'LECTIFY_EXECUTION_CREDENTIAL_KEY':credentials['execution']}
        env.update({target.upper()+'_ADDRESS':target+':'+str(port) for target,port in ports.items()})
        for prefix in ('LECTIFY_GRPC_SERVER_TLS','LECTIFY_GRPC_CLIENT_TLS'):
            env.update({prefix+'_CERT_FILE':'/run/config/tls/service.pem',prefix+'_KEY_FILE':'/run/config/tls/service.key',
                        prefix+'_CA_FILE':'/run/config/tls/ca.pem'})
        if name == 'infra_tas': env['INFRA_TAS_JWT_PRIVATE_KEY'] = credentials['tas']
        if name == 'api_file': env.update(API_FILE_MINIO_ENDPOINT='minio:9000',
            API_FILE_MINIO_ACCESS_KEY='local-backend',API_FILE_MINIO_SECRET_KEY=credentials['s3'])
        if name == 'orchestrator': env['LECTIFY_DEPLOYMENT_FILE'] = '/run/config/deployment.json'
        if name == 'api_auth': env['LOCAL_ADMIN_PASSWORD'] = credentials['admin']
        if name=='plugins_provider' and test_provider:
            env.update(LOCAL_TEST_PROVIDER='1',LECTIFY_ALLOW_TEST_PROVIDER='1',
                LECTIFY_PROVIDER_TEST_ENDPOINT='http://127.0.0.1:18080',
                PLUGINS_PROVIDER_HTTP_BEARER_TOKEN='local-offline-fixture')
        services[name] = {'image':PROJECT+'-backend:local',
            'build':{'context':str(LOCAL/'build'),'args':{'PLUGIN_SYSTEM_PACKAGES':' '.join(packages)}},'command':[relative],
            'environment':env,'volumes':[str(LOCAL/'config')+':/run/config:ro'],
            'depends_on':{'postgres':{'condition':'service_healthy'},'minio':{'condition':'service_started'}},
            'stop_grace_period':'20s'}
        if name == 'orchestrator_worker':
            env.update(CODEGEN_SANDBOX_MEMORY_MIB='1024',CODEGEN_SANDBOX_TMPFS_MIB='384')
            services[name]['volumes'].append('/var/run/docker.sock:/var/run/docker.sock')
        published = {'api_auth':19021,'api_workflow':19024,'api_execution':19025,'api_file':19026,'orchestrator':19040}
        if name in published: services[name]['ports'] = [f'127.0.0.1:{published[name]}:{ports[name]}']
    for service in services.values(): service['networks'] = ['backend']
    private_file(LOCAL/'compose.yaml',yaml.safe_dump({'services':services,'volumes':{'pg':{},'s3':{},'loki':{}},
        'networks':{'backend':{'name':NETWORK}}}))
    print('Local configuration prepared; credentials stay in .local/backend/config.')

def build():
    compose('build','api_auth')
    bindings = []
    image = run('docker','image','inspect',PROJECT+'-backend:local','--format','{{.Id}}',capture_output=True,text=True).stdout.strip()
    for name,relative in PLUGINS.items():
        plugin=yaml.safe_load((LOCAL/'build/project/plugins'/relative/'plugin.yaml').read_text())['plugin']
        bindings.append({'id':plugin['name'],'version':plugin['version'],'image':image,
            'cwd':'/app/plugins/'+relative,
            'manifest_file':'/app/plugins/'+relative+'/generated/plugin_manifest.json',
            'runtime_timeout':3600 if plugin['name']=='speech_to_text' else 300})
    daemon = run('docker','info','--format','{{.ID}}',capture_output=True,text=True).stdout.strip()
    config = {'workers':{daemon:{'endpoint':'orchestrator_worker:10042','network':NETWORK,
        'agent_endpoint':'{name}.plugins.internal:50055','runtime_endpoint':'{name}.plugins.internal:50056',
        'network_aliases':['{name}.plugins.internal'],'sidecar':'{name}.plugins.internal:50055'}},
        'plugins':bindings,'backends':{'auth':'api_auth:10021','file':'api_file:10024','prompt':'api_prompt:10023',
            'provider':'plugins_provider:10032','orchestrator':'orchestrator:10040','tas':'infra_tas:10010'},'tls':{}}
    for role,key in {'agent_server':'agent','runtime_server':'runtime','control_client':'service',
                      'runtime_client':'service','sidecar_client':'runtime','backend_client':'service'}.items():
        config['tls'][role] = {'certificate':'/run/config/tls/'+key+'.pem','private_key':'/run/config/tls/'+key+'.key',
                               'roots':'/run/config/tls/ca.pem'}
    private_file(LOCAL/'config/deployment.json',json.dumps(config))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['up','down','status','logs','prepare','smoke','scenarios','seed','recovery','migration-race','replicas','execution-details'])
    parser.add_argument('--test-provider',action='store_true',help='Use an explicit offline loopback provider fixture')
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.test_provider)
    elif args.command == 'up':
        prepare(args.test_provider); build(); compose('up','-d','--no-build')
        compose('exec','-T','api_execution','python','/app/infra/local/ready.py')
    elif args.command == 'down': compose('down')
    elif args.command == 'status': compose('ps')
    elif args.command == 'logs': compose('logs','--tail','40')
    elif args.command == 'smoke':
        compose('exec','-T','api_execution','python','/app/infra/local/smoke.py')
    elif args.command == 'scenarios':
        with (ROOT/'infra/local/scenarios.py').open() as scenario:
            run('docker','compose','-p','lectify-mvp','-f',str(LOCAL/'compose.yaml'),
                'exec','-T','-w','/app/infra/local','api_execution','python','-',stdin=scenario)
    elif args.command == 'seed':
        compose('exec','-T','api_execution','python','/app/infra/local/seed.py')
    elif args.command == 'recovery':
        from recovery import main as recovery
        recovery()
    elif args.command == 'migration-race':
        compose('exec','-T','orchestrator','python','/app/infra/local/migration_race.py')
    elif args.command == 'replicas':
        from replicas import main as replicas
        replicas()
    elif args.command == 'execution-details':
        with (ROOT/'infra/local/execution_details_probe.py').open() as probe:
            run('docker','compose','-p',PROJECT,'-f',str(LOCAL/'compose.yaml'),'exec','-T',
                '-w','/app/infra/local','api_execution','python','-',stdin=probe)

if __name__ == '__main__': main()
