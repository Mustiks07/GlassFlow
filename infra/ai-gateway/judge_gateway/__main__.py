"""judge_gateway CLI.

  python -m judge_gateway serve [--host 0.0.0.0 --port 8080]   (behind an HTTPS-terminating host)
  python -m judge_gateway issue-token --tokens tokens.json --label jury --days 3 --max-requests 500
  python -m judge_gateway revoke --tokens tokens.json --token-id jt-xxxx
  python -m judge_gateway smoke --url https://<host> --token <token>   (cold start + readiness + one turn)

Run with ``--app-dir`` semantics: from the repository root use
``uv run --directory infra/ai-gateway python -m judge_gateway ...`` or set PYTHONPATH=infra/ai-gateway.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="judge_gateway")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    issue = sub.add_parser("issue-token")
    issue.add_argument("--tokens", type=Path, required=True)
    issue.add_argument("--label", default="jury")
    issue.add_argument("--days", type=int, default=3)
    issue.add_argument("--max-requests", type=int, default=500)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--tokens", type=Path, required=True)
    revoke.add_argument("--token-id", required=True)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--url", required=True)
    smoke.add_argument("--token", required=True)
    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, log_level="info")
    elif args.command == "issue-token":
        from .tokens import issue as issue_token

        token, record = issue_token(args.tokens, label=args.label, days=args.days, max_requests=args.max_requests)
        print(json.dumps({"token_id": record.token_id, "expires_at": record.expires_at.isoformat(), "max_requests": record.max_requests}))
        print("TOKEN (shown once, store it in the jury launch profile only):", token, file=sys.stderr)
    elif args.command == "revoke":
        from .tokens import revoke as revoke_token

        print(json.dumps({"revoked": revoke_token(args.tokens, args.token_id)}))
    else:
        print(json.dumps(run_smoke(args.url, args.token), ensure_ascii=False, indent=2))


def run_smoke(url: str, token: str) -> dict[str, object]:
    import httpx

    from glassflow.modules.intelligence.assistant.prompts import PROMPT_VERSION

    base = url.rstrip("/")
    result: dict[str, object] = {"url": base, "https": base.startswith("https://")}
    started = time.monotonic()
    with httpx.Client(timeout=60) as client:
        health = client.get(f"{base}/healthz")
        result["healthz"] = {"status": health.status_code, "cold_start_ms": int((time.monotonic() - started) * 1000)}
        ready = client.get(f"{base}/readyz")
        result["readyz"] = {"status": ready.status_code, "body": ready.json() if ready.headers.get("content-type", "").startswith("application/json") else None}
        turn_started = time.monotonic()
        turn = client.post(
            f"{base}/v1/turn",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": "smoke", "prompt_version": PROMPT_VERSION, "purpose": "settings_check",
                  "messages": [{"role": "user", "text": "Сколько стоит стекло 4 мм прозрачное за м²?"}]},
        )
        body = turn.json() if turn.headers.get("content-type", "").startswith("application/json") else {}
        result["turn"] = {
            "status": turn.status_code,
            "latency_ms": int((time.monotonic() - turn_started) * 1000),
            "model_id": body.get("model_id"),
            "tool_calls": [c.get("name") for c in body.get("tool_calls", [])] if isinstance(body, dict) else None,
            "code": body.get("code") if isinstance(body, dict) else None,
        }
    result["passed"] = result["https"] and health.status_code == 200 and ready.status_code == 200 and turn.status_code == 200
    return result


if __name__ == "__main__":
    main()
