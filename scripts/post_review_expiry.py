"""Observe an actual short-budget run after UTC expiry; no clock mocking."""

import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--run-reference", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    reference = json.loads(args.run_reference.read_text(encoding="utf8"))
    original = next(
        r["evidence"]["manifest"] for r in reference["checks"] if r["name"] == "N02_full_real_run_terminal"
    )
    report = {
        "kind": "Actual UTC expiry on valid ten-second total/six-second work budget; no provider",
        "observations": [],
    }
    with httpx.Client(base_url=args.base, timeout=120) as c:
        c.get("/api/v1/session").raise_for_status()
        response = c.post(
            "/api/v1/runs",
            json={
                "dataset_id": original["source_dataset_id"],
                "modules": ["cutting", "assistant", "quality", "crm", "cards"],
                "config_version": "independent-expiry-boundary",
                "solver_config": {
                    "profile": "standard",
                    "seed": 101,
                    "time_limit_seconds": 30,
                    "workers": 1,
                    "minimum_free_remnants": 5,
                },
                "ai_profile": "local_limited",
                "buyer_registry_version": original["buyer_registry_version"],
                "total_budget_seconds": 10,
                "export_reserve_seconds": 4,
            },
            headers={"Idempotency-Key": f"review-expiry:{time.time_ns()}"},
        )
        response.raise_for_status()
        rid = response.json()["run_id"]
        report["run_id"] = rid
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            view = c.get(f"/api/v1/runs/{rid}").json()
            item = {
                "status": view["status"],
                "missing_modules": view["missing_modules"],
                "remaining_seconds": view["budget"]["remaining_seconds"],
                "states": [j["state"] for j in view["jobs"]],
                "errors": [j["error_code"] for j in view["jobs"]],
            }
            if not report["observations"] or item != report["observations"][-1]:
                report["observations"].append(item)
            if item["remaining_seconds"] == 0 and item["status"] != "running":
                break
            time.sleep(0.2)
        report["final_run"] = view
        response = c.post(
            f"/api/v1/runs/{rid}/export",
            headers={"Idempotency-Key": f"review-expiry-export:{time.time_ns()}"},
        )
        response.raise_for_status()
        exported = response.json()
        report["export"] = exported
        report["provider_calls"] = c.get("/api/v1/assistant/usage").json()["calls"]
        report["ok"] = (
            view["budget"]["remaining_seconds"] == 0
            and view["status"] != "running"
            and (exported["status"] != "ready" or not view["missing_modules"])
            and report["provider_calls"] == 0
        )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "status": view["status"],
                "export_status": exported["status"],
                "errors": [j["error_code"] for j in view["jobs"]],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
