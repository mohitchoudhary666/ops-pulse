"""Local dashboard and JSON API for OpsPulse."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .collector import collect_snapshot

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
history: deque[dict[str, Any]] = deque(maxlen=360)
latest: dict[str, Any] | None = None


async def _monitor_loop() -> None:
    global latest
    while True:
        try:
            snapshot = await asyncio.to_thread(collect_snapshot)
            latest = snapshot
            history.append(snapshot)
        except Exception:
            # Keep the service alive if an optional host sensor is unavailable.
            logger.exception("Host metrics collection failed")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_monitor_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="OpsPulse", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "opspulse"}


@app.get("/api/snapshot")
def snapshot() -> dict[str, Any]:
    if latest is None:
        raise HTTPException(status_code=503, detail="Metrics are warming up. Retry in a moment.")
    return latest


@app.get("/api/history")
def metrics_history(limit: int = Query(default=60, ge=1, le=360)) -> dict[str, Any]:
    return {"points": list(history)[-limit:], "interval_seconds": 5}

