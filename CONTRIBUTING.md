# Contributing to OpsPulse

Thanks for helping improve OpsPulse. Keep contributions focused and explain the host platforms and permissions involved.

## Guidelines

- Keep monitoring and default checks read-only.
- Never add automatic remediation, privileged actions, or outbound telemetry without a clear opt-in design and documentation.
- Treat system logs and process details as potentially sensitive. Avoid adding real host logs to issues, examples, or screenshots.
- Escape or sanitize host-derived content before rendering it in the dashboard.
- Document optional tools and platform-specific behavior.
- Keep the default web listener on loopback unless authentication and network safety are addressed.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install ruff
ruff check ops_pulse
python -m uvicorn ops_pulse.app:app --host 127.0.0.1 --port 8765 --reload
```

Before opening a pull request, describe the change, how you verified it, and any permission or platform limitations.
