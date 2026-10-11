# OpsPulse

**Local-first Linux observability and incident triage for small engineering teams.** OpsPulse brings host health, failed services, recent system errors, and safe first-response guidance into one dashboard. When an incident needs escalation, export a compact JSON evidence report for review and handoff.

![OpsPulse host health dashboard](docs/dashboard.svg)

## The operational problem

During a host or service incident, responders often have to switch between system metrics, `systemd`, and journal logs before they can share useful evidence. OpsPulse collects those read-only signals in one place and offers a local report that gives a teammate a consistent starting point for triage and root-cause analysis.

This is a portfolio project and learning tool. It is not affiliated with an employer, and it does not claim production deployment or measured incident-time savings.

## What it does

- Samples CPU and memory every five seconds and plots a rolling trend.
- Shows swap, readable filesystem use, network counters, and uptime.
- Reads NVIDIA GPU utilization, VRAM, and temperature when `nvidia-smi` is installed.
- Lists failed systemd units and error-level journal messages from the last ten minutes.
- Redacts common password, token, secret, API key, and authorization assignments in displayed journal lines.
- Flags CPU, memory, and disk thresholds with configurable warning levels.
- Provides a chat-style triage panel with read-only diagnostic suggestions; commands are never executed.
- Exports a downloadable incident report with a timestamp, health summary, active alerts, failed services, redacted recent errors, thresholds, and suggested read-only checks.
- Keeps the report local. It is not sent to a hosted service; review host details and journal messages before sharing it with anyone.
- Exposes JSON endpoints for health, current telemetry, metric history, and incident report export.

## Quick start

Requirements: Python 3.11+, Linux with systemd for service and journal checks, and `nvidia-smi` for NVIDIA GPU metrics.

```bash
git clone https://github.com/mohitchoudhary666/ops-pulse.git
cd ops-pulse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn ops_pulse.app:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The **Export incident report** button downloads `opspulse-incident-report.json` locally. Review the file before attaching it to an issue or sharing it externally.

## API

| Endpoint | Purpose |
| --- | --- |
| `/api/health` | Process liveness |
| `/api/snapshot` | Latest host metrics, alerts, and recent errors |
| `/api/history?limit=60` | Recent five-second metric samples |
| `/api/incident-report` | Download the latest incident snapshot as JSON |
| `/api/docs` | Interactive API reference |

The incident report endpoint returns `503` while the initial metrics sample is warming up. It sets `Cache-Control: no-store` and an attachment filename for the JSON download.

## Configuration

Set optional environment variables before starting the server:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `OPSPULSE_CPU_WARN` | `80` | CPU warning percentage |
| `OPSPULSE_MEMORY_WARN` | `85` | Memory warning percentage |
| `OPSPULSE_DISK_WARN` | `85` | Disk warning percentage |
| `OPSPULSE_LOG_LINES` | `80` | Maximum journal lines collected |

Example: `OPSPULSE_CPU_WARN=75 OPSPULSE_DISK_WARN=90 python -m uvicorn ops_pulse.app:app --host 127.0.0.1 --port 8765`.

## Architecture

```text
Linux host sensors ──> Python collector ──> in-memory rolling history
                             │                        │
                             ├── FastAPI JSON API <── dashboard (5s polling)
                             └── incident report ───> local JSON download
```

Collection is read-only. The triage panel returns text guidance only. OpsPulse does not restart services, change configuration, run suggested commands, or transmit telemetry.

## Safety and current limits

- The server binds to loopback (`127.0.0.1`) in the quick start. Do not expose it publicly without authentication and network controls.
- Metrics and journal messages are returned by the local JSON API and included in the incident report. Journal redaction covers common key/value secret assignments, not every possible sensitive format; inspect reports before sharing.
- `systemctl` and journal checks depend on Linux systemd and the current user's permissions. Restricted journal access may result in missing events.
- GPU telemetry is optional. OpsPulse reports when `nvidia-smi` is absent or cannot read a device.
- This is a single-host monitor, not a hosted alerting service or fleet management platform. The report is downloaded only on request and has no external delivery integration.

## Contributing

Issues and pull requests are welcome. Keep checks read-only by default, avoid uploading real host logs, and document platform or permission requirements. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
