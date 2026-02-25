# Wealthgate

**Making investing programmable for AI agents and accessible to Humans**

## The Problem

Every payments company shipped agent infrastructure in 2025. No brokerage has. When AI agents need to invest on behalf of humans, there's no standardized interface — no discovery protocol, no authorisation tiers, no audit trail. The result is either "AI can't touch investments" or "AI has full access with no guardrails." Neither works.

## What This Is

Wealthgate is an MCP (Model Context Protocol) server that exposes investment operations to any AI agent — Claude, ChatGPT, or custom agents — with tiered authorisation, human approval gates, and regulatory-grade audit trails.

It has two parts:
1. **MCP Server** (Python) — exposes investment tools that AI agents discover and call via MCP protocol
2. **Approval Dashboard** (Web UI) — where humans review agent proposals, approve/reject trades, and see full audit trails

This is not a chatbot. AI agents don't see a UI. They call tools over MCP. Humans see the dashboard.

## Architecture

```
┌─────────────────┐     MCP Protocol      ┌──────────────────────┐
│   AI Agent       │ ◄──── JSON-RPC ────► │   Wealthgate MCP     │
│ (Claude/ChatGPT) │                       │   Server             │
└─────────────────┘                       │                      │
                                          │  Tools:              │
                                          │  - get_portfolio()   │
                                          │  - get_account()     │
                                          │  - search_etfs()     │
                                          │  - propose_trade()   │
                                          │  - propose_rebalance()│
                                          │  - check_approval()  │
                                          │  - execute_trade()   │
                                          │  - get_audit_log()   │
                                          └──────────┬───────────┘
                                                     │
                                                     │ SQLite
                                                     │
                                          ┌──────────▼───────────┐
                                          │  Approval Dashboard   │
                                          │  (FastAPI + HTML)     │
                                          │                      │
                                          │  - Proposal queue     │
                                          │  - Approve/reject     │
                                          │  - Audit trail viewer │
                                          │  - Agent session log  │
                                          └──────────────────────┘
```

## The Three Boundaries

### What AI Does
- Portfolio analysis with live market data
- Trade proposals with detailed reasoning
- Tax-loss harvesting identification
- Rebalancing calculations
- Investment research and screening

### Where AI Stops
- Every trade above $100 requires human approval
- Trades above $5,000 have a mandatory 15-minute cooling period
- Agents must provide reasoning for every proposal
- Humans can modify proposals before approving

### What AI Can't Touch
- Withdrawals — always blocked, requires the Wealthsimple app
- Account modifications — always blocked
- Account closures — always blocked
- No agent can bypass Tier 4 restrictions

## Authorisation Tiers

| Tier | Value | Approval | Description |
|------|-------|----------|-------------|
| 1 | Under $100 | Auto-approved | Micro-trades logged but not gated |
| 2 | $100 – $5,000 | Human required | Queued for human review |
| 3 | Over $5,000 | Human + cooling | 15-minute mandatory cooling period |
| 4 | Withdrawals/modifications | Blocked | Cannot be performed by agents |

## Quick Start

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd WealthGate

# Install dependencies
pip install -r requirements.txt

# Run the dashboard
python main.py
```

The dashboard will be available at `http://localhost:8000`.

### Running the MCP Server (for Claude Desktop)

```bash
# In a separate terminal
cd wealthgate
fastmcp run mcp_server.py
```

### Claude Desktop Configuration

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "wealthgate": {
      "command": "python",
      "args": ["-m", "fastmcp", "run", "wealthgate/mcp_server.py"],
      "env": {}
    }
  }
}
```

## Demo Scenarios

### 1. Portfolio Check + Smart Trade
Ask Claude: "Check my TFSA portfolio" → Claude calls `get_portfolio("TFSA-001")` → shows holdings with live prices → proposes a trade with reasoning → proposal appears in dashboard → human approves → Claude executes.

### 2. Tax-Loss Harvesting
Ask Claude: "Check my non-registered account for tax-loss harvesting opportunities" → Claude analyzes unrealized gains/losses → proposes selling a losing position and buying a similar ETF → reasoning includes superficial loss rule awareness.

### 3. The Blocked Operation
Ask Claude: "Withdraw $5,000 from my TFSA" → Claude gets a BLOCKED response → tells user withdrawals must be done directly in the Wealthsimple app.

### 4. The Thesis Moment — Agent Defers to Human
See proposal PROP-2026-00004 in the dashboard. An agent that flagged market volatility, provided its analysis, but explicitly said "I recommend human review because factors beyond my analysis include personal risk tolerance and upcoming cash needs." The human rejected the panic-sell and noted "Good flag by the agent."

This single proposal tells the entire story of agent-human collaboration.

## Canadian Regulatory Context

This design satisfies key requirements from:
- **CSA Notice 11-348** (Artificial Intelligence in Capital Markets) — auditability of AI decision-making, human oversight of material trading decisions
- **OSFI E-23** (Model Risk Management) — tiered authorisation controls, model output validation through human review, complete audit trails

## Project Structure

```
wealthgate/
├── main.py                    # Entry point — runs FastAPI dashboard
├── wealthgate/
│   ├── mcp_server.py          # All MCP tool definitions
│   ├── authorization.py       # Tiered authorisation engine
│   ├── models.py              # SQLite models and database setup
│   ├── mock_data.py           # Realistic Canadian portfolio data
│   ├── market_data.py         # yfinance integration with mock fallback
│   ├── audit.py               # Audit trail logging
│   └── dashboard/
│       ├── app.py             # FastAPI routes for dashboard
│       ├── templates/         # Jinja2 HTML templates
│       │   ├── base.html
│       │   ├── queue.html
│       │   ├── proposal.html
│       │   ├── audit.html
│       │   └── agents.html
│       └── static/
│           └── style.css      # Wealthsimple-inspired design
├── requirements.txt
├── Procfile
└── README.md
```

## Built With

- **Claude Code** — AI-assisted development
- **FastMCP** — MCP server framework for Python
- **FastAPI** — Web dashboard framework
- **yfinance** — Live TSX/NYSE market data
- **SQLite** — Embedded database for proposals and audit trails
- **Jinja2** — Server-side HTML templating
