"""MCP server exposing curated queries over the dbt marts, per the spec's MCP section. Runs
locally/on-demand (stdio transport) - launch it via an MCP client config, not as a hosted service.
"""
from mcp.server.mcpserver import MCPServer

from .marts import connect
from .tools import (
    get_data_quality_report as _get_data_quality_report,
    get_monthly_cashflow as _get_monthly_cashflow,
    get_spend_by_category as _get_spend_by_category,
    get_subscriptions as _get_subscriptions,
    get_top_merchants as _get_top_merchants,
)

mcp = MCPServer("monzo-finance")
_con = connect()


@mcp.tool()
def get_spend_by_category(month: str | None = None) -> list[dict]:
    """Spend per category. Pass `month` as "YYYY-MM" to filter to one month, or omit for all months."""
    return _get_spend_by_category(_con, month)


@mcp.tool()
def get_monthly_cashflow(months: int | None = None) -> list[dict]:
    """Income, expenses and net cashflow per calendar month, most recent first. `months` limits how many."""
    return _get_monthly_cashflow(_con, months)


@mcp.tool()
def get_top_merchants(limit: int = 10) -> list[dict]:
    """Highest-spend merchants, excluding declined transactions."""
    return _get_top_merchants(_con, limit)


@mcp.tool()
def get_subscriptions() -> list[dict]:
    """Merchants that look like recurring subscriptions (same charge amount in 2+ distinct months)."""
    return _get_subscriptions(_con)


@mcp.tool()
def get_data_quality_report() -> dict:
    """Snapshot of the underlying data: row counts, date range, freshness, duplicate/decline checks."""
    return _get_data_quality_report(_con)


if __name__ == "__main__":
    mcp.run()
