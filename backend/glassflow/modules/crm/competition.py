"""A02 preregistered offline comparison. Never changes runtime ranking policy."""

import hashlib
import json
from pathlib import Path

import numpy as np
import sklearn
from sklearn.model_selection import GroupShuffleSplit, StratifiedShuffleSplit
from threadpoolctl import threadpool_limits

from glassflow.core.uow import canonical_hash
from glassflow.modules.crm.evaluation import FEATURES, choose_c, feature_matrix, pipeline
from glassflow.modules.crm.service import baseline_key
from glassflow.modules.platform.imports import LABEL

CANDIDATES = ("reference-v1", "reference-no-manager-v1", "logistic-manager-v1", "logistic-no-manager-v1")


def partitions(rows, labels):
    groups = np.array([r["client_id"] for r in rows])
    days = np.array([int(r["день_года"]) for r in rows])
    result = [(f"client_group_{i}", a, b) for i, (a, b) in enumerate(
        GroupShuffleSplit(5, test_size=0.3, random_state=42).split(rows, labels, groups))]
    result += [(f"temporal_purge60_day{cut}", np.where(days < cut - 60)[0], np.where(days >= cut)[0])
               for cut in (90, 110, 130)]
    result += [(f"random_control_{i}", a, b) for i, (a, b) in enumerate(
        StratifiedShuffleSplit(5, test_size=0.3, random_state=42).split(rows, labels))]
    result += [(f"manager_holdout_{manager}", np.array([i for i, r in enumerate(rows) if r["manager"] != manager]),
                np.array([i for i, r in enumerate(rows) if r["manager"] == manager]))
               for manager in sorted({r["manager"] for r in rows})]
    return result


def heuristic_order(rows, indices, include_manager=True):
    def key(index):
        values = baseline_key(rows[index])
        return values if include_manager else (values[0], values[1], values[3])
    return sorted(indices, key=key)[:25]


def fit_and_select(rows, train, test, labels):
    """Label-free feature matrix; labels accessed only to fit within outer train."""
    x = feature_matrix(rows)
    groups = np.array([r["client_id"] for r in rows])
    selected = {"reference-v1": heuristic_order(rows, test),
                "reference-no-manager-v1": heuristic_order(rows, test, False)}
    metadata, models = {}, {}
    for name, manager in (("logistic-manager-v1", True), ("logistic-no-manager-v1", False)):
        c = choose_c(x[train], labels[train], groups[train], include_manager=manager)
        model = pipeline(c, include_manager=manager).fit(x[train], labels[train])
        selected[name] = test[np.argsort(-model.predict_proba(x[test])[:, 1], kind="stable")[:25]].tolist()
        metadata[name] = {"C": c, "features": FEATURES if manager else [f for f in FEATURES if f != "manager"],
                          "fit_app_ids_hash": canonical_hash([rows[i]["app_id"] for i in train])}
        models[name] = model
    return selected, metadata, models


def manager_stress(rows, test, selected, models, labels):
    managers = sorted({r["manager"] for r in rows})
    mapping = {manager: managers[(i + 1) % len(managers)] for i, manager in enumerate(managers)}
    renamed = [{**r, "manager": mapping[r["manager"]]} for r in rows]
    changed = {"reference-v1": heuristic_order(renamed, test),
               "reference-no-manager-v1": heuristic_order(renamed, test, False)}
    x = feature_matrix(renamed)
    for name, model in models.items():
        changed[name] = test[np.argsort(-model.predict_proba(x[test])[:, 1], kind="stable")[:25]].tolist()
    return {name: {"selection_unchanged": list(selected[name]) == list(changed[name]),
                   "overlap_at_25": len(set(selected[name]) & set(changed[name])),
                   "precision_at_25": float(np.mean(labels[changed[name]]))}
            for name in CANDIDATES}


def decide(results, protocol):
    rule = protocol["selection_rule"]
    decisions = {}
    primary = [r for r in results if r["split"].startswith(("client_group_", "temporal_purge60_"))]
    for name in CANDIDATES[1:]:
        evaluated = [r for r in primary if r["status"] == "evaluated"]
        lifts = [r["scores"][name]["precision_at_25"] - r["scores"]["reference-v1"]["precision_at_25"]
                 for r in evaluated]
        temporal = [r["scores"][name]["precision_at_25"] - r["scores"]["reference-v1"]["precision_at_25"]
                    for r in evaluated if r["split"].startswith("temporal_")]
        mean_lift = float(np.mean(lifts)) if lifts else None
        worst = min(temporal) if temporal else None
        passes = (len(evaluated) == 8 and mean_lift >= rule["minimum_mean_precision_lift"] - 1e-12
                  and worst >= rule["minimum_worst_temporal_lift"] - 1e-12)
        decisions[name] = {"primary_mean_lift": mean_lift, "worst_temporal_lift": worst,
                           "passes_reused_data_criteria": passes,
                           "promotion_eligible": False, "reason": "Independent previously unseen control unavailable"}
    return {"candidates": decisions, "runtime_policy": "reference-v1", "promoted": False,
            "reason": "No independent control; retain frozen baseline even if exploratory criteria pass"}


def compete(rows, protocol, source_sha256, protocol_sha256):
    if tuple(protocol["candidates"]) != CANDIDATES or protocol["allowed_features"] != FEATURES:
        raise ValueError("Protocol candidate/features differ from registered implementation")
    if len(rows) < 100 or len({r["app_id"] for r in rows}) != len(rows):
        raise ValueError("At least100 distinct application rows required")
    if any(r.get(LABEL) not in {"0", "1", 0, 1} for r in rows):
        raise ValueError("Offline comparison requires explicit known labels for every row")
    labels = np.array([int(r[LABEL]) for r in rows])
    results = []
    with threadpool_limits(limits=1):
        for name, train, test in partitions(rows, labels):
            row = {"split": name, "train_app_ids": [rows[i]["app_id"] for i in train],
                   "test_app_ids": [rows[i]["app_id"] for i in test], "train_count": len(train),
                   "test_count": len(test), "client_overlap": len(
                       {rows[i]["client_id"] for i in train} & {rows[i]["client_id"] for i in test}),
                   "train_positive_count": int(labels[train].sum()),
                   "max_train_day": max((int(rows[i]["день_года"]) for i in train), default=None),
                   "min_test_day": min((int(rows[i]["день_года"]) for i in test), default=None)}
            if len(train) < 25 or len(test) < 25 or len(set(labels[train])) < 2:
                row["status"] = "blocked_insufficient_data"
            else:
                selected, fitted, models = fit_and_select(rows, train, test, labels)
                row.update(status="evaluated", fitted=fitted, scores={
                    candidate: {"precision_at_25": float(np.mean(labels[indices])),
                                "app_ids": [rows[i]["app_id"] for i in indices],
                                "unique_client_count": len({rows[i]["client_id"] for i in indices})}
                    for candidate, indices in selected.items()},
                    manager_id_rotation=manager_stress(rows, test, selected, models, labels))
            results.append(row)
    return {"protocol_version": protocol["protocol_version"], "protocol_sha256": protocol_sha256,
            "source_sha256": source_sha256, "sklearn_version": sklearn.__version__,
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "data_status": "reused_open_dataset; not independent control",
            "target": protocol["target"], "selection_unit": protocol["selection_unit"],
            "splits": results, "decision": decide(results, protocol),
            "limitations": ["Manager IDs are associations, not causal performance",
                            "Leave-manager-out may overlap clients; it is diagnostic only",
                            "No claim about closed score, purchase, revenue or calibrated probability"]}


def write_report(report, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
