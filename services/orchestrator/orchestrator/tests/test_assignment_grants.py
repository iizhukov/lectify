from contextlib import asynccontextmanager
from copy import deepcopy
import json
import time
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from src.engine.dispatch import claim
from src.engine.launch import prepare_launch
from src.engine.grants import assignment_policy,assignment_grants,_same_data
from src.models import WorkflowExecutionModel,WorkflowDispatchModel,WorkflowNodeExecutionModel,PluginRegistryModel


@pytest_asyncio.fixture
async def assignment(test_session):
    node = {'id':'node','plugin_id':'plugin','plugin_version':'0.1.0',
        'parameters':{'file_id':'file-1','enabled':True},'prompt_id':'prompt-1'}
    test_session.add(WorkflowExecutionModel(id='grants',workflow_id='workflow',user_id='alice',state='RUNNING',
        graph_json={'nodes':[deepcopy(node)]},initial_inputs={'source':'saved'}))
    await test_session.flush()
    test_session.add_all([WorkflowDispatchModel(execution_id='grants'),
        WorkflowNodeExecutionModel(execution_id='grants',node_id='node',plugin_id='plugin'),
        PluginRegistryModel(id='plugin',version='0.1.0',name='plugin',manifest_yaml=json.dumps({
            'plugin':{'name':'plugin','permissions':{'storage':{'enabled':True},
                'llm':{'enabled':True,'allowed_models':['small'],'allowed_purposes':['transform']}}}}))])
    await test_session.commit()
    fence = await claim(test_session,'grants','worker')
    await test_session.commit()
    attempt = await prepare_launch(test_session,execution_id='grants',node_id='node',owner='worker',
        fence=fence,role='plugin',image='sha256:'+'a'*64,daemon_id='daemon')
    await test_session.commit()
    return dict(execution_id='grants',node=node,ownership=('worker',fence),
        placement={'attempt_id':attempt,'daemon_id':'daemon'})


@pytest.mark.asyncio
async def test_policy_uses_saved_owner_and_exact_node_capabilities(test_session,assignment):
    assert not _same_data({'1':'value'},{1:'value'})
    assert not _same_data({'nested':[1]},{'nested':(1,)})
    policy = await assignment_policy(test_session,**assignment)
    assert policy['owner_id'] == 'alice'
    assert policy['file_ids'] == ['file-1'] and policy['prompt_ids'] == ['prompt-1']
    assert policy['manifest']['plugin']['permissions']['llm']['allowed_models'] == ['small']
    for change in ({'parameters':{'file_id':'other-file'}},{'prompt_id':'other-prompt'},{'plugin_id':'other'},
                   {'parameters':{'file_id':'file-1','enabled':1}}):
        forged = {**assignment,'node':{**assignment['node'],**change}}
        with pytest.raises(PermissionError,match='committed graph'):
            await assignment_policy(test_session,**forged)
    for change in ({'ownership':('worker',assignment['ownership'][1]+1)},
                   {'placement':{**assignment['placement'],'daemon_id':'other-daemon'}}):
        with pytest.raises(PermissionError):
            await assignment_policy(test_session,**{**assignment,**change})
    await test_session.rollback()


@pytest.mark.asyncio
async def test_grants_never_provision_forged_inputs_or_inactive_plugin(test_session,assignment):
    entered = []
    @asynccontextmanager
    async def provision(**fields):
        entered.append(fields)
        yield {'runtime':{},'environment':{}}
    factory = async_sessionmaker(test_session.bind,expire_on_commit=False)
    grants = assignment_grants(factory,provision)
    async with grants(**assignment,initial_inputs={'source':'saved'}):
        assert entered[0]['policy']['owner_id'] == 'alice'
        assert entered[0]['policy']['file_ids'] == ['file-1']
    entered.clear()
    with pytest.raises(PermissionError,match='inputs'):
        async with grants(**assignment,initial_inputs={'source':'forged'}):
            pytest.fail('Forged inputs reached credentials')
    assert not entered
    row = await test_session.get(PluginRegistryModel,('plugin','0.1.0'))
    row.active = False
    await test_session.commit()
    with pytest.raises(PermissionError,match='not active'):
        async with grants(**assignment,initial_inputs={'source':'saved'}):
            pytest.fail('Inactive plugin received credentials')
    assert not entered


@pytest.mark.asyncio
async def test_grants_borrow_one_reporting_capability_for_the_lease(test_session,assignment):
    from cryptography.fernet import Fernet
    from generated.credential_cipher import CredentialCipher
    from src.engine.credentials import ExecutionCredentials
    store = ExecutionCredentials(CredentialCipher(Fernet.generate_key()))
    test_session.add(store.prepare('grants','alice','la_saved',int(time.time())+900))
    await test_session.commit()
    tokens = []
    @asynccontextmanager
    async def provision(**fields):
        policy = fields['policy']
        assert policy['user_access_token'] == 'la_saved'
        assert policy['lease_owner'] == assignment['ownership'][0]
        assert policy['fence'] == assignment['ownership'][1]
        tokens.append(policy['report_token'])
        yield {}
    factory = async_sessionmaker(test_session.bind,expire_on_commit=False)
    grants = assignment_grants(factory,provision,credentials=store)
    for _ in range(2):
        async with grants(**assignment,initial_inputs={'source':'saved'}): pass
    assert len(set(tokens)) == 1
