"""Server-level guardrails that aren't about any one query: the audit log (spec R8) and the
local-transport check (R6). Kept apart from server.py, which opens the real Blob Storage connection
at import, so both are testable without Azure.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_AUDIT_LOG = Path(__file__).resolve().parent / "logs" / "audit.log"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def audit_logger(path: str | os.PathLike | None = None) -> logging.Logger:
    path = Path(path or os.environ.get("MONZO_MCP_AUDIT_LOG") or DEFAULT_AUDIT_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"monzo_mcp.audit.{path}")
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # never echo to stderr/stdio, which is the MCP channel
    return logger


def audited(logger: logging.Logger):
    """One JSON line per tool call: timestamp, tool, effective parameters, row count, duration.
    Never the returned rows - the log is a second copy of nothing but what was asked."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": fn.__name__}
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                entry.update(params=kwargs, error=type(exc).__name__)
                raise
            else:
                if isinstance(result, dict) and "query_echo" in result:
                    entry.update(params=result["query_echo"], row_count=len(result["rows"]))
                elif isinstance(result, list):
                    entry.update(params=kwargs, row_count=len(result))
                else:
                    entry.update(params=kwargs, row_count=1)
                return result
            finally:
                entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
                logger.info(json.dumps(entry, default=str))
        return wrapper
    return decorate


def check_transport(transport: str, host: str | None) -> None:
    """Refuse anything but stdio or loopback HTTP (R6): this server returns personal financial
    data and has no authentication, so it must never listen on a reachable interface."""
    if transport == "stdio":
        return
    if transport not in {"sse", "streamable-http"}:
        raise SystemExit(f"unknown MCP transport {transport!r}")
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"refusing to start: {transport} transport must bind to a loopback address "
            f"({', '.join(sorted(LOOPBACK_HOSTS))}), not {host!r}"
        )
