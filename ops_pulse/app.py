"""Local dashboard and JSON API for OpsPulse."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

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


@app.get("/api/incident-report")
def incident_report(response: Response) -> dict[str, Any]:
    """Download a compact incident snapshot without sending host data anywhere."""
    if latest is None:
        raise HTTPException(status_code=503, detail="Metrics are warming up. Retry in a moment.")

    snapshot_data = latest
    alerts = snapshot_data["alerts"]
    checks = {
        "CPU": "Compare CPU over several samples; inspect top processes with `ps`.",
        "Memory": "Check `free -h`, `vmstat 1`, and recent OOM journal messages.",
        "Disk": "Check `df -h` and investigate large directories before removing files.",
        "systemd": "Inspect each failed unit with `systemctl status <unit>` before restarting it.",
        "system journal": "Review recent errors locally; redact host and user details before sharing.",
        "Applications": "Check the application's own logs and dependencies before taking action.",
    }
    disk_summary = [
        {
            "mount": disk["mount"],
            "used_percent": disk["percent"],
            "free_bytes": disk["free_bytes"],
            "status": disk["status"],
        }
        for disk in snapshot_data["disks"]
    ]
    response.headers["Content-Disposition"] = 'attachment; filename="opspulse-incident-report.json"'
    response.headers["Cache-Control"] = "no-store"
    return {
        "report_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_at": snapshot_data["timestamp"],
        "product": "OpsPulse",
        "status": snapshot_data["status"],
        "privacy_notice": (
            "This report is downloaded locally and is not transmitted by OpsPulse. "
            "It contains host metrics and redacted journal messages; review it for "
            "sensitive details before sharing."
        ),
        "summary": {
            "cpu_percent": snapshot_data["cpu"]["percent"],
            "memory_percent": snapshot_data["memory"]["percent"],
            "uptime_seconds": snapshot_data["uptime_seconds"],
            "disks": disk_summary,
            "failed_services": snapshot_data["failed_services"],
            "watched_applications": snapshot_data["watched_applications"],
            "recent_errors": snapshot_data["errors"],
            "alerts": alerts,
            "thresholds": snapshot_data["thresholds"],
        },
        "suggested_read_only_checks": [
            {"signal": alert["source"], "check": checks.get(alert["source"].split(" ")[0], checks["system journal"])}
            for alert in alerts
        ],
    }


@app.get("/api/history")
def metrics_history(limit: int = Query(default=60, ge=1, le=360)) -> dict[str, Any]:
    return {"points": list(history)[-limit:], "interval_seconds": 5}

