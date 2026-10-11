"""Read-only Linux host metrics and health checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

import psutil

CPU_WARN = float(os.getenv("OPSPULSE_CPU_WARN", "80"))
MEMORY_WARN = float(os.getenv("OPSPULSE_MEMORY_WARN", "85"))
DISK_WARN = float(os.getenv("OPSPULSE_DISK_WARN", "85"))
LOG_LINES = int(os.getenv("OPSPULSE_LOG_LINES", "80"))
PSEUDO_FILESYSTEMS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "overlay", "squashfs", "cgroup", "cgroup2"}
SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization)(\s*[=:]\s*)([^\s,;]+)"
)


def _run(command: list[str], timeout: float = 3) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError, OSError):
        return None


def _redact(line: str) -> str:
    return SECRET_PATTERN.sub(r"\1\2[REDACTED]", line).strip()


def _disk_metrics() -> list[dict[str, Any]]:
    disks = []
    seen: set[str] = set()
    try:
        partitions = psutil.disk_partitions(all=False)
    except (PermissionError, OSError):
        partitions = []

    for partition in partitions:
        if partition.fstype.lower() in PSEUDO_FILESYSTEMS or partition.mountpoint in seen:
            continue
        seen.add(partition.mountpoint)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "mount": partition.mountpoint,
                "device": partition.device,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": usage.percent,
                "status": "critical" if usage.percent >= 95 else "warning" if usage.percent >= DISK_WARN else "healthy",
            }
        )
    return disks


def _gpu_metrics() -> dict[str, Any]:
    if not shutil.which("nvidia-smi"):
        return {"available": False, "vendor": None, "message": "NVIDIA GPU telemetry unavailable (nvidia-smi not found)."}

    result = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=4,
    )
    if not result or result.returncode != 0:
        return {"available": False, "vendor": "NVIDIA", "message": "nvidia-smi could not read GPU telemetry."}

    devices = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        name, utilization, memory_used, memory_total, temperature = fields
        try:
            devices.append(
                {
                    "name": name,
                    "utilization_percent": int(utilization),
                    "memory_used_mib": int(memory_used),
                    "memory_total_mib": int(memory_total),
                    "temperature_c": int(temperature),
                }
            )
        except ValueError:
            continue
    return {"available": bool(devices), "vendor": "NVIDIA", "devices": devices, "message": None if devices else "No NVIDIA devices reported."}


def _failed_services() -> list[str]:
    result = _run(["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"])
    if not result or result.returncode not in (0, 1):
        return []
    names = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names[:20]


def _recent_errors() -> list[dict[str, str]]:
    result = _run(
        ["journalctl", "--since", "10 minutes ago", "--priority", "err..emerg", "--no-pager", "-n", str(LOG_LINES), "-o", "short-iso"],
        timeout=5,
    )
    if not result or result.returncode != 0:
        return []
    events = []
    for line in result.stdout.splitlines():
        clean = _redact(line)
        if clean:
            events.append({"message": clean[:600]})
    return events[-LOG_LINES:]


def collect_snapshot() -> dict[str, Any]:
    """Collect one point-in-time snapshot without making system changes."""
    started = time.monotonic()
    cpu = psutil.cpu_percent(interval=0.15)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disks = _disk_metrics()
    services = _failed_services()
    errors = _recent_errors()
    gpu = _gpu_metrics()

    alerts: list[dict[str, str]] = []
    if cpu >= CPU_WARN:
        alerts.append({"severity": "warning", "source": "CPU", "message": f"CPU usage is {cpu:.0f}% (threshold {CPU_WARN:.0f}%)."})
    if memory.percent >= MEMORY_WARN:
        alerts.append({"severity": "warning", "source": "Memory", "message": f"Memory usage is {memory.percent:.0f}% (threshold {MEMORY_WARN:.0f}%)."})
    for disk in disks:
        if disk["status"] != "healthy":
            alerts.append({"severity": "critical" if disk["status"] == "critical" else "warning", "source": f"Disk {disk['mount']}", "message": f"Disk usage is {disk['percent']:.0f}% on {disk['mount']}."})
    if services:
        alerts.append({"severity": "critical", "source": "systemd", "message": f"{len(services)} failed service(s): {', '.join(services[:4])}."})
    if errors:
        alerts.append({"severity": "warning", "source": "system journal", "message": f"{len(errors)} error-level event(s) found in the last 10 minutes."})

    status = "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy"
    uptime = time.time() - psutil.boot_time()
    net = psutil.net_io_counters()
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown"),
        "platform": os.name,
        "status": status,
        "uptime_seconds": int(uptime),
        "collection_ms": round((time.monotonic() - started) * 1000),
        "cpu": {"percent": cpu, "per_core": cpu_per_core, "logical_cores": psutil.cpu_count(logical=True)},
        "memory": {"total_bytes": memory.total, "used_bytes": memory.used, "available_bytes": memory.available, "percent": memory.percent},
        "swap": {"total_bytes": swap.total, "used_bytes": swap.used, "percent": swap.percent},
        "disks": disks,
        "gpu": gpu,
        "failed_services": services,
        "errors": errors,
        "network": {"bytes_sent": net.bytes_sent, "bytes_received": net.bytes_recv},
        "alerts": alerts,
        "thresholds": {"cpu_percent": CPU_WARN, "memory_percent": MEMORY_WARN, "disk_percent": DISK_WARN},
    }

