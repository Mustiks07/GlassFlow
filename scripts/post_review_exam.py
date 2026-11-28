"""Frozen independent exam against a running real GlassFlow HTTP application.

This evaluator never injects expected answers into the application. Local results
are not live acceptance. Missing public live provenance fails closed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MONEY = re.compile(r"(?<![\w])([\d][\d\s\u00a0\u202f]*(?:[.,]\d{1,2})?)\s*(?:₸|тенге|тг\b)", re.I)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf8"))


def money_values(text):
    values = []
    for match in MONEY.finditer(text):
        try:
            values.append(Decimal(re.sub(r"\s", "", match.group(1)).replace(",", ".")))
        except InvalidOperation:
            pass
    return values


def near(a, b):
    return abs(Decimal(a) - Decimal(b)) <= Decimal(".005")


def qualified_catalog_price(case, value, before, after):
    """Credit a supplementary catalog rate only with its unit/tier qualifier.

    The requested product, quantity and complete total are checked separately.
    This adjudicates evaluator false alarms, not the production verifier.
    """
    expected = case["expected"].get("quote", {})
    product_id = expected.get("product_id")
    if not product_id:
        return False
    frozen = json.loads((ROOT / "tests/post_review/ai_exam_v1.json").read_text(encoding="utf8"))
    kb_bytes = (ROOT / "inputs/PACK_for_teams/2_assistant_crm/ksm_knowledge_base.json").read_bytes()
    if hashlib.sha256(kb_bytes).hexdigest() != frozen["source_KB_sha256"]:
        raise ValueError("Independent oracle KB changed")
    kb = json.loads(kb_bytes)
    product = next(p.copy() for p in kb["товары"] if p["id"] == product_id)
    product.update(frozen["variants"][case["kb_variant"]]["products"].get(product_id, {}))
    before, after = before.lower(), after.lower()
    rules = [
        ("цена_за_м2_тг", bool(re.search(r"за\s*м[²2]", after))),
        ("цена_листа_тг", "лист" in before[-35:] or bool(re.search(r"за\s+(?:целый\s+)?лист", after))),
        ("цена_розница_тг", "розни" in before[-35:] or "розни" in after[:35]),
        ("цена_от_100_шт_тг", bool(re.search(r"от\s*100", before[-75:] + after[:35]))),
    ]
    if re.search(r"^\s*за\s+(?:одну\s+)?штук", after):
        field = "цена_от_100_шт_тг" if expected.get("quantity", 1) >= 100 else "цена_розница_тг"
        rules.append((field, True))
    return any(
        qualified and product.get(field) is not None and near(value, product[field])
        for field, qualified in rules
    )


def grade(case, reply):
    """Predeclared mechanical rubric; unsupported linguistic claims need manual review."""
    e = case["expected"]
    action = e["action"]
    text = reply.get("answer", "")
    low = text.lower().replace("ё", "е")
    q = reply.get("quote")
    reasons = []
    flags = {
        "wrong_total": False,
        "unnecessary_refusal": False,
        "incomplete": False,
        "fabrication": False,
        "unnecessary_question": False,
    }
    if action == "answer":
        expected = e["quote"]
        total = expected["total_tg"]
        if reply.get("status") != "answered":
            reasons.append("complete_request_not_answered")
            flags["unnecessary_refusal"] = True
        if q and (q.get("total_tg") is None or not near(q["total_tg"], total)):
            reasons.append("structured_total_missing_or_wrong")
            flags["wrong_total"] = True
        if q:
            for name, wanted in [
                ("catalog_product_id", expected["product_id"]),
                ("quantity", expected["quantity"]),
            ]:
                if q.get(name) != wanted:
                    reasons.append("wrong_" + name)
            if expected["dimensions"] is not None and q.get("dimensions") != expected["dimensions"]:
                reasons.append("wrong_dimensions")
        else:
            # Quote is optional in AssistantReply. Absence is not itself an
            # incorrect answer when the bound card and full factual total agree.
            card = reply.get("card") or {}
            params = card.get("confirmed_parameters") or {}
            if card.get("catalog_product_id") != expected["product_id"]:
                reasons.append("wrong_catalog_product_id")
            if str(params.get("quantity")) != str(expected["quantity"]):
                reasons.append("wrong_quantity")
            if expected["dimensions"] and any(
                str(params.get(k)) != str(v) for k, v in expected["dimensions"].items()
            ):
                reasons.append("dimensions_missing_or_wrong")
        numbers = money_values(text)
        if not any(near(n, total) for n in numbers):
            reasons.append("answer_omits_full_total")
            flags["incomplete"] = True
        allowed = [total, expected["unit_rate_tg"], *expected["components_tg"].values()]
        if "edge" in expected["components_tg"]:
            allowed += ["300", "400"] if case["kb_variant"] == "base" else ["317", "419"]
        unqualified = []
        for match in MONEY.finditer(text):
            value = money_values(match.group())[0]
            after = text[match.end() :]
            explicit_rate_unit = bool(
                re.search(r"^\s*за\s+(?:м[²2]|(?:целый\s+)?лист|(?:одну\s+)?штук)", after.lower())
            )
            qualified = qualified_catalog_price(case, value, text[: match.start()], after)
            if (explicit_rate_unit and not qualified) or (
                not explicit_rate_unit and not any(near(value, a) for a in allowed) and not qualified
            ):
                unqualified.append(value)
        if unqualified:
            reasons.append("unbound_or_wrong_currency_amount")
            flags["fabrication"] = True
        if e.get("no_extra_question") and reply.get("clarification"):
            reasons.append("unnecessary_clarification")
            flags["unnecessary_question"] = True
    elif action == "manager_handoff":
        if reply.get("status") != "manager_handoff" or "менеджер" not in low:
            reasons.append("required_manager_handoff_missing")
            flags["incomplete"] = True
        if q and q.get("total_tg") is not None:
            reasons.append("unknown_total_became_known")
            flags["fabrication"] = True
        allowed = e.get("allowed_known_prices", [])
        if any(not any(near(n, a) for a in allowed) for n in money_values(text)):
            reasons.append("price_claim_without_applicable_rate")
            flags["fabrication"] = True
        if e.get("allowed_price_context") == ["лист"] and any(
            re.search(r"^\s*за\s*м[²2]", text[m.end() :].lower()) for m in MONEY.finditer(text)
        ):
            reasons.append("sheet_price_misrepresented_as_area_rate")
            flags["fabrication"] = True
        question = (reply.get("clarification") or "").lower()
        if any(topic in question for topic in e.get("must_not_ask_known", [])):
            reasons.append("asks_known_parameter_for_unpriced_product")
            flags["unnecessary_question"] = True
    elif action == "clarification":
        question = reply.get("clarification") or ""
        combined = (question + " " + text).lower().replace("ё", "е")
        if reply.get("status") != "clarification" or not question:
            reasons.append("useful_clarification_missing")
            flags["incomplete"] = True
        if not any(topic in combined for topic in e["question_topics_any"]):
            reasons.append("clarification_does_not_resolve_target_ambiguity")
        if q and q.get("total_tg") is not None:
            reasons.append("ambiguous_product_resolved_without_customer")
            flags["fabrication"] = True
        if (
            reply.get("status") == "answered"
            and money_values(text)
            and any(t in e["question_topics_any"] for t in ["модел", "вариант", "формат"])
        ):
            flags["fabrication"] = True
    else:
        if any(word not in low for word in e.get("contains_all", [])):
            reasons.append("missing_required_rule")
        if e.get("contains_any") and not any(word in low for word in e["contains_any"]):
            reasons.append("missing_rule_context")
    if e.get("max_questions") is not None and text.count("?") > e["max_questions"]:
        reasons.append("too_many_questions")
        flags["unnecessary_question"] = True
    if any(word in low for word in e.get("forbidden_promises", [])):
        reasons.append("forbidden_commercial_promise")
        flags["fabrication"] = True
    return {"ok": not reasons, "reasons": reasons, **flags}


def provenance(reply, before, after, selected):
    delta = max(0, after.get("calls", 0) - before.get("calls", 0))
    success_delta = max(0, after.get("ok", 0) - before.get("ok", 0))
    path = reply.get("answer_path")
    declared = reply.get("provenance")
    origin = (declared or {}).get("origin") if isinstance(declared, dict) else None
    if origin in {"model", "deterministic", "cache", "fallback", "reuse"}:
        classification = origin
    elif path == "llm_tools" and delta == 0:
        classification = "cache_or_unverifiable"
    elif path == "llm_tools" and success_delta > 0:
        classification = "model"
    elif path == "fallback":
        classification = "fallback"
    else:
        classification = "deterministic"
    label = f"{reply.get('provider')}:{reply.get('model_id')}"
    confirmed = classification == "model" and delta > 0 and success_delta > 0 and label == selected
    return {
        "origin": classification,
        "selected_model_answer_confirmed": confirmed,
        "provider_calls_delta": delta,
        "ok_calls_delta": success_delta,
        "verifier_rejected_attempt": reply.get("verifier_status") == "unsupported_replaced",
        "declared_provenance": declared,
    }


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def evaluate(args):
    oracle_bytes = args.oracle.read_bytes()
    exam = json.loads(oracle_bytes)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "reviewer_code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "oracle_sha256": hashlib.sha256(oracle_bytes).hexdigest(),
        "mode": args.mode,
        "rubric": "mechanical action+bound structured total+currency+completeness+refusal; manual semantic review still required",
        "rubric_revision": "1.1-adjudicated-before-candidate",
        "baseline_product_commit": exam["baseline_commit"],
        "results": [],
        "quality_results": [],
        "live_acceptance": {"status": "NOT_RUN"},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    cases = [c for c in exam["cases"] if not args.ids or c["id"] in args.ids]
    with httpx.Client(base_url=args.base.rstrip("/"), timeout=args.timeout) as client:
        client.get("/api/v1/session").raise_for_status()
        ready = client.get("/api/v1/ready")
        ready.raise_for_status()
        report["readiness"] = ready.json()
        profile = client.get("/api/v1/assistant/ai-status").json()
        usage0 = client.get("/api/v1/assistant/usage").json()
        report["profile"] = profile
        selected = f"{profile.get('provider')}:{profile.get('model_id')}"
        spec = client.get("/openapi.json").json()
        fields = spec.get("components", {}).get("schemas", {}).get("AssistantTurn", {}).get("properties", {})
        model_first_supported = "execution_mode" in fields
        report["public_capabilities"] = {
            "model_first": model_first_supported,
            "legacy_cache_hit_public": "cache_hit"
            in spec.get("components", {}).get("schemas", {}).get("AssistantReply", {}).get("properties", {}),
        }
        if args.mode == "live" and (not model_first_supported or not profile.get("key_configured")):
            report["live_acceptance"] = {
                "status": "BLOCKED",
                "reason": "Public model_first capability or configured selected model missing; no paid/profile mutation attempted",
            }
            write_json(args.out / "report.json", report)
            return report
        source = client.post(
            "/api/v1/datasets/demo", headers={"Idempotency-Key": f"independent-source:{time.time_ns()}"}
        )
        source.raise_for_status()
        source = source.json()
        base_kb = json.loads(
            (ROOT / "inputs/PACK_for_teams/2_assistant_crm/ksm_knowledge_base.json").read_text(
                encoding="utf8"
            )
        )
        datasets = {}
        for variant in sorted(
            {c["kb_variant"] for c in cases} | {q["kb_variant"] for q in exam["quality_cases"]}
        ):
            response = client.post(
                f"/api/v1/datasets/{source['dataset_id']}/working-copy",
                json={"name": f"Independent exam {variant}"},
                headers={"Idempotency-Key": f"exam-copy:{variant}:{time.time_ns()}"},
            )
            response.raise_for_status()
            dataset = response.json()
            dsid = dataset["dataset_id"]
            if variant != "base":
                kb = copy.deepcopy(base_kb)
                changes = exam["variants"][variant]
                for p in kb["товары"]:
                    p.update(changes["products"].get(p["id"], {}))
                for rule in kb["правила"]:
                    for before, after in changes["rule_replacements"].get(rule["id"], {}).items():
                        rule["правило"] = rule["правило"].replace(before, after)
                response = client.post(
                    f"/api/v1/datasets/{dsid}/kb",
                    data={"expected_version": "0"},
                    files={
                        "file": (
                            "review-kb.json",
                            json.dumps(kb, ensure_ascii=False).encode("utf8"),
                            "application/json",
                        )
                    },
                    headers={"Idempotency-Key": f"exam-kb:{variant}:{time.time_ns()}"},
                )
                response.raise_for_status()
            snapshot = client.get(f"/api/v1/datasets/{dsid}").json()
            datasets[variant] = {
                "dataset_id": dsid,
                "kb_version": snapshot["kb_version"],
                "source_hashes": snapshot["source_hashes"],
            }
        report["datasets"] = datasets
        for case in cases:
            scope = datasets[case["kb_variant"]]
            control = None
            if case["expected"]["action"] == "answer":
                canonical = case["expected"]["quote"]
                response = client.post(
                    "/api/v1/quotes",
                    json={
                        "dataset_id": scope["dataset_id"],
                        "kb_version": scope["kb_version"],
                        "catalog_product_id": canonical["product_id"],
                        "dimensions": canonical["dimensions"],
                        "quantity": canonical["quantity"],
                        "processing": canonical["processing"],
                        "price_basis": canonical["basis"],
                        "inventory_mode": "none",
                    },
                )
                control = {
                    "http_status": response.status_code,
                    "reply": response.json(),
                    "independent_oracle_total_tg": canonical["total_tg"],
                    "ok": response.status_code == 200
                    and response.json().get("total_tg") is not None
                    and near(response.json()["total_tg"], canonical["total_tg"]),
                }
            repeat_count = exam["critical_repeats"] if case["critical"] and not args.once else 1
            for repeat in range(repeat_count):
                payload = dict(
                    dataset_id=scope["dataset_id"],
                    kb_version=scope["kb_version"],
                    text=case["question"],
                    inventory_mode=case["inventory_mode"],
                    allow_ai=args.mode == "live",
                )
                if args.mode == "live":
                    payload["execution_mode"] = "model_first"
                before = client.get("/api/v1/assistant/usage").json()
                started = time.perf_counter()
                response = client.post("/api/v1/assistant/turns", json=payload)
                latency = round((time.perf_counter() - started) * 1000, 2)
                after = client.get("/api/v1/assistant/usage").json()
                if response.status_code != 200:
                    result = {
                        "case_id": case["id"],
                        "repeat": repeat,
                        "family": case["family"],
                        "ok": False,
                        "http_status": response.status_code,
                        "error": response.text[:1000],
                        "latency_ms": latency,
                    }
                else:
                    reply = response.json()
                    result = {
                        "case_id": case["id"],
                        "repeat": repeat,
                        "family": case["family"],
                        "latency_ms": latency,
                        **grade(case, reply),
                        "reply": reply,
                        "canonical_quote_control": control,
                        "provenance": provenance(reply, before, after, selected),
                    }
                report["results"].append(result)
                with (args.out / "progress.jsonl").open("a", encoding="utf8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                if len(report["results"]) % 10 == 0:
                    print(f"{len(report['results'])} turns completed", flush=True)
        for case in exam["quality_cases"]:
            scope = datasets[case["kb_variant"]]
            response = client.post(
                "/api/v1/quality/check",
                json={
                    "dataset_id": scope["dataset_id"],
                    "kb_version": scope["kb_version"],
                    "id": case["id"],
                    "client": case["client"],
                    "manager": case["manager"],
                },
            )
            reply = response.json()
            expect = case["expected"]
            ok = response.status_code == 200 and reply.get("verdict") == expect["verdict"]
            ok = ok and (
                reply.get("correct") is None
                if expect["correct"] is None
                else reply.get("correct") is not None and near(reply["correct"], expect["correct"])
            )
            report["quality_results"].append({"case_id": case["id"], "ok": bool(ok), "reply": reply})
        usage = client.get("/api/v1/assistant/usage").json()
        report["usage_after"] = usage
        report["provider_calls_during_exam"] = usage["calls"] - usage0["calls"]
    results = report["results"]
    ok = sum(bool(r["ok"]) for r in results)
    first = [r for r in results if r["repeat"] == 0]
    report["summary"] = {
        "turns": len(results),
        "distinct_cases": len(cases),
        "correct": ok,
        "accuracy": round(ok / len(results), 4) if results else None,
        "distinct_correct": sum(r["ok"] for r in first),
        "distinct_accuracy": round(sum(r["ok"] for r in first) / len(first), 4) if first else None,
        "quality_correct": sum(r["ok"] for r in report["quality_results"]),
        "quality_total": len(report["quality_results"]),
        "failures_by_family": dict(Counter(r["family"] for r in results if not r["ok"])),
        "origins": dict(Counter(r.get("provenance", {}).get("origin", "http_error") for r in results)),
        "latency_p50_ms": percentile([r["latency_ms"] for r in results], 0.5),
        "latency_p95_ms": percentile([r["latency_ms"] for r in results], 0.95),
        **{
            f"{k}_count": sum(bool(r.get(k)) for r in results)
            for k in ["fabrication", "unnecessary_refusal", "incomplete", "unnecessary_question"]
        },
    }
    if args.mode == "live":
        confirmed = [r for r in results if r.get("provenance", {}).get("selected_model_answer_confirmed")]
        attempts = confirmed + [
            r for r in results if r.get("provenance", {}).get("verifier_rejected_attempt")
        ]
        report["live_acceptance"] = {
            "status": "MANUAL_REVIEW_REQUIRED"
            if len(confirmed) == len(results)
            and len(cases) >= 60
            and ok / len(results) >= 0.95
            and report["summary"]["distinct_accuracy"] >= 0.95
            and not args.once
            and not report["summary"]["fabrication_count"]
            else "FAIL_OR_PARTIAL",
            "confirmed_model_answers": len(confirmed),
            "model_attempts": len(attempts),
            "model_accuracy": round(sum(r["ok"] for r in confirmed) / len(attempts), 4) if attempts else None,
            "cache_fallback_deterministic_do_not_raise_model_score": True,
            "manual_review_required": True,
        }
    write_json(args.out / "report.json", report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18173")
    p.add_argument("--oracle", type=Path, default=ROOT / "tests/post_review/ai_exam_v1.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mode", choices=["local", "live"], default="local")
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--once", action="store_true")
    p.add_argument("--ids", nargs="*")
    args = p.parse_args()
    report = evaluate(args)
    print(
        json.dumps(
            {"summary": report.get("summary"), "live_acceptance": report["live_acceptance"]},
            ensure_ascii=True,
            indent=2,
        )
    )
    if args.mode == "live" and report["live_acceptance"]["status"] != "PASS":
        raise SystemExit(2 if report["live_acceptance"]["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    main()
