"""Audit trail logging for Wealthgate."""

import json
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

from .models import get_db


@dataclass
class AuditEntry:
    id: str
    timestamp: str
    agent_id: str
    session_id: str
    tool_name: str
    parameters: dict
    authorization_tier: Optional[int] = None
    authorization_decision: Optional[str] = None
    result_summary: Optional[str] = None
    latency_ms: Optional[int] = None
    proposal_id: Optional[str] = None


class AuditLogger:
    """Logs every MCP tool call to the audit trail."""

    @staticmethod
    async def log(
        agent_id: str,
        session_id: str,
        tool_name: str,
        parameters: dict,
        authorization_tier: Optional[int] = None,
        authorization_decision: Optional[str] = None,
        result_summary: Optional[str] = None,
        latency_ms: Optional[int] = None,
        proposal_id: Optional[str] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=f"AUD-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            session_id=session_id,
            tool_name=tool_name,
            parameters=parameters,
            authorization_tier=authorization_tier,
            authorization_decision=authorization_decision,
            result_summary=result_summary,
            latency_ms=latency_ms,
            proposal_id=proposal_id,
        )

        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO audit_log
                   (id, timestamp, agent_id, session_id, tool_name, parameters_json,
                    authorization_tier, authorization_decision, result_summary,
                    latency_ms, proposal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.timestamp,
                    entry.agent_id,
                    entry.session_id,
                    entry.tool_name,
                    json.dumps(entry.parameters),
                    entry.authorization_tier,
                    entry.authorization_decision,
                    entry.result_summary,
                    entry.latency_ms,
                    entry.proposal_id,
                ),
            )
            await db.commit()
        finally:
            await db.close()

        return entry

    @staticmethod
    async def get_log(
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        db = await get_db()
        try:
            query = "SELECT * FROM audit_log"
            params = []
            conditions = []

            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)
            if agent_id:
                conditions.append("agent_id = ?")
                params.append(agent_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "agent_id": row["agent_id"],
                    "session_id": row["session_id"],
                    "tool_name": row["tool_name"],
                    "parameters": json.loads(row["parameters_json"]),
                    "authorization_tier": row["authorization_tier"],
                    "authorization_decision": row["authorization_decision"],
                    "result_summary": row["result_summary"],
                    "latency_ms": row["latency_ms"],
                    "proposal_id": row["proposal_id"],
                }
                for row in rows
            ]
        finally:
            await db.close()


class AuditTimer:
    """Context manager to measure tool call latency."""

    def __init__(self):
        self.start_time = None
        self.elapsed_ms = 0

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = int((time.monotonic() - self.start_time) * 1000)
