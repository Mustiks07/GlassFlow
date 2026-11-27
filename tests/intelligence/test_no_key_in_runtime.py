"""Runtime code must not read evaluation KEY files or contain answer tables (R65, T31, T59)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "backend" / "glassflow" / "modules" / "intelligence"
GATEWAY = ROOT / "infra" / "ai-gateway"


def runtime_files():
    for path in list(RUNTIME.rglob("*.py")) + list(GATEWAY.rglob("*.py")):
        if "evaluation" in path.relative_to(ROOT).parts:
            continue  # the offline evaluator is the only place allowed to name KEY files
        yield path


def test_runtime_has_no_key_references():
    offenders = []
    for path in runtime_files():
        text = path.read_text(encoding="utf-8")
        if re.search(r"_KEY\.csv|questions_open_KEY|dialogs_open_KEY|reviewed_answers|reviewed_verdicts|analysis/crm", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_runtime_has_no_hardcoded_question_ids():
    pattern = re.compile(r"[\"'](?:Q\d{2}|D\d{2})[\"']")
    offenders = [str(p.relative_to(ROOT)) for p in runtime_files() if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_runtime_has_no_secrets():
    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9]{32,}")
    offenders = [str(p.relative_to(ROOT)) for p in runtime_files() if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
