"""FastAPI dashboard for Wealthgate — human approval interface."""

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..authorization import AuthorizationEngine
from ..audit import AuditLogger
from ..models import get_db
from ..mock_data import INVESTMENT_UNIVERSE

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"

auth_engine = AuthorizationEngine()

# ── Symbol name lookup ────────────────────────────────────────────────
_SYMBOL_MAP = {inv["symbol"]: inv["name"] for inv in INVESTMENT_UNIVERSE}


def _format_value(value):
    """Format a number as currency."""
    if value is None:
        return "$0.00"
    return f"${value:,.2f}"


def _tier_label(tier):
    labels = {1: "Tier 1 — Auto", 2: "Tier 2 — Review", 3: "Tier 3 — Cooling", 4: "Tier 4 — Blocked"}
    return labels.get(tier, f"Tier {tier}")


def _status_class(status):
    mapping = {
        "pending": "status-pending",
        "approved": "status-approved",
        "rejected": "status-rejected",
        "executed": "status-executed",
        "blocked": "status-blocked",
        "auto_approved": "status-approved",
    }
    return mapping.get(status, "")


# ── Natural-language transaction names ────────────────────────────────
_TOOL_DISPLAY_NAMES = {
    "withdraw_funds": "Withdraw Funds",
    "propose_rebalance": "Rebalance Portfolio",
    "get_portfolio": "View Portfolio",
    "search_investments": "Search Investments",
    "modify_account": "Modify Account",
    "get_account_summary": "View Account Summary",
    "get_audit_log": "View Audit Log",
    "check_approval_status": "Check Approval Status",
    "execute_approved_trade": "Execute Trade",
}


def _tool_display_name(tool_name, action=None):
    """Convert raw tool_name to natural-language transaction name."""
    if tool_name == "propose_trade":
        if action == "buy":
            return "Buy Stock"
        elif action == "sell":
            return "Sell Stock"
        return "Trade Proposal"
    return _TOOL_DISPLAY_NAMES.get(tool_name, tool_name.replace("_", " ").title())


def _symbol_with_name(symbol):
    """Return 'TD.TO — Toronto-Dominion Bank' format."""
    if not symbol:
        return ""
    name = _SYMBOL_MAP.get(symbol)
    if name:
        return f"{symbol} — {name}"
    return symbol


def _symbol_name(symbol):
    """Return just the company name, e.g. 'Toronto-Dominion Bank'."""
    if not symbol:
        return ""
    return _SYMBOL_MAP.get(symbol, "")


def create_dashboard_app(lifespan=None) -> FastAPI:
    """Factory function to create the dashboard FastAPI app."""
    app = FastAPI(title="Wealthgate Dashboard", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["format_value"] = _format_value
    templates.env.globals["tier_label"] = _tier_label
    templates.env.globals["status_class"] = _status_class
    templates.env.globals["tool_display_name"] = _tool_display_name
    templates.env.globals["symbol_with_name"] = _symbol_with_name
    templates.env.globals["symbol_name"] = _symbol_name

    # -------------------------------------------------------------------
    # Routes
    # -------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    async def proposal_queue(request: Request):
        """AI Agent Orders — pending proposals only."""
        all_proposals = await auth_engine.get_all_proposals(limit=100)

        # Queue shows only actionable (unread) proposals
        pending_proposals = [
            p for p in all_proposals
            if p["status"] in ("pending", "pending_with_cooling")
        ]

        pending = len(pending_proposals)
        total_value = sum(p["estimated_value"] for p in pending_proposals)

        stats = {
            "pending": pending,
            "total_pending_value": total_value,
        }

        return templates.TemplateResponse("queue.html", {
            "request": request,
            "proposals": pending_proposals,
            "stats": stats,
        })

    @app.get("/dashboard/proposal/{proposal_id}", response_class=HTMLResponse)
    async def proposal_detail(request: Request, proposal_id: str):
        """Single proposal detail view."""
        proposal = await auth_engine.get_proposal(proposal_id)
        if not proposal:
            return HTMLResponse("<h1>Proposal not found</h1>", status_code=404)

        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM audit_log WHERE proposal_id = ? ORDER BY timestamp ASC",
                (proposal_id,),
            )
            rows = await cursor.fetchall()
            audit_entries = []
            for row in rows:
                entry = dict(row)
                entry["parameters"] = json.loads(entry["parameters_json"])
                audit_entries.append(entry)
        finally:
            await db.close()

        return templates.TemplateResponse("proposal.html", {
            "request": request,
            "proposal": proposal,
            "audit_entries": audit_entries,
        })

    @app.post("/dashboard/proposal/{proposal_id}/approve")
    async def approve_proposal(
        request: Request,
        proposal_id: str,
        reviewer: str = Form(default="Almir Moura"),
        notes: str = Form(default=""),
        modified_units: Optional[int] = Form(default=None),
    ):
        """Approve a proposal."""
        modifications = None
        if modified_units is not None and modified_units > 0:
            modifications = {"units": modified_units}

        await auth_engine.approve(proposal_id, reviewer, notes, modifications)
        return RedirectResponse(f"/dashboard/proposal/{proposal_id}", status_code=303)

    @app.post("/dashboard/proposal/{proposal_id}/reject")
    async def reject_proposal(
        request: Request,
        proposal_id: str,
        reviewer: str = Form(default="Almir Moura"),
        reason: str = Form(...),
    ):
        """Reject a proposal."""
        await auth_engine.reject(proposal_id, reviewer, reason)
        return RedirectResponse(f"/dashboard/proposal/{proposal_id}", status_code=303)

    @app.get("/dashboard/audit", response_class=HTMLResponse)
    async def activity_page(request: Request):
        """Activity — reviewed proposals + transaction log."""
        entries = await AuditLogger.get_log(limit=100)

        # Fetch resolved proposals for the "Reviewed Orders" section
        all_proposals = await auth_engine.get_all_proposals(limit=100)
        resolved_proposals = [
            p for p in all_proposals
            if p["status"] in ("approved", "rejected", "executed", "blocked", "auto_approved")
        ]

        return templates.TemplateResponse("audit.html", {
            "request": request,
            "entries": entries,
            "resolved_proposals": resolved_proposals,
        })

    @app.get("/dashboard/transcript", response_class=HTMLResponse)
    async def transcript_page(request: Request):
        """Agent session transcript — MCP tool-call replay."""
        from ..mock_data import TRANSCRIPT_ENTRIES
        return templates.TemplateResponse("transcript.html", {
            "request": request,
            "entries": TRANSCRIPT_ENTRIES,
        })

    @app.get("/dashboard/agents", response_class=HTMLResponse)
    async def agents_page(request: Request):
        """Connected agents overview."""
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM agent_sessions ORDER BY last_activity DESC"
            )
            rows = await cursor.fetchall()
            sessions = [dict(row) for row in rows]
        finally:
            await db.close()

        return templates.TemplateResponse("agents.html", {
            "request": request,
            "sessions": sessions,
        })

    return app
