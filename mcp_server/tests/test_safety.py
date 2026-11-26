"""Server-level guardrails: audit log (R8), local-only transport (R6), no committed tokens (R7)."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from mcp_server.safety import audit_logger, audited, check_transport

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_each_tool_call_writes_one_audit_line_without_row_contents(tmp_path):
    log_path = tmp_path / "audit.log"

    @audited(audit_logger(log_path))
    def get_transactions(**kwargs):
        return {
            "rows": [{"merchant_name": "SECRET MERCHANT", "amount_gbp": -12.34}],
            "total_count": 1,
            "query_echo": {"start_date": "2026-11-13", "end_date": "2026-11-25", "limit": 100},
        }

    get_transactions(start_date="2026-11-13", end_date="2026-11-25")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "get_transactions"
    assert entry["params"]["start_date"] == "2026-11-13"
    assert entry["row_count"] == 1
    assert "duration_ms" in entry
    assert "SECRET MERCHANT" not in lines[0] and "12.34" not in lines[0]


def test_failed_calls_are_logged_with_the_error_type(tmp_path):
    log_path = tmp_path / "audit.log"

    @audited(audit_logger(log_path))
    def get_spend_summary(**kwargs):
        raise ValueError("bad group_by")

    with pytest.raises(ValueError):
        get_spend_summary(group_by="nope")
    entry = json.loads(log_path.read_text(encoding="utf-8"))
    assert entry["error"] == "ValueError" and entry["params"] == {"group_by": "nope"}


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", None])
def test_refuses_to_bind_http_beyond_loopback(host):
    with pytest.raises(SystemExit, match="refusing to start"):
        check_transport("streamable-http", host)


@pytest.mark.parametrize("transport,host", [("stdio", None), ("streamable-http", "127.0.0.1"), ("sse", "localhost")])
def test_allows_stdio_and_loopback(transport, host):
    check_transport(transport, host)


def test_no_tokens_committed_to_the_repo():
    # Monzo access/refresh tokens are JWTs ("eyJ" = base64 of '{"'); GitHub tokens have fixed
    # prefixes. Tracked files only - .env and friends are gitignored and never committed.
    files = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    pattern = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}")
    hits = []
    for name in files:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            hits.append(name)
    assert hits == [], f"token-like strings in tracked files: {hits}"
