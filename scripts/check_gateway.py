"""Explicit read-only HTTPS deployment probe, not a substitute for C3's full AI flow."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-env", default="GLASSFLOW_JUDGE_TOKEN")
    parser.add_argument("--report", type=Path, default=Path("docs/release/gateway-probe.json"))
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise SystemExit("HTTPS origin without credentials or query required")
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit("Judge token environment variable is missing; value is never printed")
    started = time.perf_counter()
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.get(args.url.rstrip("/") + "/healthz", headers={"Authorization": f"Bearer {token}"})
    report = {
        "origin": f"{parsed.scheme}://{parsed.netloc}",
        "checked_at": datetime.now(UTC).isoformat(),
        "health_status": response.status_code,
        "health_ms": (time.perf_counter() - started) * 1000,
        "tls_verification": True,
        "full_ai_flow": "not_run",
        "token_expiry": "not_verified",
        "quota": "not_verified",
        "new_computer_under_five_minutes": "not_run",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(f"HTTPS health status={response.status_code}; full AI acceptance remains not_run")
