"""Tests tools.py's query logic against an in-memory DuckDB with fixture data - no real
Azure/Blob Storage access needed. See mcp_server/marts.py for the real connection.
"""
import duckdb
import pytest

from mcp_server.tools import (
    get_data_quality_report,
    get_monthly_cashflow,
    get_spend_by_category,
    get_subscriptions,
    get_top_merchants,
)


@pytest.fixture
def con():
    con = duckdb.connect()

    con.execute("""
        create table spend_by_category (
            transaction_month timestamp, category varchar, category_label varchar,
            total_spend double, transaction_count bigint
        )
    """)
    con.execute("""
        insert into spend_by_category values
            ('2026-01-01', 'groceries', 'Groceries', 100.0, 5),
            ('2026-01-01', 'eating_out', 'Eating out', 50.0, 3),
            ('2026-02-01', 'groceries', 'Groceries', 80.0, 4)
    """)

    con.execute("create table monthly_cashflow (transaction_month timestamp, income double, expenses double, net double)")
    con.execute("""
        insert into monthly_cashflow values
            ('2026-01-01', 2000.0, 500.0, 1500.0),
            ('2026-02-01', 2000.0, 600.0, 1400.0),
            ('2026-03-01', 2000.0, 700.0, 1300.0)
    """)

    con.execute("""
        create table merchant_summary (
            merchant_id varchar, merchant_name varchar, merchant_category varchar,
            total_spend double, transaction_count bigint, avg_transaction_amount double,
            first_transaction_at timestamp, last_transaction_at timestamp
        )
    """)
    con.execute("""
        insert into merchant_summary values
            ('merch_1', 'Tesco', 'groceries', 300.0, 10, 30.0, '2026-01-05', '2026-02-20'),
            ('merch_2', 'Netflix', 'entertainment', 30.0, 3, 10.0, '2026-01-05', '2026-03-05')
    """)

    con.execute("""
        create table subscriptions (
            merchant_id varchar, merchant_name varchar, merchant_category varchar,
            charge_amount double, months_charged bigint, charge_count bigint,
            first_charged_at timestamp, last_charged_at timestamp
        )
    """)
    con.execute("""
        insert into subscriptions values
            ('merch_2', 'Netflix', 'entertainment', 9.99, 3, 3, '2026-01-05', '2026-03-05')
    """)

    con.execute("""
        create table staging (
            transaction_id varchar, account_id varchar, merchant_id varchar,
            category varchar, created_at timestamp, is_declined boolean
        )
    """)
    con.execute("""
        insert into staging values
            ('tx_1', 'acc_1', 'merch_1', 'groceries', '2026-01-05 10:00:00', false),
            ('tx_2', 'acc_1', 'merch_2', 'entertainment', '2026-03-05 08:00:00', false),
            ('tx_3', 'acc_1', null, 'shopping', '2026-02-01 09:00:00', true)
    """)

    return con


def test_get_spend_by_category_returns_all_months_by_default(con):
    rows = get_spend_by_category(con)
    assert len(rows) == 3


def test_get_spend_by_category_filters_by_month(con):
    rows = get_spend_by_category(con, month="2026-02")
    assert len(rows) == 1
    assert rows[0]["category"] == "groceries"
    assert rows[0]["total_spend"] == 80.0


def test_get_monthly_cashflow_most_recent_first(con):
    rows = get_monthly_cashflow(con)
    assert [r["transaction_month"] for r in rows] == [
        "2026-03-01T00:00:00", "2026-02-01T00:00:00", "2026-01-01T00:00:00",
    ]


def test_get_monthly_cashflow_respects_months_limit(con):
    rows = get_monthly_cashflow(con, months=2)
    assert len(rows) == 2
    assert rows[0]["transaction_month"] == "2026-03-01T00:00:00"


def test_get_top_merchants_orders_by_spend_desc(con):
    rows = get_top_merchants(con, limit=1)
    assert len(rows) == 1
    assert rows[0]["merchant_name"] == "Tesco"


def test_get_subscriptions_returns_recurring_merchants(con):
    rows = get_subscriptions(con)
    assert len(rows) == 1
    assert rows[0]["merchant_name"] == "Netflix"


def test_get_data_quality_report_counts_and_flags(con):
    report = get_data_quality_report(con)
    assert report["transaction_count"] == 3
    assert report["declined_count"] == 1
    assert report["account_count"] == 1
    assert report["has_duplicate_transaction_ids"] is False
    assert report["mart_row_counts"]["subscriptions"] == 1


def test_get_data_quality_report_flags_duplicate_transaction_ids(con):
    con.execute(
        "insert into staging values ('tx_1', 'acc_1', 'merch_1', 'groceries', '2026-01-06 10:00:00', false)"
    )
    report = get_data_quality_report(con)
    assert report["transaction_count"] == 4
    assert report["distinct_transaction_ids"] == 3
    assert report["has_duplicate_transaction_ids"] is True
