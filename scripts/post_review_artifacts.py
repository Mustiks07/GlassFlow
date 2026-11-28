"""Read-only native CSV/source/GET audit. Never configures or mutates runtime."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import httpx

HEADERS = {
    "solution.csv": ["part_id", "remnant_id", "x_mm", "y_mm", "rot"],
    "answers.csv": ["id", "answer"],
    "picks.csv": ["app_id"],
    "verdicts.csv": ["id", "verdict", "correct"],
    "sale_cards.csv": ["remnant_id", "title", "price_tg", "description", "target_buyer", "top3_buyers"],
    "buyers_top50.csv": ["name", "city", "category", "url", "why", "source_url", "score"],
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    db = sqlite3.connect((args.data / "glassflow.db").resolve().as_uri() + "?mode=ro", uri=True)
    result = {
        "kind": "Read-only actual native exported files, source SQLite and GET byte checks; no provider/config/POST",
        "snapshots": [],
    }
    with httpx.Client(base_url=args.base, timeout=30) as c:
        # Establish the normal local read session; never persist or print its token.
        c.get("/api/v1/session").raise_for_status()
        for path in sorted((args.data / "exports").rglob("manifest.json")):
            manifest = json.loads(path.read_text(encoding="utf8"))
            item = {
                "run_id": manifest["run_id"],
                "export_id": manifest["export_id"],
                "status": manifest["status"],
                "build_commit": manifest["build_info"]["commit"],
                "files": {},
                "issues": [],
            }
            rows = {}
            for name, expected_hash in manifest["files"].items():
                content = (path.parent / name).read_bytes()
                sha = hashlib.sha256(content).hexdigest()
                response = c.get(f"/api/v1/runs/{manifest['run_id']}/files/{manifest['export_id']}/{name}")
                reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""), strict=True)
                rows[name] = list(reader)
                check = {
                    "bytes": len(content),
                    "rows": len(rows[name]),
                    "sha256": sha,
                    "manifest_hash_matches": sha == expected_hash,
                    "GET_HTTP_status": response.status_code,
                    "GET_same_bytes": response.status_code == 200 and response.content == content,
                    "exact_header": reader.fieldnames == HEADERS[name],
                    "UTF8_no_BOM": not content.startswith(b"\xef\xbb\xbf"),
                }
                item["files"][name] = check
                if not all(
                    check[k]
                    for k in ["manifest_hash_matches", "GET_same_bytes", "exact_header", "UTF8_no_BOM"]
                ):
                    item["issues"].append("file_contract:" + name)
            if manifest["status"] == "ready":
                sources = dict(
                    db.execute(
                        "SELECT kind, content FROM source_files WHERE dataset_id=?", (manifest["dataset_id"],)
                    ).fetchall()
                )
                source = {
                    k: list(csv.DictReader(io.StringIO(v.decode("utf-8-sig"))))
                    for k, v in sources.items()
                    if k != "kb"
                }
                stock = {r["remnant_id"]: r for r in source["stock"]}
                materials = {r["material_id"]: r for r in source["materials"]}
                buyers = {r["name"] for r in rows["buyers_top50.csv"]}
                used = {r["remnant_id"] for r in rows["solution.csv"] if r["remnant_id"] != "NEW"}
                checks = {
                    "solution_exact_parts": {r["part_id"] for r in rows["solution.csv"]}
                    == {r["part_id"] for r in source["orders"]},
                    "solution_original_or_NEW": all(
                        r["remnant_id"] == "NEW" or r["remnant_id"] in stock for r in rows["solution.csv"]
                    ),
                    "answers_exact_IDs": {r["id"] for r in rows["answers.csv"]}
                    == {r["id"] for r in source["questions"]},
                    "verdicts_exact_IDs": {r["id"] for r in rows["verdicts.csv"]}
                    == {r["id"] for r in source["dialogs"]},
                    "picks25_unique_members": len(rows["picks.csv"])
                    == len({r["app_id"] for r in rows["picks.csv"]})
                    == 25
                    and {r["app_id"] for r in rows["picks.csv"]}
                    <= {r["app_id"] for r in source["applications"]},
                    "buyers50_unique": len(rows["buyers_top50.csv"]) == len(buyers) == 50,
                    "cards5_original_free": len(rows["sale_cards.csv"])
                    == len({r["remnant_id"] for r in rows["sale_cards.csv"]})
                    == 5
                    and all(
                        r["remnant_id"] in stock and r["remnant_id"] not in used
                        for r in rows["sale_cards.csv"]
                    ),
                }
                details = []
                for card in rows["sale_cards.csv"]:
                    names = card["top3_buyers"].split(";")
                    piece = stock[card["remnant_id"]]
                    rate = Decimal(materials[piece["material_id"]]["цена_нового_стекла_тг_за_м2"])
                    full = Decimal(piece["длина_мм"]) * Decimal(piece["ширина_мм"]) * rate / 1000000
                    price = Decimal(card["price_tg"])
                    details.append(
                        {
                            "remnant_id": card["remnant_id"],
                            "three_distinct_registry_buyers": len(set(names)) == 3 and set(names) <= buyers,
                            "price_in_30_to_70_percent": full * Decimal(".30")
                            <= price
                            <= full * Decimal(".70"),
                            "price_tg": str(price),
                        }
                    )
                checks["cards_matching_names_and_price_bounds"] = all(
                    r["three_distinct_registry_buyers"] and r["price_in_30_to_70_percent"] for r in details
                )
                item["domain_checks"], item["cards"] = checks, details
                item["issues"] += [k for k, v in checks.items() if not v]
            result["snapshots"].append(item)
    db.close()
    result["ok"] = bool(result["snapshots"]) and all(not s["issues"] for s in result["snapshots"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "snapshots": [
                    {
                        "status": s["status"],
                        "files": {n: v["rows"] for n, v in s["files"].items()},
                        "issues": s["issues"],
                    }
                    for s in result["snapshots"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
