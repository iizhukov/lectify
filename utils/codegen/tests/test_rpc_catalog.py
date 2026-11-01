from types import ModuleType, SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool
from templates import env


def test_catalog_uses_all_descriptor_services_and_cardinalities(monkeypatch):
    descriptor = descriptor_pb2.FileDescriptorProto(name='catalog_multi.proto', package='catalog.test', syntax='proto3')
    descriptor.message_type.add(name='Request')
    descriptor.message_type.add(name='Reply')
    for name, client_stream, server_stream in [('First', False, False), ('Second', True, True)]:
        service = descriptor.service.add(name=name)
        service.method.add(name='Call', input_type='.catalog.test.Request', output_type='.catalog.test.Reply',
            client_streaming=client_stream, server_streaming=server_stream)
    pb = SimpleNamespace(DESCRIPTOR=descriptor_pool.DescriptorPool().Add(descriptor))
    source = env.get_template('services/grpc/client/rpc_catalog.py.j2').render(
        client_services=[{'name': 'external', 'proto_module': 'index'}])
    module = ModuleType('test_catalog_generated')
    import sys
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source, '<rendered rpc_catalog>', 'exec'), module.__dict__)
    module.import_module = lambda name: pb
    catalog = module.get_rpc_catalog()
    assert set(catalog) == {('external', 'catalog.test.First/Call'), ('external', 'catalog.test.Second/Call')}
    unary = catalog['external', 'catalog.test.First/Call']
    stream = catalog['external', 'catalog.test.Second/Call']
    assert not unary.client_streaming and not unary.server_streaming
    assert stream.client_streaming and stream.server_streaming
    assert unary.request_type.DESCRIPTOR.full_name == 'catalog.test.Request'
    assert unary.response_type.DESCRIPTOR.full_name == 'catalog.test.Reply'
