# Wealthgate

## Overview
Wealthgate is an MCP (Model Context Protocol) server that exposes investment operations to AI agents with tiered authorisation, human approval gates, and audit trails.

## Architecture
- **MCP Server** (`wealthgate/mcp_server.py`) — Python MCP server exposing investment tools to AI agents via FastMCP
- **Approval Dashboard** (`wealthgate/dashboard/`) — FastAPI web UI for humans to review/approve/reject agent trade proposals
- **Database** — SQLite via aiosqlite (auto-created at startup)

## Project Structure
```
main.py                        # Entry point — FastAPI dashboard on port 5000
wealthgate/
  mcp_server.py                # MCP tool definitions for AI agents
  authorization.py             # Tiered authorization engine
  models.py                    # SQLite models and DB setup
  mock_data.py                 # Demo portfolio data
  market_data.py               # yfinance integration with mock fallback
  audit.py                     # Audit trail logging
  dashboard/
    app.py                     # FastAPI routes
    templates/                 # Jinja2 HTML templates
    static/                    # CSS
requirements.txt               # Python dependencies
```

## Tech Stack
- **Python 3.10**
- **FastAPI** + **uvicorn** — web dashboard
- **FastMCP** — MCP server framework
- **aiosqlite** — async SQLite
- **yfinance** — live market data with mock fallback
- **Jinja2** — server-side templating

## Running
- Dashboard runs on port 5000 (`python main.py`)
- MCP server run separately: `fastmcp run wealthgate/mcp_server.py`

## Deployment
- Target: autoscale
- Run: `python main.py`
- Port: 5000

## Authorization Tiers
| Tier | Value | Approval |
|------|-------|----------|
| 1 | Under $100 | Auto-approved |
| 2 | $100–$5,000 | Human required |
| 3 | Over $5,000 | Human + 15-min cooling period |
| 4 | Withdrawals/modifications | Blocked |
