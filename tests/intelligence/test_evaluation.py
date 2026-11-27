"""Evaluation-command tests. KEY files are used here only through the unmodified selfcheck.py
(test/evaluation context, allowed by AGENTS.md); runtime code never opens them."""

from glassflow.modules.intelligence.evaluation.runner import CASES_PATH, evaluate_extended, evaluate_open

from .conftest import PACK


def test_t24_t37_open_pack_through_runtime_and_official_selfcheck(tmp_path):
    report = evaluate_open(PACK, tmp_path)
    assistant, dialogs = report["selfcheck"]["assistant"], report["selfcheck"]["dialogs"]
    assert assistant["exit_code"] == 0 and dialogs["exit_code"] == 0
    assert (assistant["score"], assistant["max"]) == (15.0, 15)
    assert (dialogs["score"], dialogs["max"]) == (5.0, 5)
    assert "выдумок 0" in assistant["stdout"]
    assert report["answer_batch"]["paths"] == ["deterministic"]
    raw = (tmp_path / "answers.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and raw.splitlines()[0] == b"id,answer"
    assert (tmp_path / "verdicts.csv").read_bytes().splitlines()[0] == b"id,verdict,correct"


def test_t32_extended_and_holdout_sets(tmp_path):
    extended = evaluate_extended(PACK, tmp_path, cases_path=CASES_PATH)
    holdout = evaluate_extended(PACK, tmp_path, cases_path=CASES_PATH.with_name("cases_holdout.json"), name="holdout")
    for report in (extended, holdout):
        assert report["accuracy"] >= 0.95
        assert report["unconfirmed_commercial_claims"] == 0
    assert extended["cases"] + holdout["cases"] >= 60
