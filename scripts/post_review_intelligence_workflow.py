"""Actual local review queue, explicit KB preview and stale correction boundaries."""

import argparse
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "kind": "Actual HTTP local KB/correction boundary; no provider/no outbound messages",
        "checks": [],
    }

    def check(name, ok, evidence):
        report["checks"].append({"name": name, "ok": bool(ok), "evidence": evidence})
        (args.out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )

    with httpx.Client(base_url=args.base, timeout=120) as c:
        c.get("/api/v1/session").raise_for_status()

        def post(path, body=None, **kwargs):
            r = c.post(
                "/api/v1" + path,
                json=body,
                headers={"Idempotency-Key": f"review-workflow:{time.time_ns()}"},
                **kwargs,
            )
            r.raise_for_status()
            return r.json()

        source = post("/datasets/demo")
        workspace = post(f"/datasets/{source['dataset_id']}/working-copy", {})
        d = workspace["dataset_id"]
        version = c.get(f"/api/v1/datasets/{d}").json()["kb_version"]
        report["dataset_id"] = d
        replies = []
        for text in [
            "Выполняете ли монтаж стекла?",
            "Стекло 6 мм прозрачное 613×407 мм, кромка только по выбранным сторонам",
            "Какова цена рифленого прозрачного стекла 8 мм за квадратный метр?",
        ]:
            replies.append(
                post(
                    "/assistant/turns",
                    {
                        "dataset_id": d,
                        "kb_version": version,
                        "text": text,
                        "allow_ai": False,
                        "inventory_mode": "none",
                    },
                )
            )
        items = c.get("/api/v1/assistant/review-items", params={"dataset_id": d}).json()
        check(
            "N07_policy_missing_KB_separate",
            {r["category"] for r in items} >= {"correct_policy", "missing_parameter", "kb_fact"},
            {"items": items, "replies": replies},
        )
        body = {
            "dataset_id": d,
            "kb_version": version,
            "id": "TEST-DRAFT-PRICE",
            "client": "Стекло 6 мм прозрачное: какая цена за м²?",
            "manager": "Цена 1111 тг за м².",
        }
        draft = post("/dialogs/corrections", body)
        replay = post("/dialogs/corrections", body)
        check(
            "N19_bound_unit_draft_and_idempotency",
            draft == replay
            and draft["status"] == "DRAFT_VERIFIED"
            and draft["applicable_price_tg"] == "8000"
            and draft["price_meaning"] == "per_m2"
            and bool(draft["evidence"])
            and draft["requires_human_review"],
            draft,
        )
        ambiguous = post(
            "/dialogs/corrections", body | {"id": "TEST-DRAFT-AMBIGUOUS", "client": "Цена зеркала 4 мм?"}
        )
        check(
            "N19_ambiguous_draft_not_invented",
            ambiguous["status"] == "NEEDS_REVIEW" and ambiguous["answer"] is None,
            ambiguous,
        )
        old_head = c.get(f"/api/v1/datasets/{d}/kb").json()
        kb = json.loads(
            (ROOT / "inputs/PACK_for_teams/2_assistant_crm/ksm_knowledge_base.json").read_text(
                encoding="utf8"
            )
        )
        for product in kb["товары"]:
            if product["id"] == "steklo-6-prozrachnoe":
                product["цена_за_м2_тг"] = 9127
        content = json.dumps(kb, ensure_ascii=False).encode()
        preview = post(
            f"/assistant/review-items/{items[0]['item_id']}/kb-preview",
            {"dataset_id": d, "expected_kb_version": version, "proposed_content": content.decode()},
        )
        check(
            "N07_preview_read_only_explicit_confirmation",
            preview["requires_explicit_human_confirmation"] is True
            and c.get(f"/api/v1/datasets/{d}/kb").json() == old_head,
            preview,
        )
        applied = post(
            f"/datasets/{d}/kb",
            data={"expected_version": str(old_head["version"])},
            files={"file": ("kb-review.json", content, "application/json")},
        )
        assert applied["version"] == old_head["version"] + 1
        old = c.get(f"/api/v1/dialogs/corrections/{draft['draft_id']}", params={"dataset_id": d})
        old_json = old.json()
        check(
            "N19_old_draft_not_presented_current_after_KB_change",
            old.status_code == 409
            or old_json.get("stale") is True
            or old_json.get("status") != "DRAFT_VERIFIED",
            {
                "http_status": old.status_code,
                "old_draft_view": old_json,
                "current_KB": c.get(f"/api/v1/datasets/{d}").json()["kb_version"],
            },
        )
        fresh_version = c.get(f"/api/v1/datasets/{d}").json()["kb_version"]
        fresh = post("/dialogs/corrections", body | {"kb_version": fresh_version})
        check(
            "N19_rechecked_draft_new_price",
            fresh["draft_id"] != draft["draft_id"] and fresh["applicable_price_tg"] == "9127",
            fresh,
        )
        historical = c.get("/api/v1/dialogs/corrections", params={"dataset_id": d}).json()
        historical_old = next(row for row in historical if row["draft_id"] == draft["draft_id"])
        check(
            "N19_historical_list_marks_stale_without_rewriting_price",
            historical_old.get("is_current") is False
            and historical_old.get("current_kb_version") == fresh_version
            and historical_old["applicable_price_tg"] == "8000",
            historical_old,
        )
        unknown_identity_checks(c, post, check, d, fresh_version)
    print(json.dumps({"checks": [{"name": r["name"], "ok": r["ok"]} for r in report["checks"]]}, indent=2))


def unknown_identity_checks(client, post, check, dataset, version):
    money = re.compile(r"\d[\d\s,.]*\s*(?:₸|тенге|тг\b)", re.I)
    replies = []
    for identity in ("NEXUS-CLIENT-87021", "LQ8V721", "ТЕСТФИКС-717", "981732"):
        reply = post(
            "/assistant/turns",
            {
                "dataset_id": dataset,
                "kb_version": version,
                "text": f"Нужно неизвестное крепление {identity}, 3 шт. Какая цена?",
                "allow_ai": False,
                "inventory_mode": "none",
            },
        )
        replies.append(reply)
    check(
        "P1_unknown_changed_IDs_never_select_or_price_generic_hardware",
        all(
            r["status"] in {"clarification", "manager_handoff"}
            and r["quote"] is None
            and r["card"]["catalog_product_id"] is None
            and not money.search(r["answer"])
            for r in replies
        ),
        replies,
    )
    first = post(
        "/assistant/turns",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "text": "Прозрачное стекло 6 мм 527×361 мм, 2 шт., без обработки",
            "allow_ai": False,
            "inventory_mode": "none",
        },
    )
    unknown = post(
        "/assistant/turns",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "conversation_id": first["conversation_id"],
            "text": "Теперь нужно неизвестное крепление VX-KUND-561, 3 шт.",
            "allow_ai": False,
            "inventory_mode": "none",
        },
    )
    followup = post(
        "/assistant/turns",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "conversation_id": first["conversation_id"],
            "text": "А если 4 штуки?",
            "allow_ai": False,
            "inventory_mode": "none",
        },
    )
    old = first["quote"]
    rejected = client.post(
        f"/api/v1/quotes/{old['quote_id']}/confirm",
        json={"dataset_id": dataset, "expected_revision": old["revision"], "confirmed_by": "TEST_REVIEWER"},
    )
    check(
        "P1_unknown_retires_prior_quote_and_context",
        all(r["quote"] is None and r["card"]["catalog_product_id"] is None for r in [unknown, followup])
        and rejected.status_code == 409,
        {
            "first": first,
            "unknown": unknown,
            "followup": followup,
            "old_confirmation_http_status": rejected.status_code,
        },
    )
    batch = post(
        "/assistant/batch",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "allow_ai": False,
            "questions": [
                {
                    "id": "TEST-CHANGED-UNKNOWN-ID",
                    "question": "Нужна цена неизвестного крепления BLINDREG-449, без известной модели.",
                }
            ],
        },
    )
    check(
        "P1_unknown_batch_no_model_guess_or_price",
        batch["answers"][0]["status"] in {"clarification", "manager_handoff"}
        and not money.search(batch["answers"][0]["answer"]),
        batch,
    )
    qa = post(
        "/quality/check",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "id": "TEST-WRONG-KNOWN-RATE",
            "client": "Какова цена неизвестного крепления BLINDREG-449?",
            "manager": "Подвес для скрытого крепления зеркала — 400 тг за штуку.",
        },
    )
    check(
        "P1_unknown_quality_does_not_whitelist_other_product_price",
        qa["verdict"] == "NEEDS_REVIEW" and qa["correct"] is None,
        qa,
    )
    known = post(
        "/assistant/turns",
        {
            "dataset_id": dataset,
            "kb_version": version,
            "text": "Сенсорный переключатель YZKJ-F2FTC, 3 шт., остальные параметры неизвестны. Цена?",
            "allow_ai": False,
            "inventory_mode": "none",
        },
    )
    check(
        "P1_known_explicit_SKU_not_unnecessarily_refused",
        known["status"] == "answered" and known["card"]["catalog_product_id"] == "sensor-dvoynoy-yzkj-f2ftc",
        known,
    )


if __name__ == "__main__":
    main()
