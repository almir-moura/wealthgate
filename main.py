"""Wealthgate — Entry point. Runs the FastAPI approval dashboard."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'wealthgate' package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from wealthgate.models import init_db, seed_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and seed demo data on startup."""
    await init_db()
    await seed_db()
    yield


# Import the dashboard app and attach lifespan
from wealthgate.dashboard.app import create_dashboard_app

dashboard_app = create_dashboard_app(lifespan=lifespan)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:dashboard_app",
        host="0.0.0.0",
        port=port,
        reload=port == 8000,
    )
