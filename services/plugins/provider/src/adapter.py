"""Polza wire protocol only. HTTP pooling/TLS settings belong to codegen."""
import base64
import json
from urllib.parse import urlsplit

import httpx
from generated.http.client import run_blocking


POLZA_URL = 'https://polza.ai/api/v1'


class ProviderFailure(Exception):
    def __init__(self, kind):
        self.kind = kind
        super().__init__('Provider request failed')


def check_status(response):
    if response.status_code == 429:
        raise ProviderFailure('quota')
    if response.status_code < 200 or response.status_code >= 300:
        # No automatic retries or redirects: requests may already have been billed.
        raise ProviderFailure('upstream')
    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ProviderFailure('protocol')


async def sse_events(response, max_output_bytes):
    pending = bytearray()
    event = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > max_output_bytes:
            raise ProviderFailure('limit')
        pending.extend(chunk)
        while b'\n' in pending:
            line, _, rest = pending.partition(b'\n')
            pending = bytearray(rest)
            if len(line) > 65536:
                raise ProviderFailure('limit')
            try:
                text = line.rstrip(b'\r').decode('utf-8')
            except UnicodeError:
                raise ProviderFailure('protocol') from None
            if text == '':
                if event:
                    yield '\n'.join(event)
                    event.clear()
            elif text.startswith('data:'):
                event.append(text[5:].lstrip(' '))
            elif text.startswith(':') or text.startswith(('event:', 'id:', 'retry:')):
                continue
            else:
                raise ProviderFailure('protocol')
        if len(pending) > 65536:
            raise ProviderFailure('limit')
    if pending or event:
        raise ProviderFailure('protocol')


class PolzaAdapter:
    def __init__(self, client, token, *, test_endpoint=None):
        self.client = client
        self._token = token
        self.endpoint = POLZA_URL
        if test_endpoint is not None:
            parsed = urlsplit(test_endpoint)
            if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Test endpoint must be a numeric loopback HTTP URL')
            self.endpoint = test_endpoint.rstrip('/')
        if not isinstance(token, str) or not token or not token.isascii() or any(not 33 <= ord(char) <= 126 for char in token):
            raise ProviderFailure('configuration')

    def _headers(self):
        return {'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json',
                'Accept-Encoding': 'identity'}

    async def chat(self, payload, policy):
        finished, done, tokens = False, False, 0
        async with self.client.stream('POST', self.endpoint + '/chat/completions',
                headers=self._headers(), json=payload, follow_redirects=False) as response:
            check_status(response)
            if 'text/event-stream' not in response.headers.get('content-type', ''):
                raise ProviderFailure('protocol')
            async for event in sse_events(response, policy.max_output_bytes):
                if event == '[DONE]':
                    if not finished:
                        raise ProviderFailure('protocol')
                    done = True
                    break
                try:
                    data = json.loads(event)
                    if not isinstance(data, dict) or 'error' in data:
                        raise ValueError()
                    usage = data.get('usage')
                    if usage is not None:
                        tokens = usage.get('total_tokens', 0)
                        if not isinstance(tokens, int) or isinstance(tokens, bool) or not 0 <= tokens <= 2147483647:
                            raise ValueError()
                    choices = data.get('choices', [])
                    if not isinstance(choices, list) or len(choices) > 1:
                        raise ValueError()
                    if not choices:
                        continue
                    choice = choices[0]
                    if finished:
                        raise ValueError()
                    delta = choice.get('delta', {}).get('content')
                    if delta is not None and not isinstance(delta, str):
                        raise ValueError()
                    reason = choice.get('finish_reason')
                    if reason is not None:
                        if reason != 'stop':
                            raise ProviderFailure('limit' if reason == 'length' else 'protocol')
                        finished = True
                except (ValueError, TypeError, AttributeError, KeyError):
                    raise ProviderFailure('protocol') from None
                if delta:
                    yield delta, False, '', 0
        if not done:
            raise ProviderFailure('protocol')
        yield '', True, 'stop', tokens

    async def transcribe(self, body, metadata, policy):
        async def encoded_json():
            # Multiples of three keep each base64 fragment independently concatenable.
            fields={'model':metadata.model,'response_format':'json'}
            if metadata.language and metadata.language!='auto': fields['language']=metadata.language
            prefix = json.dumps(fields, separators=(',', ':'))[:-1]
            yield (prefix + ',"file":"data:' + metadata.content_type + ';base64,').encode()
            while True:
                chunk = await run_blocking(body.read, 49152)
                if not chunk:
                    break
                yield base64.b64encode(chunk)
            yield b'"}'
        async with self.client.stream('POST', self.endpoint + '/audio/transcriptions',
                headers=self._headers(), content=encoded_json(), follow_redirects=False) as response:
            check_status(response)
            result = bytearray()
            async for chunk in response.aiter_raw():
                result.extend(chunk)
                if len(result) > policy.max_output_bytes:
                    raise ProviderFailure('limit')
            try:
                payload = json.loads(result)
                text, language, duration = payload['text'], payload.get('language', ''), payload.get('duration', 0)
                if not isinstance(text, str) or not isinstance(language, str) or not isinstance(duration, (int, float)) or isinstance(duration, bool):
                    raise ValueError()
                import math
                if not math.isfinite(duration) or duration < 0 or 'error' in payload:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise ProviderFailure('protocol') from None
            return text, language, duration
