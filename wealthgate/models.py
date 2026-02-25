"""SQLite models and database setup for Wealthgate."""

import aiosqlite
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "wealthgate.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                account_id TEXT NOT NULL,
                type TEXT NOT NULL,
                action TEXT NOT NULL,
                symbol TEXT,
                units INTEGER,
                estimated_value REAL NOT NULL,
                tier INTEGER NOT NULL,
                reasoning TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                trades_json TEXT,
                approved_by TEXT,
                approved_at TEXT,
                rejected_by TEXT,
                rejection_reason TEXT,
                block_reason TEXT,
                modifications_json TEXT,
                executed_at TEXT,
                execution_price REAL,
                cooling_expires_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                authorization_tier INTEGER,
                authorization_decision TEXT,
                result_summary TEXT,
                latency_ms INTEGER,
                proposal_id TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                connected_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                operations_count INTEGER DEFAULT 0,
                tier1_count INTEGER DEFAULT 0,
                tier2_count INTEGER DEFAULT 0,
                tier3_count INTEGER DEFAULT 0,
                tier4_count INTEGER DEFAULT 0,
                blocked_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
            CREATE INDEX IF NOT EXISTS idx_proposals_account ON proposals(account_id);
            CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
            CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        """)
        await db.commit()
    finally:
        await db.close()


async def seed_db():
    """Seed the database with demo proposals if empty."""
    from .mock_data import SEED_PROPOSALS

    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM proposals")
        row = await cursor.fetchone()
        if row[0] > 0:
            return

        import json
        for p in SEED_PROPOSALS:
            trades_json = json.dumps(p.get("trades")) if p.get("trades") else None
            await db.execute(
                """INSERT INTO proposals
                   (id, agent_id, agent_name, account_id, type, action, symbol, units,
                    estimated_value, tier, reasoning, status, trades_json,
                    approved_by, approved_at, rejected_by, rejection_reason,
                    block_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["id"], p["agent_id"], p["agent_name"], p["account_id"],
                    p["type"], p["action"], p.get("symbol"), p.get("units"),
                    p["estimated_value"], p["tier"], p["reasoning"], p["status"],
                    trades_json,
                    p.get("approved_by"), p.get("approved_at"),
                    p.get("rejected_by"), p.get("rejection_reason"),
                    p.get("block_reason"), p["created_at"]
                ),
            )

        # Seed some audit log entries for the demo
        now = datetime.now(timezone.utc).isoformat()
        audit_entries = [
            ("AUD-001", "2026-02-24T10:15:00Z", "claude-financial-advisor", "sess-001",
             "get_portfolio", '{"account_id": "TFSA-001"}', 0, "auto_approved",
             "Returned portfolio with 4 holdings", 45, None),
            ("AUD-002", "2026-02-24T10:15:30Z", "claude-financial-advisor", "sess-001",
             "search_investments", '{"query": "equity ETF"}', 0, "auto_approved",
             "Returned 6 matching investments", 32, None),
            ("AUD-003", "2026-02-24T10:16:00Z", "claude-financial-advisor", "sess-001",
             "propose_trade", '{"account_id": "TFSA-001", "action": "buy", "symbol": "XEQT.TO", "units": 50}',
             2, "pending_human_approval", "Trade proposal created: WS-2026-00001", 78, "WS-2026-00001"),
            ("AUD-004", "2026-02-24T10:30:00Z", "chatgpt-portfolio-manager", "sess-002",
             "propose_rebalance", '{"account_id": "RRSP-001"}',
             3, "pending_with_cooling", "Rebalance proposal created: WS-2026-00002", 120, "WS-2026-00002"),
            ("AUD-005", "2026-02-24T11:30:00Z", "chatgpt-portfolio-manager", "sess-002",
             "withdraw_funds", '{"account_id": "TFSA-001", "amount": 5000}',
             4, "blocked", "BLOCKED: Withdrawal operations not available to AI agents", 5, "WS-2026-00005"),
        ]
        for entry in audit_entries:
            await db.execute(
                """INSERT INTO audit_log
                   (id, timestamp, agent_id, session_id, tool_name, parameters_json,
                    authorization_tier, authorization_decision, result_summary,
                    latency_ms, proposal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                entry,
            )

        # Seed agent sessions
        sessions = [
            ("sess-001", "claude-financial-advisor", "Claude (Financial Advisor)",
             "2026-02-24T10:00:00Z", "2026-02-24T11:00:00Z", 5, 2, 1, 1, 0, 0),
            ("sess-002", "chatgpt-portfolio-manager", "ChatGPT (Portfolio Rebalancer)",
             "2026-02-24T10:25:00Z", "2026-02-24T11:30:00Z", 4, 1, 1, 1, 0, 1),
            ("sess-003", "claude-tax-optimizer", "Claude (Tax Optimizer)",
             "2026-02-24T10:55:00Z", "2026-02-24T11:05:00Z", 2, 1, 1, 0, 0, 0),
        ]
        for s in sessions:
            await db.execute(
                """INSERT INTO agent_sessions
                   (id, agent_id, agent_name, connected_at, last_activity,
                    operations_count, tier1_count, tier2_count, tier3_count,
                    tier4_count, blocked_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                s,
            )

        await db.commit()
    finally:
        await db.close()
