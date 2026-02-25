"""Tiered authorisation engine for Wealthgate."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from .models import get_db


BLOCKED_OPERATIONS = {"withdraw", "withdraw_funds", "modify_account", "close_account", "transfer"}

TIER_POLICY = {
    1: {"max_value": 100, "approval": "auto_approved", "description": "Micro-trades auto-approved"},
    2: {"max_value": 5000, "approval": "pending_human_approval", "description": "Standard trades require human approval"},
    3: {"max_value": float("inf"), "approval": "pending_with_cooling", "description": "Large trades require approval + 15min cooling period"},
    4: {"operations": list(BLOCKED_OPERATIONS), "approval": "blocked", "description": "These operations cannot be performed by agents"},
}


@dataclass
class AuthorizationDecision:
    tier: int
    decision: str  # "auto_approved" | "pending_human_approval" | "pending_with_cooling" | "blocked"
    reason: str
    cooling_expires_at: Optional[str] = None


class AuthorizationEngine:
    """Tiered authorisation with human approval gates."""

    async def evaluate(
        self, operation: str, estimated_value: float, agent_id: str
    ) -> AuthorizationDecision:
        if operation in BLOCKED_OPERATIONS:
            return AuthorizationDecision(
                tier=4,
                decision="blocked",
                reason=f"Operation '{operation}' is not available to AI agents. Requires direct human authorisation.",
            )

        if estimated_value < 100:
            return AuthorizationDecision(
                tier=1,
                decision="auto_approved",
                reason=f"Micro-trade (${estimated_value:.2f}) auto-approved. Logged for audit.",
            )

        if estimated_value <= 5000:
            return AuthorizationDecision(
                tier=2,
                decision="pending_human_approval",
                reason=f"Trade value ${estimated_value:,.2f} requires human approval.",
            )

        cooling_expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        return AuthorizationDecision(
            tier=3,
            decision="pending_with_cooling",
            reason=f"Large trade (${estimated_value:,.2f}) requires human approval with 15-minute cooling period.",
            cooling_expires_at=cooling_expires,
        )

    async def submit_for_approval(
        self,
        proposal_id: str,
        agent_id: str,
        agent_name: str,
        account_id: str,
        proposal_type: str,
        action: str,
        symbol: Optional[str],
        units: Optional[int],
        estimated_value: float,
        tier: int,
        reasoning: str,
        trades: Optional[list] = None,
        cooling_expires_at: Optional[str] = None,
    ) -> str:
        db = await get_db()
        try:
            status = "pending"
            if tier == 1:
                status = "auto_approved"
            elif tier == 4:
                status = "blocked"

            trades_json = json.dumps(trades) if trades else None

            await db.execute(
                """INSERT INTO proposals
                   (id, agent_id, agent_name, account_id, type, action, symbol, units,
                    estimated_value, tier, reasoning, status, trades_json, cooling_expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id, agent_id, agent_name, account_id,
                    proposal_type, action, symbol, units,
                    estimated_value, tier, reasoning, status,
                    trades_json, cooling_expires_at,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
        finally:
            await db.close()

        return proposal_id

    async def get_proposal(self, proposal_id: str) -> Optional[dict]:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            result = dict(row)
            if result.get("trades_json"):
                result["trades"] = json.loads(result["trades_json"])
            else:
                result["trades"] = None
            if result.get("modifications_json"):
                result["modifications"] = json.loads(result["modifications_json"])
            else:
                result["modifications"] = None
            return result
        finally:
            await db.close()

    async def approve(
        self,
        proposal_id: str,
        reviewer: str,
        notes: Optional[str] = None,
        modifications: Optional[dict] = None,
    ) -> bool:
        db = await get_db()
        try:
            proposal = await self.get_proposal(proposal_id)
            if not proposal or proposal["status"] != "pending":
                return False

            # Check cooling period for tier 3
            if proposal["tier"] == 3 and proposal.get("cooling_expires_at"):
                cooling_expires = datetime.fromisoformat(proposal["cooling_expires_at"])
                if datetime.now(timezone.utc) < cooling_expires:
                    return False

            mods_json = json.dumps(modifications) if modifications else None
            now = datetime.now(timezone.utc).isoformat()

            await db.execute(
                """UPDATE proposals
                   SET status = 'approved', approved_by = ?, approved_at = ?,
                       modifications_json = ?
                   WHERE id = ?""",
                (reviewer, now, mods_json, proposal_id),
            )
            await db.commit()
            return True
        finally:
            await db.close()

    async def reject(
        self, proposal_id: str, reviewer: str, reason: str
    ) -> bool:
        db = await get_db()
        try:
            proposal = await self.get_proposal(proposal_id)
            if not proposal or proposal["status"] != "pending":
                return False

            await db.execute(
                """UPDATE proposals
                   SET status = 'rejected', rejected_by = ?, rejection_reason = ?
                   WHERE id = ?""",
                (reviewer, reason, proposal_id),
            )
            await db.commit()
            return True
        finally:
            await db.close()

    async def get_all_proposals(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        db = await get_db()
        try:
            if status:
                cursor = await db.execute(
                    "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()

            results = []
            for row in rows:
                r = dict(row)
                if r.get("trades_json"):
                    r["trades"] = json.loads(r["trades_json"])
                else:
                    r["trades"] = None
                if r.get("modifications_json"):
                    r["modifications"] = json.loads(r["modifications_json"])
                else:
                    r["modifications"] = None
                results.append(r)
            return results
        finally:
            await db.close()

    async def mark_executed(
        self, proposal_id: str, execution_price: float
    ) -> bool:
        db = await get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                """UPDATE proposals
                   SET status = 'executed', executed_at = ?, execution_price = ?
                   WHERE id = ? AND status = 'approved'""",
                (now, execution_price, proposal_id),
            )
            await db.commit()
            return db.total_changes > 0
        finally:
            await db.close()


def generate_proposal_id() -> str:
    seq = uuid.uuid4().hex[:5].upper()
    return f"WS-2026-{seq}"
