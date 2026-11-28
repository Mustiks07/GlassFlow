"""Reproducible C1 -> platform evidence conversion, preserving C1 originals byte-for-byte.

Use --verify-sources to refresh a separate HTTP report. Applications are explicit
integrator-reviewed design assumptions, not evidence of demand or purchase intent.
"""

import argparse
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUYERS = ROOT / "data/buyers"
REVIEWED = {
    "B01": "Изготовление индивидуальной, модульной и корпоративной мебели; Астана, ул. Ташенова 19. Подтверждено на публичной странице CATRINE.",
    "B02": "Собственное производство мебели в Астане; шкафы со стеклом и зеркалами, витрины и полки. Подтверждено на публичной странице Astana MG.",
    "B03": "Собственное производство корпусной мебели в Астане; шкафы, полки, журнальные столики и зеркала для прихожей. Подтверждено на публичной странице DalaSK.",
}


def convert():
    original = BUYERS / "evidence.json"
    source = json.loads(original.read_text(encoding="utf-8"))
    records = []
    for buyer in source["buyers"]:
        activity = REVIEWED.get(buyer["id"])
        checked = "2026-11-28" if activity else buyer["verified_at"][:10]
        applications = []
        if activity:
            for application, materials in (("furniture_insert", ["clear-4", "clear-6", "clear-8"]),
                                            ("mirror_interior", ["mirror-4"])):
                applications.append(dict(application=application, material_ids=materials,
                    min_dimensions=dict(length_mm=100, width_mm=100),
                    max_dimensions=dict(length_mm=2000, width_mm=1500), requires_cutting=True,
                    dimensions_basis="Проектное допущение интегратора для небольших мебельных вставок: 100×100–2000×1500 мм; материал/толщина и конечный размер требуют согласования. Сайт не заявляет такую потребность или диапазон закупки.",
                    activity=activity, source_url=buyer["source_url"], checked_at=checked))
        records.append(dict(name=buyer["name"], city=buyer["city"], profile=activity or buyer["category"],
            source_url=buyer["source_url"], checked_at=checked,
            reviewer="Mustiks07 / GPT Pro integration" if activity else source["reviewer"],
            confirmation=activity or f"C1 evidence: {buyer['page_title']}; city_confirmed={buyer['city_confirmed']}; profile_keyword={buyer['profile_keyword']}",
            entity_id=buyer["id"], applications=applications,
            verification_scope="integration_public_page_review" if activity else "C1_report_not_independently_accepted"))
    payload = dict(records=records, dedupe_policy=source["dedup_rule"],
        source_evidence_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        source_csv_sha256=hashlib.sha256((BUYERS / "buyers_candidate.csv").read_bytes()).hexdigest(),
        transform_version="c1-platform-v1", application_policy="Explicit project assumptions; no confirmed interest",
        integration_reviewed_ids=list(REVIEWED))
    destination = BUYERS / "evidence.platform.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def verify():
    spec = importlib.util.spec_from_file_location("buyer_verifier", BUYERS / "verify_buyers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with ThreadPoolExecutor(6) as pool:
        report = list(pool.map(module.check, module.reg.ROWS))
    target = BUYERS / "integration-source-checks.json"
    target.write_text(json.dumps(dict(checked_at="2026-11-28", checks=report,
        summary={"total": len(report), "passed": sum(bool(r.get("ok")) for r in report)}),
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(report), "passed": sum(bool(r.get("ok")) for r in report),
                      "failed_ids": [r["id"] for r in report if not r.get("ok")]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-sources", action="store_true")
    args = parser.parse_args()
    result = convert()
    print(f"Converted {len(result['records'])} records; C1 originals preserved")
    if args.verify_sources:
        verify()
