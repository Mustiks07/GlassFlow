"""Build a reviewable local contest folder only after every actual artifact passes its gate."""

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader
from scan_release import scan

from glassflow.modules.platform.exports import SCHEMAS

ROOT = Path(__file__).resolve().parents[1]


def verify_export(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
    if manifest.get("status") != "ready" or manifest.get("errors"):
        raise ValueError("Five-file same-run export is not ready")
    if any(p.get("synthetic") for p in manifest.get("module_provenance", {}).values() if isinstance(p, dict)):
        raise ValueError("Synthetic domain fixtures cannot be released")
    if set(manifest["files"]) != set(SCHEMAS):
        raise ValueError("Missing required CSVs or extra schema")
    if not manifest["validators"].get("cutting_official", {}).get("passed"):
        raise ValueError("Actual official cutting validation required")
    for name, fields in SCHEMAS.items():
        content = (directory / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["files"][name] or content.startswith(
            b"\xef\xbb\xbf"
        ):
            raise ValueError(f"Changed bytes or BOM: {name}")
        reader = csv.DictReader(io.StringIO(content.decode("utf8"), newline=""), strict=True)
        if reader.fieldnames != fields:
            raise ValueError(f"Wrong exact schema: {name}")
        rows = list(reader)
        if (
            name == "sale_cards.csv"
            and len(rows) != 5
            or name == "picks.csv"
            and len(rows) != 25
            or name == "buyers_top50.csv"
            and len(rows) != 50
        ):
            raise ValueError(f"Wrong row count: {name}")
    return manifest


def assemble(export_dir, report_dir, readme, destination, team, windows_bundle=None):
    if not team.strip():
        raise ValueError("Actual team name required")
    manifest = verify_export(export_dir)
    report = json.loads((report_dir / "report-build.json").read_text(encoding="utf8"))
    if report.get("visual_review") != "passed" or report.get("status") == "synthetic_layout_preview":
        raise ValueError("Actual PDF visual review required; previews cannot be released")
    if report.get("examples", {}).get("run_id") != manifest["run_id"]:
        raise ValueError("PDF and CSV provenance must name the same actual final run")
    for name in ("economics.pdf", "examples.pdf"):
        if hashlib.sha256((report_dir / name).read_bytes()).hexdigest() != report["files"][name]:
            raise ValueError(f"PDF changed since review: {name}")
    if len(PdfReader(report_dir / "economics.pdf").pages) != 1:
        raise ValueError("Economics must be one page")
    text = readme.read_text(encoding="utf8")
    if team not in text or any(
        marker in text for marker in ("TEAM_NAME_REQUIRED", "NOT FOR RELEASE", "имя команды неизвестно")
    ):
        raise ValueError("Final reviewed README with team name required")
    if destination.exists():
        raise ValueError(
            "Destination already exists; choose a new version, never replace final user artifacts"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".release-staging-", dir=destination.parent))
    try:
        (staging / "closed_run").mkdir()
        for name in SCHEMAS:
            target = staging / name if name == "buyers_top50.csv" else staging / "closed_run" / name
            shutil.copy2(export_dir / name, target)
        shutil.copy2(export_dir / "manifest.json", staging / "closed_run/manifest.json")
        for name in ("economics.pdf", "examples.pdf"):
            shutil.copy2(report_dir / name, staging / name)
        shutil.copy2(readme, staging / "README.md")
        code = staging / "code"
        code.mkdir()
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf8").split("\0")
        excluded = ("analysis/", "docs/status/", "docs/agents/", "docs/presentation/")
        for name in tracked:
            if (
                not name
                or (name.startswith(excluded) and name != "docs/agents/coverage.json")
                or "_KEY." in name
                or name == "AGENTS.md"
            ):
                continue
            source = ROOT / name
            if not source.is_file():
                raise ValueError(f"Tracked source missing: {name}")
            target = code / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if windows_bundle:
            shutil.copytree(windows_bundle, staging / "GlassFlow-Windows")
        problems = scan(staging)
        if problems:
            raise ValueError("\n".join(problems))
        hashes = {
            p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in staging.rglob("*")
            if p.is_file()
        }
        (staging / "release-manifest.json").write_text(
            json.dumps(
                {
                    "run_id": manifest["run_id"],
                    "team": team,
                    "files": hashes,
                    "submission": "not_run",
                    "guest_download": "not_run",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf8",
        )
        if staging.resolve().parent != destination.parent.resolve():
            raise ValueError("Unsafe staging path")
        os.replace(staging, destination)
    except BaseException:
        if staging.resolve().parent == destination.parent.resolve() and staging.name.startswith(
            ".release-staging-"
        ):
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--windows-bundle", type=Path)
    args = parser.parse_args()
    print(assemble(args.export, args.reports, args.readme, args.output, args.team, args.windows_bundle))
