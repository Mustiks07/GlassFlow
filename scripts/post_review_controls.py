"""Independent preregistered geometry and mixture boundaries over real HTTP."""

import argparse
import csv
import io
import json
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
    pack = ROOT / "inputs/PACK_for_teams"
    paths = [
        "1_ostatki/materials.csv",
        "1_ostatki/stock_open.csv",
        "1_ostatki/orders_open.csv",
        "2_assistant_crm/applications_open.csv",
        "2_assistant_crm/questions_open.csv",
        "2_assistant_crm/dialogs_open.csv",
        "2_assistant_crm/ksm_knowledge_base.json",
    ]
    reader = csv.DictReader(io.StringIO((pack / paths[3]).read_text(encoding="utf-8-sig")))
    template = next(reader)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    index = 0
    for manager, group, size, sold in [
        ("M1", "X", 80, 32),
        ("M1", "Y", 20, 18),
        ("M2", "X", 20, 6),
        ("M2", "Y", 80, 64),
    ]:
        for n in range(size):
            index += 1
            writer.writerow(
                template
                | {
                    "app_id": f"TEST-MIX-{index}",
                    "client_id": f"TEST-C-{index}",
                    "manager": manager,
                    "группа_товара": group,
                    "продано": str(int(n < sold)),
                    "день_года": "100",
                    "канал": "WhatsApp",
                    "тип_клиента": "частный",
                }
            )
    replacements = {
        "stock_open.csv": "remnant_id,material_id,длина_мм,ширина_мм,возраст_дней,дефект,место\nTEST-SMALL,clear-6,100,80,1,0,TEST-A\nTEST-RARE,clear-6,200,150,1,0,TEST-B\n".encode(),
        "orders_open.csv": "order_id,part_id,material_id,длина_мм,ширина_мм,премиум,тип_изделия\nTEST-KNOWN,TEST-PENDING,clear-6,180,130,0,полка\n".encode(),
        "applications_open.csv": stream.getvalue().encode(),
    }
    files = [
        ("files", (Path(name).name, replacements.get(Path(name).name, (pack / name).read_bytes())))
        for name in paths
    ]
    report = {
        "kind": "SYNTHETIC preregistered inputs, actual HTTP/SQLite/solver; not observed demand",
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
            response = c.post(
                "/api/v1" + path,
                json=body,
                headers={"Idempotency-Key": f"independent-control:{time.time_ns()}"},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

        preview = post("/imports/preview", files=files)
        assert not preview["errors"], preview
        source = post(
            f"/imports/{preview['import_id']}/commit",
            {"name": "SYNTHETIC independent geometry/mixture boundaries"},
        )
        d = source["dataset_id"]
        report["dataset_id"] = d
        compare = post(
            "/analytics/comparable",
            {"dataset_id": d, "dimensions": ["product_group"], "managers": ["M1", "M2"]},
        )
        rates = {
            g["dimensions"]["product_group"]: {m["manager"]: m["conversion"] for m in g["managers"]}
            for g in compare["groups"]
        }
        expected = {"X": {"M1": (32, 80), "M2": (6, 20)}, "Y": {"M1": (18, 20), "M2": (64, 80)}}
        check(
            "N08_exact_stratum_counts",
            all(
                rates[g][m]["numerator"] == n and rates[g][m]["denominator"] == den
                for g, ms in expected.items()
                for m, (n, den) in ms.items()
            )
            and compare["matched_application_count"] == 200
            and bool(compare.get("caveat_ru")),
            compare,
        )
        rejected = post(
            "/analytics/questions",
            {"dataset_id": d, "question": "DROP TABLE applications; invent a manager ranking"},
        )
        check("N08_query_not_arbitrary_SQL", rejected["status"] == "clarification", rejected)
        results = []
        for quantity in (1, 2):
            result = post(
                "/cutting/scarcity",
                {
                    "dataset_id": d,
                    "material_id": "clear-6",
                    "dimensions": {"length_mm": 60, "width_mm": 50},
                    "quantity": quantity,
                    "budget_ms": 1000,
                },
            )
            results.append(result)
        check(
            "N03_joint_quantity_boundary",
            results[0]["baseline_order_preserved"]
            and results[1]["baseline_order_preserved"]
            and not results[1]["explanations"]
            and all(e["known_order_id"] == "TEST-KNOWN" for e in results[0]["explanations"]),
            results,
        )
    print(json.dumps({"checks": [{"name": x["name"], "ok": x["ok"]} for x in report["checks"]]}, indent=2))


if __name__ == "__main__":
    main()
