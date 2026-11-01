"""HTTP boundary, bounded requests, authentication and per-request trace lifecycle."""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from functools import partial

from .tracing import safe_span as traced_span
from uuid import uuid4

import grpc
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import ValidationError

from .graph import execute, load_plans

tracer = trace.get_tracer('gateway.http')

safe_span = partial(traced_span, tracer)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    is_admin: bool


class HttpFailure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class HttpTracing:
    def __init__(self, app, max_requests=128, max_body_bytes=1048576, trust_trace_context=False):
        self.app = app
        self.active = 0
        self.max_requests = max_requests
        self.max_body_bytes = max_body_bytes
        self.trust_trace_context = trust_trace_context

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        parent = trace.Context()
        if self.trust_trace_context:
            carrier = {k.decode().lower(): v.decode() for k, v in scope['headers']
                if k.lower() in (b'traceparent', b'tracestate')}
            parent = propagate.extract(carrier, context=parent)
        with safe_span('HTTP request', context=parent, kind=SpanKind.SERVER) as span:
            request_id = uuid4().hex
            scope.setdefault('state', {})['request_id'] = request_id
            span.set_attribute('http.request.method', scope['method'])
            span.set_attribute('request.id', request_id)

            async def traced_send(message):
                if message['type'] == 'http.response.start':
                    status = message['status']
                    span.set_attribute('http.response.status_code', status)
                    route = scope.get('route')
                    if route:
                        span.update_name(scope['method'] + ' ' + route.path)
                        span.set_attribute('http.route', route.path)
                    if status >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                    message['headers'] = list(message.get('headers', [])) + [
                        (b'x-request-id', request_id.encode()),
                        (b'x-trace-id', format(span.get_span_context().trace_id, '032x').encode())]
                await send(message)

            async def error(status, code):
                await JSONResponse({'code': code, 'request_id': request_id}, status_code=status)(scope, receive, traced_send)

            if self.active >= self.max_requests:
                return await error(503, 'GATEWAY_BUSY')
            self.active += 1
            try:
                chunks, size = [], 0
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        chunk = message.get('body', b'')
                        size += len(chunk)
                        if size > self.max_body_bytes:
                            return await error(413, 'BODY_TOO_LARGE')
                        chunks.append(chunk)
                        if not message.get('more_body', False):
                            break
                pending = True

                async def replay():
                    nonlocal pending
                    if pending:
                        pending = False
                        return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
                    return await receive()

                await self.app(scope, replay, traced_send)
            except TimeoutError:
                await error(408, 'BODY_TIMEOUT')
            finally:
                self.active -= 1


def create_app(graph_root=None, *, clients=None, catalog=None, authenticate=None, configure=None):
    root = graph_root or Path(__file__).resolve().parents[1] / 'graphs'

    @asynccontextmanager
    async def lifespan(app):
        if configure:
            configure()
        if clients is None:
            from generated.grpc_client.grpc_clients import GrpcClients
            from generated.grpc_client.rpc_catalog import get_rpc_catalog
            app.state.clients = GrpcClients()
            app.state.catalog = get_rpc_catalog()
        else:
            app.state.clients, app.state.catalog = clients, catalog
        app.state.rpc_limit = asyncio.Semaphore(128)
        try:
            plans = load_plans(root, app.state.catalog)
            app.state.plans = plans
            for plan in plans:
                app.add_api_route(plan.graph.http.path, endpoint(plan), methods=[plan.graph.http.method],
                    operation_id=plan.graph.id, response_model=plan.response_schema)
            app.openapi_schema = None
            yield
        finally:
            await app.state.clients.close_all()
            if configure:
                trace.get_tracer_provider().force_flush()
                trace.get_tracer_provider().shutdown()

    app = FastAPI(title='Lectify Gateway', lifespan=lifespan)
    app.add_middleware(HttpTracing, trust_trace_context=os.environ.get('GATEWAY_TRUST_TRACE_CONTEXT') == 'true')

    def failure(request, status, code):
        return JSONResponse({'code': code, 'request_id': request.state.request_id}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return failure(request, 422, 'INVALID_INPUT')

    async def auth(request):
        values = request.headers.getlist('authorization')
        if (len(values) != 1 or not values[0].startswith('Bearer ')
                or not 7 < len(values[0]) <= 4103
                or any(ord(c) <= 32 or ord(c) >= 127 for c in values[0][7:])):
            raise HttpFailure(401, 'UNAUTHENTICATED')
        token = values[0][7:]
        if authenticate:
            result = await authenticate(token)
        else:
            method = app.state.catalog[('api_auth', 'auth.v1.AuthService/Authenticate')]
            async with app.state.rpc_limit:
                result = await method.bind(app.state.clients)(method.request_type(access_token=token), timeout=3)
        if not result.valid or not result.user_id:
            raise HttpFailure(401, 'UNAUTHENTICATED')
        return Principal(result.user_id, result.username, result.is_admin), (('x-user-authorization', values[0]),)

    def endpoint(plan):
        async def handler(request: Request):
            async def run():
                try:
                    deadline = asyncio.get_running_loop().time() + plan.graph.execution.timeout_ms / 1000
                    async with asyncio.timeout_at(deadline):
                        with safe_span('gateway.auth'):
                            principal, metadata = await auth(request) if plan.graph.http.auth == 'required' else (None, ())
                        with safe_span('gateway.input.validate'):
                            try:
                                data = plan.request_schema.model_validate(await request.json())
                            except (ValidationError, ValueError):
                                raise HttpFailure(422, 'INVALID_INPUT') from None
                        result = await execute(plan, data, principal, metadata, app.state.clients, app.state.rpc_limit, deadline)
                        # Serialize before sending headers; errors can still become a structured HTTP response.
                        with safe_span('gateway.http.encode'):
                            body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                            if len(body) > 4194304:
                                raise HttpFailure(502, 'RESPONSE_TOO_LARGE')
                        from starlette.responses import Response
                        return Response(body, media_type='application/json')
                except HttpFailure as error:
                    return failure(request, error.status, error.code)
                except TimeoutError:
                    return failure(request, 504, 'DEADLINE_EXCEEDED')
                except grpc.aio.AioRpcError as error:
                    statuses = {grpc.StatusCode.UNAUTHENTICATED: 401, grpc.StatusCode.PERMISSION_DENIED: 403,
                        grpc.StatusCode.NOT_FOUND: 404, grpc.StatusCode.INVALID_ARGUMENT: 422,
                        grpc.StatusCode.ALREADY_EXISTS: 409, grpc.StatusCode.ABORTED: 409,
                        grpc.StatusCode.FAILED_PRECONDITION: 409, grpc.StatusCode.UNAVAILABLE: 503,
                        grpc.StatusCode.DEADLINE_EXCEEDED: 504, grpc.StatusCode.RESOURCE_EXHAUSTED: 503}
                    return failure(request, statuses.get(error.code(), 502), error.code().name)
                except Exception:
                    log.error('Gateway failed: request_id=%s', request.state.request_id)
                    return failure(request, 500, 'INTERNAL_ERROR')

            await request.body()
            task = asyncio.create_task(run())

            async def disconnected():
                while True:
                    message = await request.receive()
                    if message['type'] == 'http.disconnect':
                        return
            watcher = asyncio.create_task(disconnected())
            try:
                done, _ = await asyncio.wait([task, watcher], return_when=asyncio.FIRST_COMPLETED)
                if task in done:
                    return await task
                raise asyncio.CancelledError()
            finally:
                task.cancel()
                watcher.cancel()
                await asyncio.gather(task, watcher, return_exceptions=True)

        # Explicit schema supplies the body in OpenAPI while parsing/validation remains inside spans.
        handler.__name__ = plan.graph.id
        handler.__doc__ = f'Graph: {plan.graph.id}'
        return handler

    @app.get('/health/live', include_in_schema=False)
    async def live():
        return {'status': 'ok'}

    @app.get('/health/ready', include_in_schema=False)
    async def ready():
        return {'status': 'ready', 'graphs': len(app.state.plans)}

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        for plan in app.state.plans:
            model_schema = plan.request_schema.model_json_schema(ref_template='#/components/schemas/{model}')
            definitions = model_schema.pop('$defs', {})
            schema.setdefault('components', {}).setdefault('schemas', {}).update(definitions)
            schema['paths'][plan.graph.http.path]['post']['requestBody'] = {
                'required': True, 'content': {'application/json': {'schema': model_schema}}}
            if plan.graph.http.auth == 'required':
                schema['paths'][plan.graph.http.path]['post']['security'] = [{'BearerAuth': []}]
        schema.setdefault('components', {}).setdefault('securitySchemes', {})['BearerAuth'] = {
            'type': 'http', 'scheme': 'bearer'}
        return schema
    app.openapi = openapi
    return app
