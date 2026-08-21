"""Structured logs and per-stage timings, keyed by a trace id.

A query touches the router, the embedder, Postgres, Neo4j, and an LLM.
When one is slow, "the query took 4 seconds" tells you nothing. Timing
each stage under one trace id tells you which.
"""

import json
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.config.settings import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()

    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


logger = logging.getLogger("rag")


def log(message: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, message, extra={"extra_fields": fields})


@dataclass
class Trace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stages: dict[str, float] = field(default_factory=dict)
    notes: dict[str, object] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str):
        began = time.perf_counter()
        try:
            yield self
        finally:
            elapsed = (time.perf_counter() - began) * 1000
            self.stages[name] = round(self.stages.get(name, 0.0) + elapsed, 2)

    def note(self, **fields) -> None:
        self.notes.update(fields)

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "total_ms": self.total_ms,
            "stages": self.stages,
            **self.notes,
        }

    def emit(self, message: str = "query") -> None:
        log(message, **self.to_dict())

    def slowest(self) -> tuple[str, float] | None:
        if not self.stages:
            return None
        name = max(self.stages, key=lambda k: self.stages[k])
        return name, self.stages[name]


if __name__ == "__main__":

    configure_logging()

    trace = Trace()

    with trace.stage("route"):
        time.sleep(0.01)

    with trace.stage("vector_search"):
        time.sleep(0.05)

    with trace.stage("generate"):
        time.sleep(0.02)

    trace.note(route="hybrid", chunks=7)
    trace.emit()

    print()
    print("slowest stage:", trace.slowest())
