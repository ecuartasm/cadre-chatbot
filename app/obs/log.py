"""Structured logging — one cross-cutting module every layer emits into.

Three decisions worth stating.

**stdlib `logging`, not `structlog`.** A JSON formatter is ~20 lines; a dependency is forever.
Runtime deps stay at 4.

**`QueueHandler` + `QueueListener`.** `TimedRotatingFileHandler` writes synchronously, so calling it
from an async handler blocks the event loop on every line — and for longer during a midnight
rotation. The queue moves file I/O to a background thread; the request path only does an in-memory
put.

**Dual sink, always stdout.** stdout is captured by Railway's log drain and survives even if the
volume is lost, so the disk sink is additive rather than the only copy. `sink.py` decides whether
disk is available; this module wires up whatever it reports.
"""

from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from app.obs.sink import SINK

# Set by middleware per request, read by the formatter. A ContextVar (not a global) so concurrent
# requests on the same event loop cannot see each other's id.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Keys already on every LogRecord — everything else a caller passes via `extra=` is payload.
_STD_ATTRS = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno lineno module
    msecs message msg name pathname process processName relativeCreated stack_info thread
    threadName taskName""".split()
)


# Mint an id for one request.
#   out: 16 hex chars. Short enough for a user to read back over the phone, wide enough
#        (64 bits) that a collision inside a 7-day log window is not a practical concern.
def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Every record carries the request id, so a single grep reconstructs
    a whole turn across the middleware, the LLM client, and the cost layer."""

    # Render one log record as a single-line JSON object.
    #   in : record -- a stdlib LogRecord; anything passed via extra={} is merged in
    #   out: the JSON string written to the handler
    # `request_id` prefers the record's own attribute over the ContextVar, because a record
    # written from a generator's `finally` may run outside the request's context.
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=False)


_listener: logging.handlers.QueueListener | None = None


# Construct the handler set for the resolved sink.
#   in : nothing -- reads SINK, decided once at import by sink.py
#   out: [stdout] when stdout-only, or [stdout, app, interactions, errors] on disk.
# stdout is ALWAYS included: on Railway it is what `railway logs` shows, so the same lines are
# both streamed and persisted rather than one or the other.
def _build_handlers() -> list[logging.Handler]:
    fmt = JsonFormatter()

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(fmt)
    handlers: list[logging.Handler] = [stdout]

    if SINK.mode == "disk" and SINK.log_dir:
        # One file per stream so each is independently greppable. Rotating daily with
        # backupCount == retention days makes the config *be* the retention policy — there is no
        # separate cleanup job to forget to run.
        for name in ("app", "interactions", "errors"):
            fh = logging.handlers.TimedRotatingFileHandler(
                Path(SINK.log_dir) / f"{name}.jsonl",
                when="midnight",
                utc=True,
                backupCount=SINK.retention_days,
                encoding="utf-8",
                delay=True,
            )
            fh.setFormatter(fmt)
            fh.addFilter(_StreamFilter(name))
            handlers.append(fh)

    return handlers


class _StreamFilter(logging.Filter):
    """Routes records to the right file. A record's `stream` extra picks the file; anything
    without one lands in app.jsonl."""

    #   in : stream -- the stream name this filter admits ('app' | 'interactions' | 'errors')
    def __init__(self, stream: str) -> None:
        super().__init__()
        self.stream = stream

    # Decide whether a record belongs in this handler's file.
    #   in : record -- checked for a `stream` extra
    #   out: True to admit. Records with no `stream` default to 'app', so a forgotten extra
    #        lands somewhere greppable instead of being dropped.
    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "stream", "app") == self.stream


def configure() -> None:
    """Idempotent. Safe to call from module import and from tests."""
    global _listener
    if _listener is not None:
        return

    root = logging.getLogger("cadre")
    root.setLevel(logging.INFO)
    root.propagate = False
    root.handlers.clear()

    q: queue.Queue = queue.Queue(-1)
    root.addHandler(logging.handlers.QueueHandler(q))

    _listener = logging.handlers.QueueListener(q, *_build_handlers(), respect_handler_level=True)
    _listener.start()
    # Without this, records still in the queue at shutdown are lost — including the last error
    # before a crash, which is the one you most want.
    atexit.register(_shutdown)


# Stop the background QueueListener at interpreter exit so buffered records are flushed.
#   out: None. Idempotent -- safe if configure() was never called.
def _shutdown() -> None:
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def get_logger(name: str = "cadre") -> logging.LoggerAdapter:
    """Returns an adapter that stamps the current request id onto every record."""
    configure()
    base = logging.getLogger(name if name.startswith("cadre") else f"cadre.{name}")
    return _RequestAdapter(base, {})


# Wraps a stdlib Logger so callers never have to pass the request id by hand.
class _RequestAdapter(logging.LoggerAdapter):
    # Stamp the current request id onto every record.
    #   in : msg, kwargs -- the stdlib logging call as written
    #   out: the same pair, with extra['request_id'] filled from the ContextVar
    # setdefault, not assignment: an explicit request_id passed by the caller always wins.
    def process(self, msg, kwargs):  # noqa: ANN001, ANN201 — stdlib signature
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("request_id", request_id_var.get())
        return msg, kwargs
