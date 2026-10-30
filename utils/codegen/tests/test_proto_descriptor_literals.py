import ast
from pathlib import Path

from google.protobuf import descriptor_pb2

from config.models import ServiceManifest
from generators.services.grpc_client import GrpcClientGenerator


def test_descriptor_rewrite_preserves_quotes_and_backslashes(tmp_path: Path):
    output=tmp_path/'generated'
    output.mkdir()
    protocol=descriptor_pb2.FileDescriptorProto(name='index.proto')
    protocol.options.java_package="apostrophe'and\\backslash\nanddouble\"quote"
    source='descriptor = pool.AddSerializedFile(' + repr(protocol.SerializeToString()) + ')\n'
    module=output/'index_pb2.py'
    module.write_text(source)
    generator=GrpcClientGenerator(ServiceManifest.model_validate({'service':{'name':'quote_test'}}),output)
    generator._fix_pb2_descriptor_name(output,Path('/external/index.proto'),'quote_test')
    rewritten=module.read_text()
    tree=ast.parse(rewritten)
    compile(rewritten,str(module),'exec')
    literal=next(node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call))
    restored=descriptor_pb2.FileDescriptorProto.FromString(literal)
    assert restored.name=='quote_test/index.proto'
    assert restored.options.java_package==protocol.options.java_package
