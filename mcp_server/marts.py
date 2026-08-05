"""DuckDB connection over the real staging/marts containers in Blob Storage. Same
credential_chain auth pattern as scripts/query_marts.py - the MCP server runs
locally/on-demand, not as a hosted service, per the spec's MCP section.
"""
import os
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
    return con
