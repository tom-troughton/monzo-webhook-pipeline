"""Curated query functions over the marts/staging views registered by marts.connect().
Kept as plain functions taking a connection (rather than reaching for a global connection
inside each one) so they're testable against an in-memory DuckDB with fixture data - see tests/.
"""
from datetime import date, datetime

import duckdb

from .marts import MARTS


def _as_dicts(result) -> list[dict]:
    columns = [c[0] for c in result.description]
    rows = []
    for row in result.fetchall():
        record = {}
        for col, value in zip(columns, row):
            if isinstance(value, (datetime, date)):
                value = value.isoformat()
            record[col] = value
        rows.append(record)
    return rows


def get_spend_by_category(con: duckdb.DuckDBPyConnection, month: str | None = None) -> list[dict]:
    """Spend per category. `month`, if given, filters to a single "YYYY-MM" - otherwise all months."""
    query = "select transaction_month, category, category_label, total_spend, transaction_count from spend_by_category"
    params = []
    if month:
        query += " where strftime(transaction_month, '%Y-%m') = ?"
        params.append(month)
    query += " order by transaction_month, total_spend desc"
    return _as_dicts(con.execute(query, params))


def get_monthly_cashflow(con: duckdb.DuckDBPyConnection, months: int | None = None) -> list[dict]:
    """Income/expenses/net per calendar month, most recent first unless `months` limits the window."""
    query = "select transaction_month, income, expenses, net from monthly_cashflow order by transaction_month desc"
    params = []
    if months is not None:
        query += " limit ?"
        params.append(int(months))
    return _as_dicts(con.execute(query, params))


def get_top_merchants(con: duckdb.DuckDBPyConnection, limit: int = 10) -> list[dict]:
    """Highest-spend merchants, excluding declined transactions (mart already does)."""
    query = """
        select merchant_name, merchant_category, total_spend, transaction_count,
               avg_transaction_amount, last_transaction_at
        from merchant_summary
        order by total_spend desc
        limit ?
    """
    return _as_dicts(con.execute(query, [int(limit)]))


def get_subscriptions(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Merchants charging the same amount in 2+ distinct calendar months - see the heuristic's
    caveat in dbt/models/marts/mart_subscriptions.sql (not a general subscription detector)."""
    query = """
        select merchant_name, merchant_category, charge_amount, months_charged, charge_count, last_charged_at
        from subscriptions
        order by months_charged desc, charge_amount desc
    """
    return _as_dicts(con.execute(query))


def get_data_quality_report(con: duckdb.DuckDBPyConnection) -> dict:
    """Data quality snapshot computed live from staging/marts - not dependent on stored dbt test
    results (freshness/reconciliation dbt tests aren't built yet). hours_since_last_transaction is
    a proxy for "how recent is the data we have", not "how recently did ingestion last run" -
    the webhook/reconciliation Function isn't deployed yet, so there's no ingestion-run signal to
    report on directly.
    """
    row = con.execute("""
        select
            count(*) as transaction_count,
            count(distinct transaction_id) as distinct_transaction_ids,
            count(distinct account_id) as account_count,
            count(distinct category) as category_count,
            count(distinct merchant_id) as merchant_count,
            sum(case when is_declined then 1 else 0 end) as declined_count,
            min(created_at) as earliest_transaction_at,
            max(created_at) as latest_transaction_at,
            date_diff('hour', max(created_at), current_timestamp) as hours_since_last_transaction
        from staging
    """).fetchone()

    columns = [
        "transaction_count", "distinct_transaction_ids", "account_count", "category_count",
        "merchant_count", "declined_count", "earliest_transaction_at", "latest_transaction_at",
        "hours_since_last_transaction",
    ]
    report = dict(zip(columns, row))

    for key in ("earliest_transaction_at", "latest_transaction_at"):
        if isinstance(report[key], (datetime, date)):
            report[key] = report[key].isoformat()

    report["has_duplicate_transaction_ids"] = report["transaction_count"] != report["distinct_transaction_ids"]
    report["mart_row_counts"] = {
        mart: con.execute(f"select count(*) from {mart}").fetchone()[0] for mart in MARTS
    }
    return report
