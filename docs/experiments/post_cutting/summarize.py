"""Render every frozen paired result; no filtering or objective retuning."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent


def render():
    report = json.loads((HERE / "comparison.json").read_text(encoding="utf8"))
    rows = report["trials"]
    assert len(rows) == 24 and "decisions" in report, "Do not summarize an incomplete study as complete"
    lines = [
        "# Bounded C2 research decisions",
        "",
        "Protocol v2 frozen at bb7f480 before trials; corrected runtime baseline a079a28. "
        "Six changed synthetic snapshots, seeds7/19/41, all four variants, fresh process each:20s, "
        "one OS CPU, workers1,1GiB sampled native memory ceiling. Developer Windows10, not clean Windows11 "
        "or the jury reference machine. Independent reviewer exam was not read.",
        "",
        "Old interrupted9s pilot (11 observations) is retained in pilot-9s-partial.json. It exposed "
        "the existing first-complete/minimum-free defect; its results are not silently replaced. "
        "V2 reuses its mathematical inputs openly; this is a regression comparison, not a hidden exam.",
        "",
        "| Family | Seed | Variant | Area mm² | Full orders | Free originals | Locations | First complete ms | Native peak MiB | Process stop |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        chosen = row["selected"] or {}
        first = row["first_valid_seconds"]
        lines.append(
            f"| {row['family']} | {row['seed']} | {row['variant']} | {chosen.get('area')} | "
            f"{chosen.get('full_orders')} | {chosen.get('free_original')} | {chosen.get('locations')} | "
            f"{first * 1000:.2f} | {row['peak_rss_bytes'] / 2**20:.2f} | {row['process_stop']} |"
        )
    lines += ["", "## Decisions against unchanged preregistered thresholds", ""]
    for name, decision in report["decisions"].items():
        candidates = [r for r in rows if r["variant"] == name]
        deltas = decision["area_deltas_mm2"]
        wins = {
            family: sum(d > 0 for r, d in zip(candidates, deltas) if r["family"] == family)
            for family in ("dense", "mixed")
        }
        lines.append(
            f"- {name}: **{'candidate qualifies, still requires root/reviewer promotion' if decision['promote'] else 'NO PROMOTION'}**. "
            f"Area deltas in paired dense7/19/41,mixed7/19/41: `{deltas}` mm²; wins `{wins}`; "
            f"median delta {statistics.median(deltas):.0f}mm²; common guards {decision['guards_passed']}."
        )
    locations_better = sum(
        r["selected"]["locations"]
        < next(
            b
            for b in rows
            if b["variant"] == "baseline" and b["family"] == r["family"] and b["seed"] == r["seed"]
        )["selected"]["locations"]
        for r in rows
        if r["variant"] == "N12_locations"
    )
    exercised = sum(
        (r["finished"] or {}).get("stats", {}).get("directed_moves", 0) > 0
        for r in rows
        if r["variant"] == "N11_directed"
    )
    lines += [
        "",
        f"N12 improved actual location count in {locations_better}/6 pairs (required>=3); actual location "
        "labels are not travel distance or human time savings. N11 directed moves were observed in "
        f"{exercised}/6 final diagnostic reports; a short budget can end before this phase, so no claim "
        "of benefit on unexercised cases. N14 retains one global master; the study does not license "
        "naive independent component merging.",
        "",
        f"All {sum(r['valid_complete'] for r in rows)}/24 selected complete incumbents independently "
        "passed the unchanged C2 geometry validator and requested free>=5. Only events at<=20s were selected; "
        "late final returns/diagnostics are recorded but cannot improve the selected score. Native OS "
        "PeakWorkingSet includes native memory; it is not tracemalloc or a universal total allocation bound. "
        "Other developer-host activity is not claimed absent. No pool optimum is a global optimum.",
        "",
        "Full trial metrics, hashes, actual solver stop reasons and process stops are in comparison.json. "
        "Placement rows were independently validated during each trial but are not retained in that scalar "
        "report; rerun compare.py for a new measured run. No failed row/variant was removed. Experimental "
        "classes remain confined to compare.py; production still imports CuttingSolver.",
        "",
        "## N03 / N13",
        "",
        "N03 preserves ordinary candidate order. scarcity-comparison.json retains36 synthetic actual "
        "HTTP/service responses:11 warm exact jointly validated witnesses,18 negative no_proof cases, "
        "6 tiny-budget limited cases and1 cold-import limited response. Warm HTTP p95=28.26ms; cold native "
        "startup=1044.15ms. Optional proved advice is enabled; global ordering is not promoted.",
        "",
        "N13 is enabled only as a read-only validated geometric projection: minimum edge excess over5, "
        "axis-separation gap excess over3, and separate tempered whole-piece deviation tolerance±2. "
        "It changes neither placement nor tolerances and predicts no defect probability or human savings.",
        "",
        "No600s heavy profile, contest-wide score, real demand forecast, clean-machine qualification or "
        "human measurement is claimed by this bounded study.",
        "",
    ]
    (HERE / "RESULTS.md").write_text("\n".join(lines), encoding="utf8")


if __name__ == "__main__":
    render()
