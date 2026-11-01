"""Trace failures without exporting exception messages or payloads."""
import asyncio
from contextlib import contextmanager
from opentelemetry.trace import Status, StatusCode


@contextmanager
def safe_span(tracer, *args, **kwargs):
    with tracer.start_as_current_span(*args, record_exception=False,
            set_status_on_exception=False, **kwargs) as span:
        try:
            yield span
        except BaseException as error:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute('operation.outcome', 'cancelled' if isinstance(
                error, (asyncio.CancelledError, GeneratorExit)) else 'failed')
            raise
