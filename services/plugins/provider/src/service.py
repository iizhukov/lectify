"""Business policy and protocol adaptation; servers/HTTP clients are generated."""
import asyncio
from contextlib import aclosing
import math
import tempfile
import time
import os

import grpc
import httpx

from generated.grpc_server.grpc_app import ProviderServiceBase
from generated.http.client import get_http_client, run_blocking
from generated.protos.server import index_pb2 as pb
from generated.settings import get_settings
from src.adapter import PolzaAdapter, ProviderFailure
from src.policy import ProviderPolicy


class ProviderServiceImpl(ProviderServiceBase):
    def __init__(self, adapter=None, policy=None):
        self._adapter = adapter
        self.policy = policy or ProviderPolicy.model_validate(get_settings().extensions.get('provider', {}))
        self._slots = asyncio.Semaphore(self.policy.max_concurrent)

    def _backend(self):
        if self._adapter is None:
            endpoint = os.environ.get('LECTIFY_PROVIDER_TEST_ENDPOINT')
            if endpoint is not None and os.environ.get('LECTIFY_ALLOW_TEST_PROVIDER') != '1':
                raise ProviderFailure('configuration')
            self._adapter = PolzaAdapter(get_http_client(), get_settings().http.bearer_token.get_secret_value(),
                test_endpoint=endpoint)
        return self._adapter

    async def _scope(self, request, context):
        if any(not value or len(value) > 128 or any(ord(char) < 32 for char in value)
               for value in (request.owner_id, request.execution_id, request.node_id)):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Execution scope is required')

    async def _failure(self, error, context):
        if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException)):
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'Provider deadline exceeded')
        if isinstance(error, ProviderFailure):
            if error.kind in ('quota', 'limit'):
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Provider request limit exceeded')
            if error.kind == 'protocol':
                await context.abort(grpc.StatusCode.DATA_LOSS, 'Invalid provider response')
        await context.abort(grpc.StatusCode.UNAVAILABLE, 'Provider unavailable')

    async def CallLLM(self, request, context):
        await self._scope(request, context)
        model = request.model or self.policy.default_chat_model
        if model not in self.policy.allowed_chat_models or request.purpose not in self.policy.allowed_purposes:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Model or purpose is not allowed')
        tokens = request.max_tokens or min(1024, self.policy.max_tokens)
        if not 1 <= tokens <= self.policy.max_tokens or not math.isfinite(request.temperature) or not 0 <= request.temperature <= 2:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid generation limits')
        if request.extra_params:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Extra generation parameters are not supported')
        if not 1 <= len(request.messages) <= 64 or sum(len(message.content) for message in request.messages) > self.policy.max_input_chars:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Input exceeds limit')
        if any(message.role not in ('system', 'developer', 'user', 'assistant') for message in request.messages):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Unsupported message role')
        payload = {'model': model, 'messages': [{'role': item.role, 'content': item.content} for item in request.messages],
            'temperature': request.temperature, 'max_tokens': tokens, 'stream': True,
            'stream_options': {'include_usage': True}, 'user': request.owner_id}
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.policy.timeout_seconds):
                async with self._slots:
                    async with aclosing(self._backend().chat(payload, self.policy)) as stream:
                        async for delta, final, reason, usage in stream:
                            yield pb.LLMResponse(delta_content=delta, is_finished=final, finish_reason=reason,
                                tokens_used=usage, latency_ms=int((time.monotonic() - started) * 1000))
        except (ProviderFailure, httpx.HTTPError, asyncio.TimeoutError) as error:
            await self._failure(error, context)

    async def Transcribe(self, request_iterator, context):
        try:
            async with asyncio.timeout(self.policy.timeout_seconds):
                async with self._slots:
                    iterator = request_iterator.__aiter__()
                    try:
                        first = await anext(iterator)
                    except StopAsyncIteration:
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Audio metadata is required')
                    if first.WhichOneof('data') != 'metadata' or first.sequence != 0 or first.is_last:
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Audio stream starts with metadata')
                    metadata = pb.AudioMetadata()
                    metadata.CopyFrom(first.metadata)
                    await self._scope(metadata, context)
                    metadata.model = metadata.model or self.policy.default_audio_model
                    if metadata.model not in self.policy.allowed_audio_models or 'stt' not in self.policy.allowed_purposes:
                        await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Transcription is not allowed')
                    if not 1 <= metadata.size_bytes <= self.policy.max_audio_bytes:
                        await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Audio exceeds limit')
                    if metadata.content_type not in ('audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/flac', 'audio/ogg', 'audio/webm'):
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Unsupported audio type')
                    if metadata.language and metadata.language != 'auto' and (len(metadata.language) != 2 or not metadata.language.isascii() or not metadata.language.isalpha()):
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid language')
                    size, sequence, closed = 0, 1, False
                    with tempfile.SpooledTemporaryFile(max_size=1048576, mode='w+b') as audio:
                        async for frame in iterator:
                            if closed or frame.WhichOneof('data') != 'chunk' or frame.sequence != sequence:
                                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid audio stream sequence')
                            sequence += 1
                            if len(frame.chunk) > 65536 or size + len(frame.chunk) > metadata.size_bytes:
                                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Audio chunk exceeds limit')
                            size += len(frame.chunk)
                            await run_blocking(audio.write, frame.chunk)
                            closed = frame.is_last
                        if not closed or size != metadata.size_bytes:
                            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Audio requires EOF and exact size')
                        audio.seek(0)
                        text, language, duration = await self._backend().transcribe(audio, metadata, self.policy)
                        return pb.TranscribeResponse(text=text, language=language, duration=duration)
        except (ProviderFailure, httpx.HTTPError, asyncio.TimeoutError) as error:
            await self._failure(error, context)
