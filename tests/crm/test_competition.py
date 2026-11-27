"""A02 leakage/transfer tests; organizer open rows are explicitly reused data."""

import csv
import hashlib
import json

import numpy as np
from conftest import INPUTS, ROOT
from threadpoolctl import threadpool_limits

from glassflow.modules.crm.competition import CANDIDATES, decide, fit_and_select, manager_stress, partitions
from glassflow.modules.crm.evaluation import feature_matrix
from glassflow.modules.platform.imports import LABEL


def inputs():
    with (INPUTS / "2_assistant_crm/applications_open.csv").open(encoding="utf8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, np.array([int(r[LABEL]) for r in rows])


def test_a02_test_labels_and_manager_ids_do_not_leak_into_no_manager_candidate():
    rows, labels = inputs()
    _, train, test = partitions(rows, labels)[0]
    with threadpool_limits(limits=1):
        selected, fitted, models = fit_and_select(rows, train, test, labels)
        changed_labels = labels.copy()
        changed_labels[test] = 1 - changed_labels[test]
        changed, metadata, _ = fit_and_select(rows, train, test, changed_labels)
    assert {name: list(values) for name, values in selected.items()} == {name: list(values) for name, values in changed.items()}
    assert fitted == metadata
    stress = manager_stress(rows, test, selected, models, labels)
    assert stress["reference-no-manager-v1"]["selection_unchanged"]
    assert stress["logistic-no-manager-v1"]["selection_unchanged"]
    assert all(len(set(rows[i]["app_id"] for i in values)) == 25 for values in selected.values())
    # Data transformers are fitted only on train, never on the test population.
    scaler = models["logistic-no-manager-v1"].named_steps["preprocess"].named_transformers_["numeric"].named_steps["scale"]
    assert np.allclose(scaler.mean_[:2], np.mean(feature_matrix(rows)[train, :2].astype(float), axis=0))


def test_a02_report_is_preregistered_complete_and_never_promotes_reused_data():
    base = ROOT / "docs/release/crm"
    protocol = json.loads((base / "A02_PROTOCOL.json").read_text(encoding="utf8"))
    report = json.loads((base / "a02-comparison.json").read_text(encoding="utf8"))
    assert report["protocol_sha256"] == hashlib.sha256((base / "A02_PROTOCOL.json").read_bytes()).hexdigest()
    assert len(report["splits"]) == 18
    assert report["decision"] == decide(report["splits"], protocol)
    for split in report["splits"]:
        assert split["status"] == "evaluated"
        assert set(split["scores"]) == set(CANDIDATES)
        if split["split"].startswith("temporal_"):
            assert split["max_train_day"] + 60 < split["min_test_day"]
        if split["split"].startswith("client_group_"):
            assert split["client_overlap"] == 0
    # Even artificially perfect exploratory scores cannot replace independent control.
    synthetic = json.loads(json.dumps(report["splits"]))
    for split in synthetic:
        split["scores"]["reference-v1"]["precision_at_25"] = 0.5
        for name in CANDIDATES[1:]:
            split["scores"][name]["precision_at_25"] = 1.0
    result = decide(synthetic, protocol)
    assert result["promoted"] is False and result["runtime_policy"] == "reference-v1"
    assert all(not c["promotion_eligible"] for c in result["candidates"].values())
