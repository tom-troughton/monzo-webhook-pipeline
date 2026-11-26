"""Transaction-level query tools over the `mcp_transactions` view (marts/mcp_transactions.parquet,
built by dbt/models/marts/mcp_transactions.sql). Same pattern as tools.py: plain functions taking a
connection, so they test against an in-memory DuckDB.

Guardrails live here rather than in the MCP wrappers so the tests exercise them directly:
  * every query is a fixed SELECT with bound parameters; enums map to fixed SQL fragments (R2);
  * row-level tools need a date range of at most 366 days and return at most 500 rows (R3);
  * notes are left out unless include_notes=True (R4) - the text itself was already sanitised and
    the counterparty masked in the dbt model (R4/R5);
  * this module reads nothing but `mcp_transactions` (R9).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import duckdb

LONDON = ZoneInfo("Europe/London")
SOURCE = "mcp_transactions"

ROW_LEVEL_MAX_DAYS = 366
SUMMARY_MAX_DAYS = 5 * 366
MAX_ROWS = 500
SEARCH_MAX_ROWS = 200
SEARCH_DEFAULT_DAYS = 365

ROW_COLUMNS = [
    "transaction_id", "created_at", "amount_gbp", "local_amount", "local_currency", "merchant_name",
    "merchant_group", "merchant_country", "merchant_city", "is_online", "category", "account",
    "counterparty", "is_declined",
]

ORDER_BY = {
    "created_at_desc": "created_at desc, transaction_id",
    "created_at_asc": "created_at asc, transaction_id",
    "amount_desc": "amount_gbp desc, created_at desc",
    "amount_asc": "amount_gbp asc, created_at desc",
}

# Time buckets are London-local, so a 23:30 BST purchase lands on the day it happened locally.
_LOCAL_TS = "((created_at at time zone 'UTC') at time zone 'Europe/London')"
GROUP_BY = {
    "merchant_group": "coalesce(merchant_group, merchant_name, '(no merchant)')",
    "category": "category",
    "local_currency": "local_currency",
    "merchant_country": "coalesce(merchant_country, '(unknown)')",
    "day": f"strftime(date_trunc('day', {_LOCAL_TS}), '%Y-%m-%d')",
    "week": f"strftime(date_trunc('week', {_LOCAL_TS}), '%Y-%m-%d')",
    "month": f"strftime(date_trunc('month', {_LOCAL_TS}), '%Y-%m')",
}
TIME_GROUPINGS = {"day", "week", "month"}
DEFAULT_EXCLUDED_CATEGORIES = ("savings", "transfers")


class ToolInputError(ValueError):
    """Raised for invalid tool input. The message is returned to the MCP client verbatim."""


# --- input handling ---------------------------------------------------------------------------

def _parse_date(value: str | date, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolInputError(f"{name} must be a date in YYYY-MM-DD form, got {value!r}") from None


def _date_range(start, end, max_days: int) -> tuple[date, date]:
    if start is None or end is None:
        raise ToolInputError("start_date and end_date are both required")
    start_d, end_d = _parse_date(start, "start_date"), _parse_date(end, "end_date")
    if end_d < start_d:
        raise ToolInputError("end_date must be on or after start_date")
    days = (end_d - start_d).days + 1
    if days > max_days:
        raise ToolInputError(f"date range is {days} days; the limit for this tool is {max_days} days")
    return start_d, end_d


def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive London-local dates -> [start, end) as naive UTC, matching created_at's storage."""
    def to_utc(d: date) -> datetime:
        return datetime.combine(d, time.min, tzinfo=LONDON).astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start), to_utc(end + timedelta(days=1))


def _clamp(value, default: int, maximum: int) -> tuple[int, bool]:
    try:
        requested = default if value is None else int(value)
    except (TypeError, ValueError):
        raise ToolInputError(f"limit must be an integer, got {value!r}") from None
    clamped = min(max(requested, 1), maximum)
    return clamped, clamped != requested


def _offset(value) -> int:
    try:
        offset = 0 if value is None else int(value)
    except (TypeError, ValueError):
        raise ToolInputError(f"offset must be an integer, got {value!r}") from None
    if offset < 0:
        raise ToolInputError("offset must be 0 or more")
    return offset


def _code(value: str | None, name: str, pattern: str) -> str | None:
    if value is None:
        return None
    code = str(value).strip().upper()
    if not re.fullmatch(pattern, code):
        raise ToolInputError(f"{name} must match {pattern}, got {value!r}")
    return code


def _like_pattern(text: str) -> str:
    """Contains-match pattern with LIKE wildcards in the user's text escaped (R2)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _valid_categories(con) -> list[str]:
    return [r[0] for r in con.execute(
        f"select distinct category from {SOURCE} where category is not null order by 1"
    ).fetchall()]


def _check_category(con, category: str | None, name: str = "category") -> str | None:
    if category is None:
        return None
    valid = _valid_categories(con)
    if category not in valid:
        raise ToolInputError(f"unknown {name} {category!r}; valid values: {', '.join(valid)}")
    return category


# --- output handling --------------------------------------------------------------------------

def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(result) -> list[dict]:
    columns = [c[0] for c in result.description]
    return [{c: _jsonable(v) for c, v in zip(columns, row)} for row in result.fetchall()]


def _select(con, sql: str, params: list):
    # Belt and braces for R1/R2: nothing in this module is anything but a SELECT.
    assert sql.lstrip().lower().startswith(("select", "with")), "transaction tools only run SELECTs"
    return con.execute(sql, params)


def _envelope(rows, total_count, offset, limit, clamped, echo) -> dict:
    more = offset + len(rows) < total_count
    return {
        "rows": rows,
        "total_count": total_count,
        "next_offset": offset + len(rows) if more else None,
        "truncated": bool(more or clamped),
        "query_echo": echo,
    }


def _page(con, where: list[str], params: list, order_by: str, limit: int, offset: int, include_notes: bool):
    columns = ", ".join(ROW_COLUMNS + (["notes"] if include_notes else []))
    where_sql = " and ".join(where) if where else "true"
    total = _select(con, f"select count(*) from {SOURCE} where {where_sql}", params).fetchone()[0]
    rows = _rows(_select(
        con,
        f"select {columns} from {SOURCE} where {where_sql} order by {order_by} limit ? offset ?",
        params + [limit, offset],
    ))
    return rows, total


# --- tools ------------------------------------------------------------------------------------

def get_transactions(
    con: duckdb.DuckDBPyConnection,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
    currency: str | None = None,
    country: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    include_declined: bool = False,
    include_notes: bool = False,
    order_by: str = "created_at_desc",
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    start, end = _date_range(start_date, end_date, ROW_LEVEL_MAX_DAYS)
    if order_by not in ORDER_BY:
        raise ToolInputError(f"order_by must be one of: {', '.join(ORDER_BY)}")
    lim, clamped = _clamp(limit, 100, MAX_ROWS)
    off = _offset(offset)
    category = _check_category(con, category)
    currency = _code(currency, "currency", "[A-Z]{3}")
    country = _code(country, "country", "[A-Z]{2,3}")
    merchant = merchant.strip() if merchant else None

    lo, hi = _utc_bounds(start, end)
    where, params = ["created_at >= ?", "created_at < ?"], [lo, hi]
    if not include_declined:
        where.append("not is_declined")
    if category:
        where.append("category = ?"); params.append(category)
    if merchant:
        where.append("(merchant_group ilike ? escape '\\' or merchant_name ilike ? escape '\\')")
        params += [_like_pattern(merchant)] * 2
    if currency:
        where.append("local_currency = ?"); params.append(currency)
    if country:
        where.append("merchant_country = ?"); params.append(country)
    if min_amount is not None:
        where.append("amount_gbp >= ?"); params.append(float(min_amount))
    if max_amount is not None:
        where.append("amount_gbp <= ?"); params.append(float(max_amount))

    rows, total = _page(con, where, params, ORDER_BY[order_by], lim, off, include_notes)
    echo = {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "category": category,
        "merchant": merchant, "currency": currency, "country": country, "min_amount": min_amount,
        "max_amount": max_amount, "include_declined": include_declined, "include_notes": include_notes,
        "order_by": order_by, "limit": lim, "offset": off,
    }
    return _envelope(rows, total, off, lim, clamped, echo)


def search_transactions(
    con: duckdb.DuckDBPyConnection,
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    include_notes: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    today: date | None = None,
) -> dict:
    text = (query or "").strip()
    if not 2 <= len(text) <= 100:
        raise ToolInputError("query must be 2-100 characters")
    if start_date is None and end_date is None:
        end_d = today or datetime.now(LONDON).date()
        start_date, end_date = end_d - timedelta(days=SEARCH_DEFAULT_DAYS - 1), end_d
    start, end = _date_range(start_date, end_date, ROW_LEVEL_MAX_DAYS)
    lim, clamped = _clamp(limit, 50, SEARCH_MAX_ROWS)
    off = _offset(offset)

    lo, hi = _utc_bounds(start, end)
    pattern = _like_pattern(text)
    fields = ["merchant_name", "merchant_group"] + (["notes"] if include_notes else [])
    match = " or ".join(f"{f} ilike ? escape '\\'" for f in fields)
    where = ["created_at >= ?", "created_at < ?", "not is_declined", f"({match})"]
    params = [lo, hi] + [pattern] * len(fields)

    rows, total = _page(con, where, params, ORDER_BY["created_at_desc"], lim, off, include_notes)
    echo = {
        "query": text, "start_date": start.isoformat(), "end_date": end.isoformat(),
        "include_notes": include_notes, "limit": lim, "offset": off,
    }
    return _envelope(rows, total, off, lim, clamped, echo)


def get_spend_summary(
    con: duckdb.DuckDBPyConnection,
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: str | None = None,
    category: str | None = None,
    currency: str | None = None,
    country: str | None = None,
    exclude_categories: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Spend is gross outgoing money (debits, as a positive number); credits in the same scope
    (refunds, cashback) are reported separately as refunds_gbp, and net_gbp = total - refunds.
    Declined transactions never count."""
    start, end = _date_range(start_date, end_date, SUMMARY_MAX_DAYS)
    if group_by not in GROUP_BY:
        raise ToolInputError(f"group_by is required and must be one of: {', '.join(GROUP_BY)}")
    lim, clamped = _clamp(limit, 50, MAX_ROWS)
    category = _check_category(con, category)
    currency = _code(currency, "currency", "[A-Z]{3}")
    country = _code(country, "country", "[A-Z]{2,3}")
    # Not validated against known categories: excluding one that never occurs is a harmless no-op,
    # and the defaults must keep working on data that happens to have no savings rows.
    excluded = [str(c) for c in (DEFAULT_EXCLUDED_CATEGORIES if exclude_categories is None else exclude_categories)]

    lo, hi = _utc_bounds(start, end)
    where, params = ["created_at >= ?", "created_at < ?", "not is_declined"], [lo, hi]
    if category:
        where.append("category = ?"); params.append(category)
    if currency:
        where.append("local_currency = ?"); params.append(currency)
    if country:
        where.append("merchant_country = ?"); params.append(country)
    if excluded:
        where.append(f"category not in ({', '.join('?' * len(excluded))})"); params += excluded
    where_sql = " and ".join(where)

    key = GROUP_BY[group_by]
    local_total = (
        ", sum(case when amount_gbp < 0 then -local_amount else 0 end) as total_local"
        if group_by == "local_currency" else ""
    )
    order = "group_key" if group_by in TIME_GROUPINGS else "total_gbp desc, group_key"
    grouped = f"""
        select
            {key} as group_key,
            sum(case when amount_gbp < 0 then -amount_gbp else 0 end) as total_gbp,
            sum(case when amount_gbp > 0 then amount_gbp else 0 end) as refunds_gbp,
            count(*) as transaction_count,
            min(created_at) as first_at,
            max(created_at) as last_at
            {local_total}
        from {SOURCE}
        where {where_sql}
        group by 1
    """
    total_groups = _select(con, f"select count(*) from ({grouped})", params).fetchone()[0]
    rows = _rows(_select(con, f"select * from ({grouped}) order by {order} limit ?", params + [lim]))
    for row in rows:
        row["net_gbp"] = round(row["total_gbp"] - row["refunds_gbp"], 2)
    totals = _select(con, f"""
        select
            coalesce(sum(case when amount_gbp < 0 then -amount_gbp else 0 end), 0),
            coalesce(sum(case when amount_gbp > 0 then amount_gbp else 0 end), 0)
        from {SOURCE} where {where_sql}
    """, params).fetchone()

    echo = {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "group_by": group_by,
        "category": category, "currency": currency, "country": country,
        "exclude_categories": excluded, "limit": lim,
    }
    result = _envelope(rows, total_groups, 0, lim, clamped, echo)
    result["next_offset"] = None  # summaries aren't paged; raise limit instead
    result["grand_total_gbp"] = _jsonable(totals[0])
    result["grand_refunds_gbp"] = _jsonable(totals[1])
    return result
