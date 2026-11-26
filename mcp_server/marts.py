"""DuckDB connection over the real staging/marts containers in Blob Storage. Same
credential_chain auth pattern as scripts/query_marts.py - the MCP server runs
locally/on-demand, not as a hosted service, per the spec's MCP section.
"""
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MARTS = ["spend_by_category", "monthly_cashflow", "merchant_summary", "subscriptions"]


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("install azure; load azure;")
    con.execute(f"""
        create secret (
            type azure, provider credential_chain, chain 'cli',
            account_name '{os.environ["STORAGE_ACCOUNT_NAME"]}'
        )
    """)
    for mart in MARTS:
        con.execute(f"create view {mart} as select * from read_parquet('az://marts/{mart}.parquet')")
    # Per-transaction data (not aggregated like the marts) - used by get_data_quality_report.
    con.execute("create view staging as select * from read_parquet('az://staging/**/*.parquet')")
    # Serving dataset for the transaction-level tools (transaction_tools.py) - the only table they
    # read, built with exactly the columns they may return (dbt/models/marts/mcp_transactions.sql).
    # Created last and tolerated if missing: DuckDB binds a view at creation, so a not-yet-published
    # file would otherwise stop the whole server, the five mart tools included. The transaction
    # tools then fail with "Table ... does not exist" until dbt has written it.
    try:
        con.execute("create view mcp_transactions as select * from read_parquet('az://marts/mcp_transactions.parquet')")
    except duckdb.Error as exc:
        print(f"mcp_transactions unavailable, transaction tools disabled: {exc}", file=sys.stderr)
    return con
