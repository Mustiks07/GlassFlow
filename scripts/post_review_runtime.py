"""Independent real HTTP smoke/boundary review; no provider or human measurements."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "candidate": args.candidate,
        "kind": "real_HTTP_independent_runtime",
        "checks": [],
        "human_measurements": "NOT_RUN",
        "live_AI": "NOT_RUN",
    }

    def record(name, ok, evidence):
        report["checks"].append({"name": name, "ok": bool(ok), "evidence": evidence})
        (args.out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )

    with httpx.Client(base_url=args.base, timeout=120) as client:
        client.get("/api/v1/session").raise_for_status()
        usage0 = client.get("/api/v1/assistant/usage").json()

        def post(path, body=None, key=None, **kwargs):
            response = client.post(
                "/api/v1" + path,
                json=body,
                headers={"Idempotency-Key": key or f"review:{time.time_ns()}"},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

        source = post("/datasets/demo")
        workspace = post(f"/datasets/{source['dataset_id']}/working-copy", {})
        d = workspace["dataset_id"]
        report["dataset_id"] = d
        # N05: no fabricated human attestations, only rejection/idempotency gates.
        study = post(
            "/labor-studies",
            dict(
                dataset_id=d,
                name="SYNTHETIC boundary review, not labor evidence",
                protocol="No human work observed. Rejection/idempotency checks only.",
                observer="TEST_REVIEWER",
                start_definition="API boundary test starts",
                end_definition="API boundary test ends",
            ),
        )
        sid = study["study_id"]
        started = post(
            f"/labor-studies/{sid}/measurements",
            dict(
                dataset_id=d,
                expected_version=study["version"],
                pair_id="TEST-P1",
                task_id="TEST-T1",
                task_input_ref="synthetic-boundary",
                input_hash=hashlib.sha256(b"synthetic-boundary").hexdigest(),
                operator="TEST_REVIEWER",
                method="manual",
                planned_order="manual_first",
            ),
        )
        mid = started["measurements"][-1]["measurement_id"]
        action = dict(dataset_id=d, expected_version=started["version"], operator="TEST_REVIEWER")
        paused = post(f"/labor-studies/{sid}/measurements/{mid}/pause", action, key="review-pause-fixed")
        replay = post(f"/labor-studies/{sid}/measurements/{mid}/pause", action, key="review-pause-fixed")
        record(
            "N05_pause_idempotent",
            paused == replay and len(replay["measurements"][-1]["events"]) == 2,
            replay,
        )
        action["expected_version"] = paused["version"]
        finished = post(
            f"/labor-studies/{sid}/measurements/{mid}/finish", action | {"result_ref": "synthetic-test-only"}
        )
        invalid = client.post(
            f"/api/v1/labor-studies/{sid}/measurements/{mid}/attest",
            json=action
            | {"expected_version": finished["version"], "active_seconds": "20", "human_confirmed": False},
            headers={"Idempotency-Key": "review-no-human"},
        )
        record(
            "N05_false_human_attestation_rejected",
            invalid.status_code == 422,
            {"http_status": invalid.status_code},
        )
        invalid = client.get(f"/api/v1/labor-studies/{sid}/export", params={"dataset_id": d})
        record(
            "N05_missing_pairs_export_blocked",
            invalid.status_code == 409,
            {"http_status": invalid.status_code, "body": invalid.json()},
        )
        # N09: stale immutable tag resolves current piece, cannot authorize mutation.
        piece = client.get("/api/v1/remnants", params={"dataset_id": d}).json()[0]
        label_body = dict(
            dataset_id=d,
            remnant_id=piece["remnant_id"],
            expected_version=piece["version"],
            operator="TEST_REVIEWER",
        )
        label = post("/piece-labels", label_body)
        changed = client.patch(
            f"/api/v1/remnants/{piece['remnant_id']}/measurement",
            json={
                "dataset_id": d,
                "expected_version": piece["version"],
                "dimensions": piece["dimensions"] | {"length_mm": piece["dimensions"]["length_mm"] + 2},
                "reason": "SYNTHETIC API geometry change, not an observed physical measurement",
            },
        )
        changed.raise_for_status()
        resolved = client.get(
            f"/api/v1/piece-labels/{label['label_id']}/resolve", params={"dataset_id": d}
        ).json()
        invalid = client.post(
            "/api/v1/piece-labels", json=label_body, headers={"Idempotency-Key": "review-old-label"}
        )
        scan = json.loads(label["scan_payload"])
        record(
            "N09_current_lookup_stale_mutation",
            resolved["changed"]
            and resolved["current"]["version"] == piece["version"] + 1
            and not resolved["mutation_authorized_by_label"]
            and invalid.status_code == 409
            and not any(k in scan for k in ("token", "api_key", "session", "reserve", "consume")),
            {"resolved": resolved, "stale_http_status": invalid.status_code},
        )
        queue1 = client.get("/api/v1/workflow/queue", params={"dataset_id": d}).json()
        queue2 = client.get("/api/v1/workflow/queue", params={"dataset_id": d}).json()
        record(
            "N06_workflow_projection_repeatable",
            queue1 == queue2 and queue1.get("projection_only") is True,
            queue1,
        )
        # N01/N02/N10/N15: genuine source files, actual solver/process/jobs and v2 public leads.
        p = ROOT / "data/buyers"
        buyer = post(
            "/buyers/import",
            params={"dataset_id": source["dataset_id"]},
            files={
                "file": ("buyers.csv", (p / "buyers.independent-v2.csv").read_bytes(), "text/csv"),
                "evidence": (
                    "evidence.json",
                    (p / "evidence.independent-v2.json").read_bytes(),
                    "application/json",
                ),
            },
        )
        record("N01_v2_registry_import", buyer["status"] == "verified" and buyer["count"] == 50, buyer)
        run = post(
            "/runs",
            dict(
                dataset_id=source["dataset_id"],
                config_version="independent-review-v1",
                modules=["cutting", "assistant", "quality", "crm", "cards"],
                solver_config=dict(
                    profile="quick", seed=101, time_limit_seconds=5, workers=1, minimum_free_remnants=5
                ),
                ai_profile="local_limited",
                buyer_registry_version=buyer["version"],
                total_budget_seconds=60,
                export_reserve_seconds=5,
            ),
        )
        rid = run["run_id"]
        report["run_id"] = rid
        deadline = time.monotonic() + 120
        report["polling_transitions"] = []
        pending_cards_observations = []
        while time.monotonic() < deadline:
            view = client.get(f"/api/v1/runs/{rid}").json()
            observed = {
                "status": view["status"],
                "missing_modules": view["missing_modules"],
                "states": [j["state"] for j in view["jobs"]],
            }
            if not report["polling_transitions"] or observed != report["polling_transitions"][-1]:
                report["polling_transitions"].append(observed)
            if (
                view["missing_modules"] == ["cards"]
                and len(view["jobs"]) == 4
                and all(j["state"] == "completed" for j in view["jobs"])
            ):
                pending_cards_observations.append(observed)
            if view["status"] != "running":
                break
            time.sleep(args.poll_interval)
        record(
            "N02_pending_cards_never_terminal",
            all(o["status"] == "running" for o in pending_cards_observations),
            {
                "pending_card_windows_observed": len(pending_cards_observations),
                "windows": pending_cards_observations,
                "limitation": "No claim that the narrow window was observed if count is zero; terminal full-run result separately checked.",
            },
        )
        record("N02_full_real_run_terminal", view["status"] == "completed", view)
        exported = post(f"/runs/{rid}/export")
        expected = {"solution.csv", "answers.csv", "verdicts.csv", "picks.csv", "sale_cards.csv"}
        record(
            "N02_five_exact_CSV_bundle",
            exported["status"] == "ready" and set(exported["files"]) >= expected,
            exported,
        )
        for name, url in exported["files"].items():
            response = client.get(url)
            response.raise_for_status()
            (args.out / name).write_bytes(response.content)
        inspect_plan(client, record, view, buyer)
        passport = client.get(
            f"/api/v1/runs/{rid}/passport", params={"dataset_id": view["manifest"]["dataset_id"]}
        ).json()
        record("N15_passport_visible", bool(passport.get("run_id") == rid), passport)
        report["provider_calls"] = client.get("/api/v1/assistant/usage").json()["calls"] - usage0["calls"]
        record("no_provider_calls", report["provider_calls"] == 0, report["provider_calls"])
    print(json.dumps({"checks": [{"name": r["name"], "ok": r["ok"]} for r in report["checks"]]}, indent=2))


def inspect_plan(client, record, view, buyer):
    plan = next(j["result"] for j in view["jobs"] if "placements" in (j.get("result") or {}))
    d = view["manifest"]["dataset_id"]
    response = client.get("/api/v1/sale-cards", params={"dataset_id": d})
    response.raise_for_status()
    cards = response.json()
    used = {p["remnant_id"] for p in plan["placements"] if p["remnant_id"] != "NEW"}
    evidence = []
    for card in cards:
        response = client.get(
            "/api/v1/buyers/matches",
            params={"dataset_id": d, "version": buyer["version"], "remnant_id": card["remnant_id"]},
        )
        response.raise_for_status()
        evidence.append({"card": card, "matches": response.json()})
    record(
        "N01_five_free_original_cards_three_real_leads_each",
        len(cards) == 5
        and all(
            len(set(c["top3_buyers"])) == 3
            and c["remnant_id"] not in used
            and c["remnant_id"].startswith("R")
            and c["plan_id"] == plan["plan_id"]
            and len({m["buyer_id"] for m in row["matches"]}) >= 3
            for row in evidence
            for c in [row["card"]]
        ),
        evidence,
    )
    needs = client.get(f"/api/v1/plans/{plan['plan_id']}/new-requirements", params={"dataset_id": d}).json()
    new_ids = {p["part_id"] for p in plan["placements"] if p["remnant_id"] == "NEW"}
    projected = [pid for row in needs["rows"] for pid in row["part_ids"]]
    record(
        "N10_exact_NEW_projection",
        len(projected) == len(set(projected))
        and set(projected) == new_ids
        and all(
            row["quantity"] == len(row["part_ids"])
            and row["area_mm2"]
            == row["quantity"] * row["dimensions"]["length_mm"] * row["dimensions"]["width_mm"]
            for row in needs["rows"]
        ),
        needs,
    )


if __name__ == "__main__":
    main()
