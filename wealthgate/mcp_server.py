"""Wealthgate MCP Server — Agent-native investment infrastructure."""

import json
from typing import Optional

from fastmcp import FastMCP

from .mock_data import CLIENTS, INVESTMENT_UNIVERSE
from .market_data import get_price, get_prices
from .authorization import AuthorizationEngine, BLOCKED_OPERATIONS, generate_proposal_id
from .audit import AuditLogger, AuditTimer

mcp = FastMCP(
    "Wealthgate",
    instructions=(
        "Agent-native investment infrastructure. Exposes portfolio management, "
        "trade proposals, and account operations for AI agents with tiered "
        "authorisation and human approval gates."
    ),
)

auth_engine = AuthorizationEngine()


# ---------------------------------------------------------------------------
# Helper: resolve account from mock data
# ---------------------------------------------------------------------------

def _find_account(account_id: str) -> tuple[Optional[str], Optional[dict]]:
    """Return (client_id, account_data) or (None, None)."""
    for client_id, client in CLIENTS.items():
        if account_id in client["accounts"]:
            return client_id, client["accounts"][account_id]
    return None, None


# ---------------------------------------------------------------------------
# MCP Resources (read-only data)
# ---------------------------------------------------------------------------

@mcp.resource("wealthgate://authorization-policy")
def get_authorization_policy() -> dict:
    """Returns the current authorisation tier policy so agents understand their boundaries."""
    return {
        "tiers": {
            "1": {"max_value": 100, "approval": "auto", "description": "Micro-trades auto-approved"},
            "2": {"max_value": 5000, "approval": "human_required", "description": "Standard trades require human approval"},
            "3": {"max_value": "unlimited", "approval": "human_required_with_cooling", "description": "Large trades require approval + 15min cooling period"},
            "4": {
                "operations": ["withdraw", "modify_account", "close_account"],
                "approval": "blocked",
                "description": "These operations cannot be performed by agents",
            },
        },
        "audit": "All operations are logged with agent identity, reasoning, and authorisation decision",
    }


@mcp.resource("wealthgate://supported-accounts")
def get_supported_accounts() -> dict:
    """Canadian account types supported."""
    return {
        "TFSA": {"description": "Tax-Free Savings Account", "contribution_limit_2026": 7000},
        "RRSP": {"description": "Registered Retirement Savings Plan"},
        "FHSA": {"description": "First Home Savings Account", "annual_limit": 8000},
        "Non-Registered": {"description": "Taxable investment account"},
    }


# ---------------------------------------------------------------------------
# READ-ONLY TOOLS (Tier 0)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_portfolio(account_id: str, agent_id: str = "anonymous", session_id: str = "default") -> dict:
    """Get current portfolio holdings with live market prices for a given account.

    Returns holdings, cash balance, performance metrics, and portfolio weights.
    This is a read-only operation (Tier 0) — always allowed.

    Args:
        account_id: The account identifier (e.g., "TFSA-001", "RRSP-001")
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        client_id, account = _find_account(account_id)
        if not account:
            result = {"error": "NOT_FOUND", "message": f"Account '{account_id}' not found."}
            await AuditLogger.log(
                agent_id=agent_id, session_id=session_id,
                tool_name="get_portfolio", parameters={"account_id": account_id},
                authorization_tier=0, authorization_decision="auto_approved",
                result_summary="Account not found", latency_ms=timer.elapsed_ms,
            )
            return result

        symbols = [h["symbol"] for h in account["holdings"]]
        prices = await get_prices(symbols)

        holdings = []
        total_market_value = account["cash"]
        total_cost = 0

        for h in account["holdings"]:
            current_price = prices.get(h["symbol"], 0)
            market_value = round(current_price * h["units"], 2)
            cost_basis = round(h["avg_cost"] * h["units"], 2)
            gain_loss = round(market_value - cost_basis, 2)
            gain_loss_pct = round((gain_loss / cost_basis * 100), 2) if cost_basis > 0 else 0

            total_market_value += market_value
            total_cost += cost_basis

            holdings.append({
                "symbol": h["symbol"],
                "name": _get_investment_name(h["symbol"]),
                "units": h["units"],
                "avg_cost": h["avg_cost"],
                "current_price": current_price,
                "market_value": market_value,
                "gain_loss": gain_loss,
                "gain_loss_pct": gain_loss_pct,
                "weight": 0,  # calculated below
            })

        # Calculate weights
        for holding in holdings:
            holding["weight"] = round(holding["market_value"] / total_market_value * 100, 2) if total_market_value > 0 else 0

        total_gain = round(total_market_value - total_cost - account["cash"], 2)
        total_gain_pct = round(total_gain / total_cost * 100, 2) if total_cost > 0 else 0

        result = {
            "account_id": account_id,
            "account_type": account["type"],
            "total_value": round(total_market_value, 2),
            "cash_available": account["cash"],
            "holdings": holdings,
            "performance": {
                "total_gain": total_gain,
                "total_gain_pct": total_gain_pct,
            },
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="get_portfolio", parameters={"account_id": account_id},
        authorization_tier=0, authorization_decision="auto_approved",
        result_summary=f"Returned portfolio with {len(holdings)} holdings, value ${total_market_value:,.2f}",
        latency_ms=timer.elapsed_ms,
    )
    return result


@mcp.tool()
async def get_account_summary(client_id: str, agent_id: str = "anonymous", session_id: str = "default") -> dict:
    """Get all accounts and total value for a client.

    Returns a summary of all investment accounts including TFSA, RRSP,
    and non-registered accounts with contribution room details.

    Args:
        client_id: The client identifier (e.g., "CLI-001")
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        client = CLIENTS.get(client_id)
        if not client:
            return {"error": "NOT_FOUND", "message": f"Client '{client_id}' not found."}

        accounts_summary = []
        total_value = 0

        for acct_id, acct in client["accounts"].items():
            symbols = [h["symbol"] for h in acct["holdings"]]
            prices = await get_prices(symbols)

            acct_value = acct["cash"]
            for h in acct["holdings"]:
                acct_value += prices.get(h["symbol"], 0) * h["units"]

            acct_value = round(acct_value, 2)
            total_value += acct_value

            entry = {"id": acct_id, "type": acct["type"], "value": acct_value}
            if "contribution_room" in acct:
                entry["contribution_room"] = acct["contribution_room"]
            if "deduction_limit" in acct:
                entry["deduction_limit"] = acct["deduction_limit"]

            accounts_summary.append(entry)

        result = {
            "client_id": client_id,
            "client_name": client["name"],
            "accounts": accounts_summary,
            "total_value": round(total_value, 2),
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="get_account_summary", parameters={"client_id": client_id},
        authorization_tier=0, authorization_decision="auto_approved",
        result_summary=f"Returned {len(accounts_summary)} accounts, total ${total_value:,.2f}",
        latency_ms=timer.elapsed_ms,
    )
    return result


@mcp.tool()
async def search_investments(
    query: str,
    filters: Optional[dict] = None,
    agent_id: str = "anonymous",
    session_id: str = "default",
) -> list[dict]:
    """Search available ETFs and stocks for investment.

    Searches the supported investment universe by name, symbol, category,
    or type. Returns current prices for matching investments.

    Args:
        query: Search term (e.g., "equity", "bond", "Shopify", "XEQT")
        filters: Optional filters — {"type": "ETF"|"Stock", "category": "..."}
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        query_lower = query.lower()
        results = []

        for inv in INVESTMENT_UNIVERSE:
            searchable = f"{inv['symbol']} {inv['name']} {inv.get('category', '')} {inv.get('description', '')}".lower()
            if query_lower not in searchable:
                continue

            if filters:
                if "type" in filters and inv["type"].lower() != filters["type"].lower():
                    continue
                if "category" in filters and filters["category"].lower() not in inv.get("category", "").lower():
                    continue

            price = await get_price(inv["symbol"])

            entry = {
                "symbol": inv["symbol"],
                "name": inv["name"],
                "type": inv["type"],
                "price": price,
                "category": inv.get("category", ""),
                "description": inv.get("description", ""),
            }
            if "mer" in inv:
                entry["mer"] = inv["mer"]
            results.append(entry)

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="search_investments",
        parameters={"query": query, "filters": filters},
        authorization_tier=0, authorization_decision="auto_approved",
        result_summary=f"Returned {len(results)} matching investments",
        latency_ms=timer.elapsed_ms,
    )
    return results


@mcp.tool()
async def get_audit_log(
    session_id: str = None,
    agent_id_filter: str = None,
    limit: int = 50,
    agent_id: str = "anonymous",
    session_id_self: str = "default",
) -> list[dict]:
    """Retrieve the audit trail of all MCP operations.

    Returns a chronological log of all tool calls made by agents,
    including parameters, authorisation decisions, and outcomes.

    Args:
        session_id: Filter by a specific session ID
        agent_id_filter: Filter by a specific agent ID
        limit: Maximum number of entries to return (default 50)
        agent_id: Identity of the calling agent
        session_id_self: Agent session tracking ID
    """
    with AuditTimer() as timer:
        entries = await AuditLogger.get_log(
            session_id=session_id,
            agent_id=agent_id_filter,
            limit=limit,
        )

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id_self,
        tool_name="get_audit_log",
        parameters={"session_id": session_id, "agent_id_filter": agent_id_filter, "limit": limit},
        authorization_tier=0, authorization_decision="auto_approved",
        result_summary=f"Returned {len(entries)} audit entries",
        latency_ms=timer.elapsed_ms,
    )
    return entries


# ---------------------------------------------------------------------------
# WRITE TOOLS (Tiered Authorisation)
# ---------------------------------------------------------------------------

@mcp.tool()
async def propose_trade(
    account_id: str,
    action: str,
    symbol: str,
    units: int,
    reasoning: str,
    agent_id: str = "anonymous",
    agent_name: str = "Unknown Agent",
    session_id: str = "default",
) -> dict:
    """Propose a trade for human review. Does NOT execute the trade.

    Creates a trade proposal that enters the authorisation pipeline.
    Small trades (<$100) are auto-approved. Larger trades require human
    approval through the dashboard. The reasoning parameter is critical —
    explain WHY you are proposing this trade.

    Args:
        account_id: Target account (e.g., "TFSA-001")
        action: "buy" or "sell"
        symbol: Ticker symbol (e.g., "XEQT.TO")
        units: Number of units to trade
        reasoning: Detailed explanation of why this trade is proposed
        agent_id: Identity of the calling agent
        agent_name: Display name of the agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        # Validate inputs
        if action not in ("buy", "sell"):
            return {"error": "INVALID_ACTION", "message": "Action must be 'buy' or 'sell'."}

        client_id, account = _find_account(account_id)
        if not account:
            return {"error": "NOT_FOUND", "message": f"Account '{account_id}' not found."}

        # Get current price
        price = await get_price(symbol)
        if price <= 0:
            return {"error": "PRICE_UNAVAILABLE", "message": f"Cannot determine price for {symbol}."}

        estimated_value = round(price * units, 2)

        # Check authorization
        decision = await auth_engine.evaluate("trade", estimated_value, agent_id)

        proposal_id = generate_proposal_id()

        await auth_engine.submit_for_approval(
            proposal_id=proposal_id,
            agent_id=agent_id,
            agent_name=agent_name,
            account_id=account_id,
            proposal_type="trade",
            action=action,
            symbol=symbol,
            units=units,
            estimated_value=estimated_value,
            tier=decision.tier,
            reasoning=reasoning,
            cooling_expires_at=decision.cooling_expires_at,
        )

        result = {
            "proposal_id": proposal_id,
            "status": decision.decision,
            "authorization_tier": decision.tier,
            "estimated_value": estimated_value,
            "estimated_price": price,
            "requires_human_approval": decision.tier >= 2,
            "message": f"Trade proposal created. Estimated value ${estimated_value:,.2f}. "
                       f"{decision.reason} Use check_approval_status() to monitor.",
        }
        if decision.cooling_expires_at:
            result["cooling_expires_at"] = decision.cooling_expires_at

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="propose_trade",
        parameters={"account_id": account_id, "action": action, "symbol": symbol, "units": units, "reasoning": reasoning},
        authorization_tier=decision.tier,
        authorization_decision=decision.decision,
        result_summary=f"Trade proposal {proposal_id}: {action} {units} {symbol} (${estimated_value:,.2f})",
        latency_ms=timer.elapsed_ms,
        proposal_id=proposal_id,
    )
    return result


@mcp.tool()
async def propose_rebalance(
    account_id: str,
    target_allocation: dict,
    reasoning: str,
    agent_id: str = "anonymous",
    agent_name: str = "Unknown Agent",
    session_id: str = "default",
) -> dict:
    """Propose a multi-trade rebalance to reach a target allocation.

    Analyses current holdings vs. target allocation and generates the
    necessary buy/sell trades. The entire batch is submitted as one proposal.

    Args:
        account_id: Target account (e.g., "RRSP-001")
        target_allocation: Target allocation as {symbol: weight_pct} e.g., {"VEQT.TO": 60, "ZAG.TO": 40}
        reasoning: Detailed explanation of why this rebalance is proposed
        agent_id: Identity of the calling agent
        agent_name: Display name of the agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        client_id, account = _find_account(account_id)
        if not account:
            return {"error": "NOT_FOUND", "message": f"Account '{account_id}' not found."}

        # Get current portfolio value
        symbols = list(set(
            [h["symbol"] for h in account["holdings"]] + list(target_allocation.keys())
        ))
        prices = await get_prices(symbols)

        total_value = account["cash"]
        for h in account["holdings"]:
            total_value += prices.get(h["symbol"], 0) * h["units"]

        # Calculate required trades
        current_holdings = {h["symbol"]: h["units"] for h in account["holdings"]}
        trades = []
        total_trade_value = 0

        for symbol, target_pct in target_allocation.items():
            price = prices.get(symbol, 0)
            if price <= 0:
                continue

            target_value = total_value * (target_pct / 100)
            current_units = current_holdings.get(symbol, 0)
            current_value = current_units * price
            diff_value = target_value - current_value

            if abs(diff_value) < 50:  # skip tiny adjustments
                continue

            diff_units = int(diff_value / price)
            if diff_units == 0:
                continue

            trade_action = "buy" if diff_units > 0 else "sell"
            trade_units = abs(diff_units)
            trade_value = round(trade_units * price, 2)
            total_trade_value += trade_value

            trades.append({
                "action": trade_action,
                "symbol": symbol,
                "units": trade_units,
                "est_value": trade_value,
            })

        # Also check for sells of holdings not in target
        for symbol, units in current_holdings.items():
            if symbol not in target_allocation:
                price = prices.get(symbol, 0)
                trade_value = round(units * price, 2)
                total_trade_value += trade_value
                trades.append({
                    "action": "sell",
                    "symbol": symbol,
                    "units": units,
                    "est_value": trade_value,
                })

        if not trades:
            return {
                "message": "Portfolio is already aligned with target allocation. No trades needed.",
                "account_id": account_id,
            }

        # Authorization
        decision = await auth_engine.evaluate("rebalance", total_trade_value, agent_id)

        proposal_id = generate_proposal_id()

        await auth_engine.submit_for_approval(
            proposal_id=proposal_id,
            agent_id=agent_id,
            agent_name=agent_name,
            account_id=account_id,
            proposal_type="rebalance",
            action="rebalance",
            symbol=None,
            units=None,
            estimated_value=total_trade_value,
            tier=decision.tier,
            reasoning=reasoning,
            trades=trades,
            cooling_expires_at=decision.cooling_expires_at,
        )

        result = {
            "proposal_id": proposal_id,
            "type": "rebalance",
            "status": decision.decision,
            "authorization_tier": decision.tier,
            "trades": trades,
            "total_value": round(total_trade_value, 2),
            "requires_human_approval": decision.tier >= 2,
            "message": f"Rebalance proposal created with {len(trades)} trades. "
                       f"Total value ${total_trade_value:,.2f}. {decision.reason}",
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="propose_rebalance",
        parameters={"account_id": account_id, "target_allocation": target_allocation, "reasoning": reasoning},
        authorization_tier=decision.tier,
        authorization_decision=decision.decision,
        result_summary=f"Rebalance proposal {proposal_id}: {len(trades)} trades (${total_trade_value:,.2f})",
        latency_ms=timer.elapsed_ms,
        proposal_id=proposal_id,
    )
    return result


@mcp.tool()
async def check_approval_status(
    proposal_id: str,
    agent_id: str = "anonymous",
    session_id: str = "default",
) -> dict:
    """Check the approval status of a trade proposal.

    Poll this tool to see if a proposal has been approved, rejected,
    or is still pending human review.

    Args:
        proposal_id: The proposal ID returned by propose_trade or propose_rebalance
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        proposal = await auth_engine.get_proposal(proposal_id)
        if not proposal:
            return {"error": "NOT_FOUND", "message": f"Proposal '{proposal_id}' not found."}

        result = {
            "proposal_id": proposal_id,
            "status": proposal["status"],
        }

        if proposal["status"] == "approved":
            result["approved_by"] = proposal.get("approved_by")
            result["approved_at"] = proposal.get("approved_at")
            result["modifications"] = proposal.get("modifications")
        elif proposal["status"] == "rejected":
            result["rejected_by"] = proposal.get("rejected_by")
            result["rejection_reason"] = proposal.get("rejection_reason")
        elif proposal["status"] == "blocked":
            result["block_reason"] = proposal.get("block_reason")
        elif proposal["status"] == "pending" and proposal.get("cooling_expires_at"):
            result["cooling_expires_at"] = proposal["cooling_expires_at"]

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="check_approval_status",
        parameters={"proposal_id": proposal_id},
        authorization_tier=0, authorization_decision="auto_approved",
        result_summary=f"Proposal {proposal_id} status: {proposal['status']}",
        latency_ms=timer.elapsed_ms,
        proposal_id=proposal_id,
    )
    return result


@mcp.tool()
async def execute_approved_trade(
    proposal_id: str,
    agent_id: str = "anonymous",
    session_id: str = "default",
) -> dict:
    """Execute a trade that has been approved by a human reviewer.

    This tool ONLY works for proposals with status "approved".
    Returns an error for pending, rejected, or blocked proposals.

    Args:
        proposal_id: The approved proposal ID
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        proposal = await auth_engine.get_proposal(proposal_id)
        if not proposal:
            return {"error": "NOT_FOUND", "message": f"Proposal '{proposal_id}' not found."}

        if proposal["status"] != "approved":
            return {
                "error": "NOT_APPROVED",
                "message": f"Proposal '{proposal_id}' has status '{proposal['status']}'. Only approved proposals can be executed.",
                "current_status": proposal["status"],
            }

        # Simulate execution with current price
        if proposal.get("symbol"):
            execution_price = await get_price(proposal["symbol"])
            total_cost = round(execution_price * (proposal.get("units") or 0), 2)
            confirmation = f"{proposal.get('units')} units of {proposal['symbol']} {proposal['action']}ed in {proposal['account_id']}"
        else:
            # Rebalance — use estimated value
            execution_price = 0
            total_cost = proposal["estimated_value"]
            confirmation = f"Rebalance executed in {proposal['account_id']} with {len(proposal.get('trades') or [])} trades"

        await auth_engine.mark_executed(proposal_id, execution_price)

        result = {
            "proposal_id": proposal_id,
            "status": "executed",
            "execution_price": execution_price,
            "total_cost": total_cost,
            "executed_at": proposal.get("executed_at") or "now",
            "confirmation": confirmation,
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="execute_approved_trade",
        parameters={"proposal_id": proposal_id},
        authorization_tier=proposal["tier"],
        authorization_decision="executed",
        result_summary=f"Executed {proposal_id}: {confirmation}",
        latency_ms=timer.elapsed_ms,
        proposal_id=proposal_id,
    )
    return result


# ---------------------------------------------------------------------------
# BLOCKED OPERATIONS (Tier 4)
# ---------------------------------------------------------------------------

@mcp.tool()
async def withdraw_funds(
    account_id: str,
    amount: float,
    destination: str = "",
    agent_id: str = "anonymous",
    session_id: str = "default",
) -> dict:
    """Withdraw funds from an account. BLOCKED for AI agents.

    This operation is restricted to Tier 4 and cannot be performed
    by AI agents. Withdrawals require direct human authorisation
    through the Wealthsimple app.

    Args:
        account_id: The account to withdraw from
        amount: Amount to withdraw
        destination: Destination account description
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        result = {
            "error": "BLOCKED",
            "message": "Withdrawal operations are not available to AI agents. "
                       "This action requires direct human authorisation through the Wealthsimple app.",
            "authorization_tier": 4,
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="withdraw_funds",
        parameters={"account_id": account_id, "amount": amount, "destination": destination},
        authorization_tier=4, authorization_decision="blocked",
        result_summary="BLOCKED: Withdrawal operations not available to AI agents",
        latency_ms=timer.elapsed_ms,
    )
    return result


@mcp.tool()
async def modify_account(
    account_id: str,
    modifications: dict,
    agent_id: str = "anonymous",
    session_id: str = "default",
) -> dict:
    """Modify account settings. BLOCKED for AI agents.

    Account modifications are restricted to Tier 4 and cannot be
    performed by AI agents. These changes require direct human
    authorisation through the Wealthsimple app.

    Args:
        account_id: The account to modify
        modifications: Requested changes
        agent_id: Identity of the calling agent
        session_id: Agent session tracking ID
    """
    with AuditTimer() as timer:
        result = {
            "error": "BLOCKED",
            "message": "Account modification operations are not available to AI agents. "
                       "This action requires direct human authorisation through the Wealthsimple app.",
            "authorization_tier": 4,
        }

    await AuditLogger.log(
        agent_id=agent_id, session_id=session_id,
        tool_name="modify_account",
        parameters={"account_id": account_id, "modifications": modifications},
        authorization_tier=4, authorization_decision="blocked",
        result_summary="BLOCKED: Account modification not available to AI agents",
        latency_ms=timer.elapsed_ms,
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_investment_name(symbol: str) -> str:
    """Get the display name for a symbol."""
    for inv in INVESTMENT_UNIVERSE:
        if inv["symbol"] == symbol:
            return inv["name"]
    return symbol
