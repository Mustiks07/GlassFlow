"""Real TCP/uvicorn acceptance. No evaluation KEY, secret, fake ports or DB mutation.

Creates changed inputs separately, pins original materials/KB, downloads accepted
bytes, invokes the unmodified organizer validator, exercises real deadline failure,
then restarts the same service/database and verifies the old accepted artifacts.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "inputs/PACK_for_teams"
RESULT_SCHEMAS = {
    "solution.csv": ["part_id", "remnant_id", "x_mm", "y_mm", "rot"],
    "answers.csv": ["id", "answer"], "picks.csv": ["app_id"],
    "verdicts.csv": ["id", "verdict", "correct"],
    "sale_cards.csv": ["remnant_id", "title", "price_tg", "description", "target_buyer", "top3_buyers"],
    "buyers_top50.csv": ["name", "city", "category", "url", "why", "source_url", "score"],
}
INPUTS = ["1_ostatki/materials.csv", "1_ostatki/stock_open.csv", "1_ostatki/orders_open.csv",
    "2_assistant_crm/ksm_knowledge_base.json", "2_assistant_crm/questions_open.csv",
    "2_assistant_crm/dialogs_open.csv", "2_assistant_crm/applications_open.csv"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def changed_inputs(directory, *, partial=False):
    directory.mkdir(parents=True, exist_ok=True)
    result, changes = {}, []
    identity = "POST18484-FAIL-" if partial else "POST18484-"
    for relative in INPUTS:
        raw = (PACK / relative).read_bytes()
        name = Path(relative).name
        if name in {"materials.csv", "ksm_knowledge_base.json"}:
            output = raw
        else:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            columns = [c for c in reader.fieldnames if c != "вернулся_за_60_дней"]
            rows = list(reader)
            for index, row in enumerate(rows):
                for key in {"stock_open.csv": ["remnant_id"], "orders_open.csv": ["part_id", "order_id"],
                    "applications_open.csv": ["app_id", "client_id"], "questions_open.csv": ["id"],
                    "dialogs_open.csv": ["id"]}[name]:
                    row[key] = identity + row[key]
                row.pop("вернулся_за_60_дней", None)  # Future label never enters runtime.
                if name == "stock_open.csv" and index < 9:
                    row["длина_мм"] = str(int(row["длина_мм"]) + 7)
                    row["место"] += " / перепроверен новый вход"
                if name == "orders_open.csv" and index < 7:
                    row["ширина_мм"] = str(int(row["ширина_мм"]) + 1)
                if name == "applications_open.csv" and index < 13:
                    row["сумма_тг"] = str(int(float(row["сумма_тг"])) + 173)
                    row["ответ_через_мин"] = str(int(row["ответ_через_мин"]) + 2)
            if name == "questions_open.csv":
                rows[0]["question"] = "Сколько стоит прозрачное стекло6 мм 451×371 мм с кромкой по всем сторонам?"
                rows[1]["question"] = "Вы устанавливаете зеркало у клиента в Астане?"
                rows[2]["question"] = "Нужна цена неизвестного крепления ZETA-POST-18484, без известной модели."
                if partial:
                    rows = [{"id": identity + str(i), "question": f"Заявка {i}: неизвестное крепление ZETA-{i}; "
                             "товар и размеры пока не подтверждены, не называйте выдуманную цену."} for i in range(1000)]
            if name == "dialogs_open.csv":
                rows[0]["client"] = "Подскажите текущую цену серого калёного стекла за м²."
                if partial:
                    rows[0].update(client="Цена неизвестного товара ZETA-18484?", manager="Товар ZETA-18484 стоит99 тенге.")
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(reversed(rows))
            output = stream.getvalue().encode("utf-8")
            changes.append({"file": name, "all_ids_replaced": True, "rows_reversed": True,
                            "future_labels_removed": name == "applications_open.csv"})
        (directory / name).write_bytes(output)
        result[name] = output
    return result, changes


class Service:
    def __init__(self, data, port):
        self.data, self.port, self.process, self.log = data, port, None, None

    def start(self):
        with socket.socket() as probe:
            probe.settimeout(.5)
            if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError("Refusing to touch an existing listener")
            # A recently stopped Windows socket may be in TIME_WAIT; it is not
            # another listener. Uvicorn itself owns the SO_REUSEADDR bind.
        env = {k: v for k, v in os.environ.items() if not re.search(r"API_KEY|TOKEN|SECRET|GEMINI|BASISWEB|OPENROUTER|OPENAI|AI_PROFILE", k, re.I)}
        env.update(GLASSFLOW_DATA_DIR=str(self.data), PYTHONPATH=str(ROOT / "backend"))
        self.data.mkdir(parents=True, exist_ok=True)
        self.log = (self.data / "uvicorn.log").open("ab")
        self.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "glassflow.main:app", "--host", "127.0.0.1",
            "--port", str(self.port), "--log-level", "warning"], cwd=ROOT, env=env, stdout=self.log, stderr=self.log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        with httpx.Client(trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Own uvicorn exited before readiness; inspect local uvicorn.log")
                try:
                    if client.get(f"http://127.0.0.1:{self.port}/api/v1/ready").json()["business_modules_ready"]:
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.2)
        raise RuntimeError("Own uvicorn failed readiness")

    def stop(self, client):
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                client.post("/api/v1/system/shutdown", headers={"X-GlassFlow-Session": client.get("/api/v1/session").json()["session_token"]}).raise_for_status()
                # Windows venv python.exe may be a redirector with the real host
                # beneath it. Stop only this owned tree, not a process-name match.
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self.process.terminate()
                self.process.wait(timeout=15)
            except (httpx.HTTPError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()
        self.process = None


def post(client, path, body=None, **kwargs):
    response = client.post("/api/v1" + path, json=body, headers={"Idempotency-Key": f"post-acceptance:{time.time_ns()}"}, **kwargs)
    if not response.is_success:
        raise RuntimeError(f"HTTP {response.status_code} {path}: {response.text[:1000]}")
    return response.json()


def import_source(client, files, name):
    preview = post(client, "/imports/preview", files=[("files", (name, content)) for name, content in files.items()])
    assert not preview["errors"], preview
    source = post(client, f"/imports/{preview['import_id']}/commit", {"name": name})
    buyer = post(client, "/buyers/import", params={"dataset_id": source["dataset_id"]}, files={
        "file": ("buyers.independent-v2.csv", (ROOT / "data/buyers/buyers.independent-v2.csv").read_bytes()),
        "evidence": ("evidence.independent-v2.json", (ROOT / "data/buyers/evidence.independent-v2.json").read_bytes())})
    assert buyer["status"] == "verified" and buyer["count"] == 50, buyer
    return source, buyer


def request_run(client, source, buyer, *, partial=False):
    return post(client, "/runs", {"dataset_id": source["dataset_id"], "config_version": "post-changed-input-http-v1",
        "buyer_registry_version": buyer["version"], "ai_profile": "local_limited",
        "total_budget_seconds": 12 if partial else 120, "export_reserve_seconds": 4 if partial else 30,
        "solver_config": {"profile": "extended", "time_limit_seconds": 6, "workers": 1, "minimum_free_remnants": 5}})


def poll_run(client, run_id, *, complete=False, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = client.get(f"/api/v1/runs/{run_id}").json()
        if (value["manifest"].get("accepted_export_id") if complete else value["status"] != "running"):
            return value
        time.sleep(.2)
    raise RuntimeError(f"Run {run_id} exceeded external observer timeout: {value}")


def download(client, exported, directory):
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, uri in exported["files"].items():
        response = client.get(uri)
        response.raise_for_status()
        raw = response.content
        (directory / name).write_bytes(raw)
        detail = {"sha256": digest(raw), "bytes": len(raw), "uri": uri}
        if name in RESULT_SCHEMAS:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
            assert reader.fieldnames == RESULT_SCHEMAS[name] and not raw.startswith(b"\xef\xbb\xbf"), name
            detail["rows"] = len(list(reader))
        result[name] = detail
    return result


def verify_downloaded_contracts(directory, files):
    def rows(name):
        return list(csv.DictReader(io.StringIO((directory / name).read_text(encoding="utf-8"), newline=""), strict=True))
    def inputs(name):
        return list(csv.DictReader(io.StringIO(files[name].decode("utf-8")), strict=True))
    for result, source, key in [("solution.csv", "orders_open.csv", "part_id"),
            ("answers.csv", "questions_open.csv", "id"), ("verdicts.csv", "dialogs_open.csv", "id")]:
        actual, expected = rows(result), inputs(source)
        assert len(actual) == len(expected) and {r[key] for r in actual} == {r[key] for r in expected}, result
        assert all(set(r) == set(RESULT_SCHEMAS[result]) for r in actual), result
    assert all(r["answer"].strip() for r in rows("answers.csv"))
    assert all(r["verdict"] in {"OK", "ERROR"} for r in rows("verdicts.csv"))
    picks = [r["app_id"] for r in rows("picks.csv")]
    assert len(picks) == len(set(picks)) == 25 and set(picks) <= {r["app_id"] for r in inputs("applications_open.csv")}
    cards = rows("sale_cards.csv")
    assert len(cards) == 5 and len({r["remnant_id"] for r in cards}) == 5
    assert {r["remnant_id"] for r in cards} <= {r["remnant_id"] for r in inputs("stock_open.csv")}
    buyers = rows("buyers_top50.csv")
    assert len(buyers) == len({r["name"] for r in buyers}) == 50
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert all(digest((directory / name).read_bytes()) == expected for name, expected in manifest["files"].items())
    return {"exact_headers_utf8_no_bom": True, "all_changed_ids_and_row_counts": True,
            "picks_25_unique_members": True, "cards_5_original_members": True,
            "buyers_50_unique": True, "pinned_manifest_file_hashes": True}


def exercise_cancel(client, source, buyer, directory):
    cancelled = request_run(client, source, buyer)
    end = time.monotonic() + 60
    while time.monotonic() < end:
        view = client.get(f"/api/v1/runs/{cancelled['run_id']}").json()
        target = next((j for j in view["jobs"] if j["total"] == 1000 and
                       j["state"] == "running" and j["accepted_row_count"] > 0), None)
        if target and sum(j["state"] == "completed" for j in view["jobs"]) >= 4:
            break
        time.sleep(.2)
    assert target, "Real cancellable long batch did not remain active"
    assert sum(j["state"] == "completed" for j in view["jobs"]) >= 4, "Other real modules did not complete"
    post(client, f"/jobs/{target['job_id']}/cancel", params={"dataset_id": target["dataset_id"]})
    view = poll_run(client, cancelled["run_id"], seconds=30)
    assert any(j["state"] == "cancelled" and j["accepted_row_count"] > 0 for j in view["jobs"])
    exported = post(client, f"/runs/{cancelled['run_id']}/export")
    assert exported["status"] != "ready"
    assert "answers.csv" not in exported["files"] and "verdicts.csv" not in exported["files"]
    assert any("UNRESOLVED_VERDICT" in error for error in exported["errors"])
    return {"run": view, "export": exported, "downloads": download(client, exported, directory)}


def unknown_product_issues(reply):
    issues = []
    if reply["status"] not in {"clarification", "manager_handoff", "limited"}:
        issues.append("UNKNOWN_SKU_MATCHED_GENERIC_HARDWARE")
    if reply.get("quote") and reply["quote"]["status"] == "ready":
        issues.append("UNKNOWN_SKU_READY_QUOTE")
    if any(f.get("kind") == "price" for f in (reply.get("card") or {}).get("facts", [])):
        issues.append("UNKNOWN_SKU_HAS_PRODUCT_PRICE_FACTS")
    if re.search(r"\d[\d\s.,]*\s*(?:₸|тг|тенге)(?!\w)", reply["answer"], re.I):
        issues.append("UNKNOWN_SKU_ASSERTS_PRODUCT_PRICE")
    return [{"severity": "P1", "code": code,
             "expected": "clarification_or_manager_handoff_without_unrelated_price"} for code in issues]


def exercise(args, report):
    files, changes = changed_inputs(args.output / "inputs")
    report.update(input_changes=changes, input_hashes={name: digest(value) for name, value in files.items()})
    assert files["materials.csv"] == (PACK / "1_ostatki/materials.csv").read_bytes()
    assert files["ksm_knowledge_base.json"] == (PACK / "2_assistant_crm/ksm_knowledge_base.json").read_bytes()
    assert not (args.data / "glassflow.db").exists(), "Fresh data path required; never deleting an existing database"
    server = Service(args.data, args.port)
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=120, trust_env=False) as client:
        try:
            server.start()
            report["readiness"] = client.get("/api/v1/ready").json()
            client.get("/api/v1/session").raise_for_status()
            source, buyer = import_source(client, files, "Changed IDs and independent dimensions / HTTP")
            started_at = time.monotonic()
            started = request_run(client, source, buyer)
            report.update(source=source, registry=buyer, run_id=started["run_id"])
            print("Actual TCP run started", started["run_id"], flush=True)
            view = poll_run(client, started["run_id"], complete=True)
            report["first_full_accepted_seconds"] = round(time.monotonic() - started_at, 3)
            assert report["first_full_accepted_seconds"] <= 120
            report["baseline_view"] = view
            exported = post(client, f"/runs/{started['run_id']}/export")
            assert exported["status"] == "ready", exported
            report["export"] = exported
            report["downloads"] = download(client, exported, args.output / "downloaded")
            assert set(RESULT_SCHEMAS) <= set(report["downloads"])
            report["download_contract_checks"] = verify_downloaded_contracts(args.output / "downloaded", files)
            passport = client.get(f"/api/v1/runs/{started['run_id']}/passport", params={"dataset_id": source["dataset_id"], "view": "accepted"}).json()
            report["accepted_passport"] = passport
            pinned = json.loads((args.output / "downloaded/manifest.json").read_text(encoding="utf-8"))
            selected_cutting = client.get(f"/api/v1/jobs/{pinned['result_refs']['cutting']['job_id']}").json()
            cards_job = client.get(f"/api/v1/jobs/{pinned['result_refs']['cards']['job_id']}").json()
            response = client.get("/api/v1/sale-cards", params={"dataset_id": view["manifest"]["dataset_id"],
                                                              "plan_id": selected_cutting["result"]["plan_id"]})
            response.raise_for_status()
            wanted = set(cards_job["result"]["card_ids"])
            cards = [c for c in response.json() if c["card_id"] in wanted]
            assert len(cards) == 5
            assert all(len({m["buyer_id"] for m in c["buyer_matches"]}) >= 3 for c in cards)
            assert all(c["remnant_id"] in selected_cutting["result"]["free_original_remnant_ids"] for c in cards)
            report["five_cards_three_matches"] = cards
            official = PACK / "1_ostatki/validate.py"
            checked = subprocess.run([sys.executable, "-X", "utf8", str(official), str(args.output / "inputs/stock_open.csv"),
                str(args.output / "inputs/orders_open.csv"), str(args.output / "downloaded/solution.csv"),
                str(args.output / "inputs/materials.csv")], capture_output=True, encoding="utf-8", timeout=30)
            assert (checked.returncode == 0 and re.search(r"RESULT coverage=[0-9.]+ invalid=0 ", checked.stdout)
                    and "не указано в решении: 0" in checked.stdout), checked.stdout
            report["original_official_validator"] = {"sha256": digest(official.read_bytes()), "exit_code": checked.returncode,
                "stdout": checked.stdout, "stderr": checked.stderr}
            unknown = post(client, "/assistant/turns", {"dataset_id": source["dataset_id"], "kb_version": source["kb_version"],
                "text": "Сколько стоит неизвестное крепление ZETA-POST-18484, модель и параметры неизвестны?",
                "inventory_mode": "none", "allow_ai": False})
            report["unknown_request"] = unknown
            report.setdefault("product_issues", []).extend(unknown_product_issues(unknown))
            assert unknown["model_call_count"] == 0
            partial_files, _ = changed_inputs(args.output / "partial-inputs", partial=True)
            partial_source, partial_buyer = import_source(client, partial_files, "Actual deadline/unknown source")
            partial = request_run(client, partial_source, partial_buyer, partial=True)
            failed_view = poll_run(client, partial["run_id"], seconds=30)
            dependency_end = time.monotonic() + 5
            while time.monotonic() < dependency_end:
                failed_view = client.get(f"/api/v1/runs/{partial['run_id']}").json()
                dependency = next((j for j in failed_view["jobs"] if j["error_code"] == "CUTTING_NOT_COMPLETED"), None)
                if dependency:
                    break
                time.sleep(.1)
            assert dependency, "Terminal cutting dependency was not projected"
            dependency_id = dependency["job_id"]
            for _ in range(3):
                time.sleep(.2)
                check = client.get(f"/api/v1/runs/{partial['run_id']}").json()
                assert next(j["job_id"] for j in check["jobs"] if j["error_code"] == "CUTTING_NOT_COMPLETED") == dependency_id
            partial_export = post(client, f"/runs/{partial['run_id']}/export")
            assert partial_export["status"] != "ready", (failed_view, partial_export)
            assert any(j["state"] in {"failed", "cancelled", "interrupted"} for j in failed_view["jobs"]) or partial_export["errors"]
            report["partial_failure"] = {"run": failed_view, "export": partial_export,
                "downloads": download(client, partial_export, args.output / "partial-downloaded"),
                "stable_terminal_dependency_id": dependency_id}
            report["cancelled_partial"] = exercise_cancel(client, partial_source, partial_buyer,
                                                         args.output / "cancelled-downloaded")
            # Let the accepted run settle before restarting; preserving exact accepted refs is observable.
            settled = poll_run(client, started["run_id"], seconds=120)
            improvement_id = (settled.get("budget") or {}).get("improvement_job_id")
            assert improvement_id, "Configured enhancement did not run after accepted baseline"
            improvement = client.get(f"/api/v1/jobs/{improvement_id}")
            improvement.raise_for_status()
            report["bounded_improvement_attempt"] = improvement.json()
            before_restart = client.get(f"/api/v1/runs/{started['run_id']}/passport", params={"dataset_id": source["dataset_id"], "view": "accepted"}).json()
            server.stop(client)
            server.start()
            client.cookies.clear()
            client.get("/api/v1/session").raise_for_status()
            after = client.get(f"/api/v1/runs/{started['run_id']}/passport", params={"dataset_id": source["dataset_id"], "view": "accepted"}).json()
            assert after == before_restart
            before_counts = {j["job_id"]: j["accepted_row_count"] for j in failed_view["jobs"]}
            after_counts = {job_id: client.get(f"/api/v1/jobs/{job_id}").json()["accepted_row_count"]
                            for job_id in before_counts}
            assert before_counts == after_counts
            after_view = client.get(f"/api/v1/runs/{partial['run_id']}").json()
            assert next(j["job_id"] for j in after_view["jobs"] if j["error_code"] == "CUTTING_NOT_COMPLETED") == dependency_id
            for name, detail in report["downloads"].items():
                response = client.get(detail["uri"])
                response.raise_for_status()
                assert digest(response.content) == detail["sha256"], name
            report["restart"] = {"same_accepted_passport": True, "old_download_bytes_preserved": True,
                                 "accepted_export_id": after["export_id"], "durable_partial_row_counts": after_counts,
                                 "host_stop": "owned_process_tree_after_API_coordinator_stop"}
            report["status"] = "blocked_product_issue" if report.get("product_issues") else "passed"
        finally:
            server.stop(client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18484)
    parser.add_argument("--data", type=Path, default=ROOT / ".qa/new-inputs")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/release/post/http-new-inputs")
    args = parser.parse_args()
    args.data, args.output = args.data.resolve(), args.output.resolve()
    report = {"source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "transport": "actual_tcp_uvicorn", "online_ai": "not_run", "human_measurements": "not_run",
              "official_hidden_accuracy": "not_run_no_changed_input_KEY", "status": "running"}
    begin = time.monotonic()
    try:
        exercise(args, report)
    except Exception as exc:
        report.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["total_observer_seconds"] = round(time.monotonic() - begin, 3)
        write_json(args.output / "report.json", report)
        print(json.dumps({k: report[k] for k in ("status", "source_sha", "total_observer_seconds")}, ensure_ascii=False), flush=True)
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
