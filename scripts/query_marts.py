"""Query the curated dbt marts straight from Blob Storage. Stopgap for the not-yet-built MCP
server (see the spec's MCP section) - same read-only view onto marts/ a future MCP tool would
expose, just from the command line for now. Manual/local only, not invoked by CI.

Usage:
    python scripts/query_marts.py                                  # show all 4 marts
    python scripts/query_marts.py "select * from subscriptions"    # run your own SQL
"""
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

# duckdb's .show() renders table borders with box-drawing characters that Windows consoles'
# default cp1252 stdout encoding can't represent.
sys.stdout.reconfigure(encoding="utf-8")

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
    return con


def main():
    con = connect()

    if len(sys.argv) > 1:
        con.sql(sys.argv[1]).show(max_rows=100)
        return

    for mart in MARTS:
        print(f"\n=== {mart} ===")
        con.sql(f"select * from {mart}").show(max_rows=20)


if __name__ == "__main__":
    main()
