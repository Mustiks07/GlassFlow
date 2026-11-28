"""Offline evaluation of the intelligence runtime.

This is the ONLY code allowed to touch evaluation KEY files, and it does so only by passing
their paths to the organisers' unmodified ``selfcheck.py`` in a subprocess. Answers and
verdicts are produced by the normal runtime service (same Pricing, matcher and verifier as
HTTP/UI). The CSVs written here are evaluation evidence; the contest exporter belongs to
the platform run.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from glassflow.contracts.intelligence import (
    AnswerBatchRequest,
    AssistantTurn,
    DialogBatchRequest,
    DialogRow,
    QuestionRow,
    QuoteRequest,
)
from glassflow.core.db import create_database

from ..assistant.facts import FactSet
from ..assistant.prompts import PROMPT_VERSION
from ..assistant.verifier import verify_answer
from ..providers.policy import MemoryLedger
from ..providers.settings import EnvSecrets, build_runtime, profile_from_env
from ..service import DbLedger, IntelligenceService
from ..sources import KB_RELATIVE, MATERIALS_RELATIVE, InMemorySources

DATASET = "evaluation-open"
CASES_PATH = Path(__file__).with_name("cases_extended.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_bytes(buffer.getvalue().encode("utf-8"))  # UTF-8 without BOM


def numbers(text: str) -> set[float]:
    """Number reading identical to the organisers' selfcheck."""
    text = text.replace(" ", " ")
    found = set()
    for match in re.finditer(r"\d[\d  ]*(?:[.,]\d+)?", text):
        try:
            found.add(float(re.sub(r"[  ]", "", match.group()).replace(",", ".")))
        except ValueError:
            pass
    return found


def has_price_claim(text: str) -> bool:
    return bool(re.search(r"\d[\d  ]{2,}\s*(тг|₸|тенге)|\d+\s*(дн|дней|день|рабочих)|\b\d{3,}\b", text))


@dataclass
class Environment:
    service: IntelligenceService
    kb_version: str
    ai_status: str
    ledger: object


def build_environment(pack: Path, *, allow_ai: bool, db_dir: Path | None = None) -> Environment:
    sources = InMemorySources()
    sources.add_kb(DATASET, (pack / KB_RELATIVE).read_bytes(), origin="organisers_open_pack")
    sources.set_materials(DATASET, (pack / MATERIALS_RELATIVE).read_bytes(), origin="organisers_open_pack")
    directory = db_dir or Path(tempfile.mkdtemp(prefix="glassflow-eval-"))
    _, session_factory = create_database(directory)
    secrets = EnvSecrets()
    ledger = DbLedger(session_factory) if allow_ai else MemoryLedger()
    runtime = build_runtime(profile_from_env(secrets=secrets), secrets, prompt_version=PROMPT_VERSION, ledger=ledger) if allow_ai else None
    service = IntelligenceService(sources, session_factory, runtime=runtime)
    kb_version = service.catalog_for(DATASET).kb.version
    return Environment(service, kb_version, runtime.status if runtime else "disabled", ledger)


def run_selfcheck(selfcheck: Path, mode: str, produced: Path, key: Path) -> dict[str, object]:
    process = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(selfcheck), mode, str(produced), str(key)],
        capture_output=True,
        timeout=120,
    )
    stdout = process.stdout.decode("utf-8", errors="replace")
    score = re.search(r"ИТОГО[^\d]*([\d.]+) из (\d+)", stdout)
    return {
        "command": f"python -I -X utf8 selfcheck.py {mode} {produced.name} {key.name}",
        "exit_code": process.returncode,
        "stdout": stdout.strip(),
        "stderr": process.stderr.decode("utf-8", errors="replace").strip(),
        "score": float(score.group(1)) if score else None,
        "max": int(score.group(2)) if score else None,
    }


def evaluate_open(pack: Path, out: Path, *, allow_ai: bool = False) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=allow_ai)
    questions_path = pack / "2_assistant_crm" / "questions_open.csv"
    dialogs_path = pack / "2_assistant_crm" / "dialogs_open.csv"
    questions = read_rows(questions_path)
    dialogs = read_rows(dialogs_path)
    started = time.monotonic()
    answers = asyncio.run(
        env.service.answer_questions(
            AnswerBatchRequest(
                dataset_id=DATASET, kb_version=env.kb_version, allow_ai=allow_ai,
                questions=[QuestionRow(id=row["id"], question=row["question"]) for row in questions],
            )
        )
    )
    answer_seconds = time.monotonic() - started
    verdicts = env.service.check_dialogs(
        DialogBatchRequest(
            dataset_id=DATASET, kb_version=env.kb_version,
            dialogs=[DialogRow(id=row["id"], client=row["client"], manager=row["manager"]) for row in dialogs],
        )
    )
    answers_csv, verdicts_csv = out / "answers.csv", out / "verdicts.csv"
    write_csv(answers_csv, ["id", "answer"], [[row.id, row.answer] for row in answers.answers])
    exportable = [v for v in verdicts.verdicts if v.verdict in {"OK", "ERROR"}]
    write_csv(verdicts_csv, ["id", "verdict", "correct"], [[v.id, v.verdict, v.correct or "" if v.verdict == "ERROR" else ""] for v in exportable])
    selfcheck = pack / "2_assistant_crm" / "selfcheck.py"
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "open_pack_runtime_evaluation",
        "runtime_path": "IntelligenceService.answer_questions / check_dialogs (same as HTTP)",
        "ai": {"allowed": allow_ai, "runtime_status": env.ai_status},
        "inputs": {
            "kb_sha256": sha256(pack / KB_RELATIVE),
            "materials_sha256": sha256(pack / MATERIALS_RELATIVE),
            "questions_sha256": sha256(questions_path),
            "dialogs_sha256": sha256(dialogs_path),
            "selfcheck_sha256": sha256(selfcheck),
        },
        "outputs": {"answers_sha256": sha256(answers_csv), "verdicts_sha256": sha256(verdicts_csv)},
        "kb_version": env.kb_version,
        "prompt_version": PROMPT_VERSION,
        "answer_batch": {"complete": answers.complete, "counts": answers.counts, "seconds": round(answer_seconds, 3),
                         "paths": sorted({a.answer_path for a in answers.answers})},
        "dialog_batch": {"complete": verdicts.complete, "counts": verdicts.counts, "blockers": verdicts.export_blockers},
        "selfcheck": {
            "assistant": run_selfcheck(selfcheck, "assistant", answers_csv, pack / "2_assistant_crm" / "questions_open_KEY.csv"),
            "dialogs": run_selfcheck(selfcheck, "dialogs", verdicts_csv, pack / "2_assistant_crm" / "dialogs_open_KEY.csv"),
        },
        "rows": [
            {"id": a.id, "question": q["question"], "answer": a.answer, "status": a.status, "path": a.answer_path,
             "numbers": sorted(numbers(a.answer)), "price_like_claim": has_price_claim(a.answer)}
            for q, a in zip(questions, answers.answers)
        ],
        "verdicts": [{"id": v.id, "verdict": v.verdict, "correct": v.correct, "product": v.catalog_product_id,
                      "meaning": v.reference_meaning, "mentions": [m.model_dump() for m in v.mentions]} for v in verdicts.verdicts],
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _check_case(case: dict, reply) -> tuple[bool, list[str], list[str]]:
    expect = case["expect"]
    answer = reply.answer
    got = numbers(answer)
    reasons: list[str] = []
    for value in expect.get("numbers", []):
        if not any(abs(g - value) <= 0.5 for g in got):
            reasons.append(f"missing_number:{value}")
    for value in expect.get("absent_numbers", []):
        if any(abs(g - value) <= 0.005 for g in got):
            reasons.append(f"forbidden_number:{value}")
    low = answer.lower()
    contains = expect.get("contains_any")
    if contains and not any(word.lower() in low for word in contains):
        reasons.append(f"missing_any:{contains}")
    for word in expect.get("not_contains", []):
        if word.lower() in low:
            reasons.append(f"forbidden_text:{word}")
    if expect.get("status") and reply.status not in expect["status"]:
        reasons.append(f"status:{reply.status}")
    if expect.get("no_price_claim") and has_price_claim(answer):
        reasons.append("price_like_claim_in_unknown_answer")
    facts = FactSet()
    for fact in reply.card.facts if reply.card else []:
        try:
            facts.add(fact.kind, Decimal(fact.value), fact.unit, fact.source_ref)
        except Exception:
            facts.add(fact.kind, fact.value, fact.unit, fact.source_ref)
    user_text = " ".join(case["turns"])
    verification = verify_answer(answer, facts, user_text, remnant_checked=False)
    promises = [item for item in verification.unsupported]
    return not reasons and not promises, reasons, promises


async def _run_case(service: IntelligenceService, kb_version: str, case: dict, allow_ai: bool):
    conversation = None
    reply = None
    for text in case["turns"]:
        reply = await service.assistant_turn(
            AssistantTurn(dataset_id=DATASET, kb_version=kb_version, text=text, conversation_id=conversation,
                          inventory_mode="none", allow_ai=allow_ai)
        )
        conversation = reply.conversation_id
    return reply


def evaluate_extended(
    pack: Path, out: Path, *, allow_ai: bool = False, repeats: int = 1, cases_path: Path | None = None, name: str = "extended"
) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=allow_ai)
    spec = json.loads((cases_path or CASES_PATH).read_text(encoding="utf-8"))
    results = []
    latencies = []
    paths: dict[str, int] = {}
    for case in spec["cases"]:
        runs = []
        for _ in range(repeats):
            started = time.monotonic()
            reply = asyncio.run(_run_case(env.service, env.kb_version, case, allow_ai))
            latencies.append((time.monotonic() - started) * 1000)
            ok, reasons, promises = _check_case(case, reply)
            runs.append({"ok": ok, "reasons": reasons, "unsupported_claims": promises, "answer": reply.answer,
                         "status": reply.status, "path": reply.answer_path, "model_id": reply.model_id})
            paths[reply.answer_path] = paths.get(reply.answer_path, 0) + 1
        results.append({"id": case["id"], "group": case["group"], "turns": case["turns"], "runs": runs,
                        "ok": all(r["ok"] for r in runs)})
    dialog_results = []
    batch = env.service.check_dialogs(
        DialogBatchRequest(dataset_id=DATASET, kb_version=env.kb_version,
                           dialogs=[DialogRow(id=d["id"], client=d["client"], manager=d["manager"]) for d in spec["dialogs"]])
    )
    for expected, verdict in zip(spec["dialogs"], batch.verdicts):
        ok = verdict.verdict == expected["verdict"]
        if ok and expected["verdict"] == "ERROR":
            ok = verdict.correct is not None and abs(float(verdict.correct) - expected["correct"]) <= 0.5
        dialog_results.append({"id": expected["id"], "expected": expected["verdict"], "got": verdict.verdict,
                               "correct": verdict.correct, "expected_correct": expected.get("correct"), "ok": ok})
    groups: dict[str, list[bool]] = {}
    for item in results:
        groups.setdefault(item["group"], []).append(item["ok"])
    total = len(results) + len(dialog_results)
    passed = sum(r["ok"] for r in results) + sum(d["ok"] for d in dialog_results)
    unconfirmed = sum(1 for r in results for run in r["runs"] if run["unsupported_claims"])
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "extended_synthetic_evaluation",
        "provenance": spec["provenance"],
        "ai": {"allowed": allow_ai, "runtime_status": env.ai_status},
        "answer_paths": paths,
        "live_acceptance": "not_applicable: hybrid strategy; deterministic answers are not model quality — use `live`",
        "kb_version": env.kb_version,
        "cases": total,
        "passed": passed,
        "accuracy": round(passed / total, 4),
        "unconfirmed_commercial_claims": unconfirmed,
        "repeats": repeats,
        "groups": {g: {"cases": len(v), "passed": sum(v)} for g, v in sorted(groups.items())},
        "dialogs": {"cases": len(dialog_results), "passed": sum(d["ok"] for d in dialog_results)},
        "latency_ms": {"p50": round(statistics.median(latencies), 1), "p95": round(_p95(latencies), 1), "turns": len(latencies)},
        "failures": [r for r in results if not r["ok"]] + [d for d in dialog_results if not d["ok"]],
        "results": results,
        "dialog_results": dialog_results,
    }
    report["case_file"] = (cases_path or CASES_PATH).name
    (out / f"{name}_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def measure_performance(pack: Path, out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=False)
    quote_times = []
    request = QuoteRequest(
        dataset_id=DATASET, catalog_product_id="steklo-6-prozrachnoe", kb_version=env.kb_version,
        dimensions={"length_mm": 450, "width_mm": 370}, quantity=1, processing={"kind": "euro_edge", "sides": "all"},
    )
    env.service.calculate_quote(request)  # warm-up
    for _ in range(100):
        started = time.perf_counter()
        env.service.calculate_quote(request)
        quote_times.append((time.perf_counter() - started) * 1000)
    turn_times = []
    texts = [row["question"] for row in read_rows(pack / "2_assistant_crm" / "questions_open.csv")]
    for index in range(30):
        started = time.perf_counter()
        asyncio.run(env.service.assistant_turn(AssistantTurn(dataset_id=DATASET, kb_version=env.kb_version,
                                                             text=texts[index % len(texts)], allow_ai=False)))
        turn_times.append((time.perf_counter() - started) * 1000)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "local_performance",
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(),
                    "processor": platform.processor() or "unknown"},
        "note": "Linux CI container, not the Windows reference laptop of TZ §27; network AI not included.",
        "quote_calculate_ms": {"n": 100, "p50": round(statistics.median(quote_times), 2), "p95": round(_p95(quote_times), 2),
                               "target_p95": 300},
        "deterministic_turn_ms": {"n": 30, "p50": round(statistics.median(turn_times), 2), "p95": round(_p95(turn_times), 2)},
        "ai_turn_p95": "NOT MEASURED: no provider key in this environment (target p95 ≤ 15 s over 30 live requests)",
    }
    (out / "performance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
