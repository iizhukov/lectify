"""Compile trusted repository graphs; execute isolated per-request DAGs."""
import asyncio
import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from functools import partial

from .tracing import safe_span as traced_span
from types import MappingProxyType
from typing import Literal

import yaml
from google.protobuf.json_format import ParseDict
from opentelemetry import trace
from opentelemetry.trace import Link
from pydantic import BaseModel, ConfigDict, Field

tracer = trace.get_tracer('gateway.graph')

safe_span = partial(traced_span, tracer)



class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Http(StrictModel):
    method: Literal['POST'] = 'POST'
    path: str = Field(pattern=r'^/v[0-9]+/[a-zA-Z0-9_/-]+$')
    auth: Literal['required', 'public'] = 'required'
    request_schema: str
    response_schema: str


class Execution(StrictModel):
    timeout_ms: int = Field(default=3000, ge=1, le=60000)
    max_parallel_nodes: int = Field(default=8, ge=1, le=64)


class Rpc(StrictModel):
    service: str
    method: str


class Node(StrictModel):
    parents: list[str] = Field(default_factory=list)
    rpc: Rpc
    request: str
    timeout_ms: int = Field(default=1000, ge=1, le=60000)


class Response(StrictModel):
    parents: list[str]
    mapping: str


class Graph(StrictModel):
    version: Literal[1]
    id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    http: Http
    execution: Execution = Field(default_factory=Execution)
    nodes: dict[str, Node]
    response: Response


@dataclass(frozen=True)
class MappingContext:
    input: BaseModel
    parents: object
    principal: object


@dataclass(frozen=True)
class Plan:
    graph: Graph
    request_schema: type
    response_schema: type
    mappings: dict
    methods: dict
    response_mapping: object


def load_plans(root: Path, catalog: dict):
    plans, ids, routes = [], set(), set()
    for path in sorted(root.glob('*/graph.yaml')):
        graph = Graph.model_validate(yaml.safe_load(path.read_text()))
        route = (graph.http.method, graph.http.path)
        if graph.id in ids or route in routes:
            raise ValueError(f'Duplicate graph or route: {path}')
        ids.add(graph.id)
        routes.add(route)
        if not 1 <= len(graph.nodes) <= 128:
            raise ValueError('Graph must contain 1..128 nodes')
        visiting, visited = set(), set()

        def visit(name):
            if name in visiting:
                raise ValueError(f'Cycle at {name}')
            if name not in graph.nodes:
                raise ValueError(f'Unknown parent: {name}')
            if name in visited:
                return
            visiting.add(name)
            parents = graph.nodes[name].parents
            if len(parents) != len(set(parents)):
                raise ValueError(f'Duplicate parents: {name}')
            for parent in parents:
                visit(parent)
            visiting.remove(name)
            visited.add(name)

        if len(graph.response.parents) != len(set(graph.response.parents)):
            raise ValueError("Duplicate response parents")
        for name in graph.response.parents:
            visit(name)
        if visited != set(graph.nodes):
            raise ValueError('Unreachable nodes or empty response dependencies')
        modules = {}

        def resolve(ref, schema=False):
            module, attr = ref.split(':')
            if module not in ('mappings', 'schemas') or not attr.isidentifier() or attr.startswith('_'):
                raise ValueError(f'Invalid local reference: {ref}')
            if module not in modules:
                spec = importlib.util.spec_from_file_location(f'gateway_graph_{graph.id}_{module}', path.parent / (module + '.py'))
                obj = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = obj
                spec.loader.exec_module(obj)
                modules[module] = obj
            value = getattr(modules[module], attr)
            if schema:
                if not inspect.isclass(value) or not issubclass(value, BaseModel):
                    raise ValueError(f'Expected Pydantic schema: {ref}')
            elif not callable(value) or inspect.iscoroutinefunction(value):
                raise ValueError(f'Expected synchronous mapping: {ref}')
            return value

        mappings, methods = {}, {}
        for name, node in graph.nodes.items():
            method = catalog[(node.rpc.service, node.rpc.method)]
            if method.client_streaming or method.server_streaming:
                raise ValueError(f'Streaming RPC requires a dedicated adapter: {name}')
            methods[name] = method
            mappings[name] = resolve(node.request)
        plans.append(Plan(graph, resolve(graph.http.request_schema, True),
            resolve(graph.http.response_schema, True), mappings, methods, resolve(graph.response.mapping)))
    if not plans:
        raise ValueError('No graphs found')
    return plans


def mapping_context(data, principal, parents, results):
    copies = {}
    for name in parents:
        copy = type(results[name])()
        copy.CopyFrom(results[name])
        copies[name] = copy
    return MappingContext(data.model_copy(deep=True), MappingProxyType(copies), principal)


async def execute(plan, data, principal, metadata, clients, rpc_limit, deadline=None):
    graph = plan.graph
    deadline = deadline or asyncio.get_running_loop().time() + graph.execution.timeout_ms / 1000
    results, spans, tasks = {}, {}, {}
    parallel = asyncio.Semaphore(graph.execution.max_parallel_nodes)
    with safe_span('gateway.graph', attributes={'graph.id': graph.id}) as graph_span:
        graph_context = trace.set_span_in_context(graph_span)

        async def run(name):
            node = graph.nodes[name]
            for parent in node.parents:
                await tasks[parent]
            links = [Link(spans[parent]) for parent in node.parents]
            async with parallel:
                with safe_span('gateway.node', context=graph_context,
                        attributes={'graph.node': name}, links=links) as span:
                    spans[name] = span.get_span_context()
                    with safe_span('gateway.mapping.request'):
                        payload = plan.mappings[name](mapping_context(data, principal, node.parents, results))
                        if not isinstance(payload, dict):
                            raise TypeError('Request mapping must return dict')
                    with safe_span('gateway.protobuf.encode'):
                        request = ParseDict(payload, plan.methods[name].request_type(), ignore_unknown_fields=False)
                    timeout = min(node.timeout_ms / 1000, deadline - asyncio.get_running_loop().time())
                    async with asyncio.timeout(timeout):
                        async with rpc_limit:
                            results[name] = await plan.methods[name].bind(clients)(request,
                                metadata=metadata, timeout=max(.001, min(timeout, deadline - asyncio.get_running_loop().time())))

        try:
            for name in graph.nodes:
                tasks[name] = asyncio.create_task(run(name), context=None)
            await asyncio.gather(*tasks.values())
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
    with safe_span('gateway.response'):
        with safe_span('gateway.mapping.response'):
            payload = plan.response_mapping(mapping_context(data, principal, graph.response.parents, results))
        with safe_span('gateway.output.validate'):
            response = plan.response_schema.model_validate(payload)
        with safe_span('gateway.output.serialize'):
            return response.model_dump(mode='json')
