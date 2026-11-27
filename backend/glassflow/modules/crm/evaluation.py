"""Offline evaluator only. Labels are never used by the runtime ranking policy."""

import hashlib
import json
from pathlib import Path

import numpy as np
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, StratifiedShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from glassflow.modules.crm.service import baseline_key
from glassflow.modules.platform.imports import LABEL

FEATURES = ["прошлых_заявок", "дней_с_последнего_контакта", "жалоба", "manager", "тип_клиента"]


def feature_matrix(rows):
    return np.array(
        [
            [
                float(r[FEATURES[0]]),
                float(r[FEATURES[1]]),
                float(r[FEATURES[2]]) if r.get(FEATURES[2]) is not None else np.nan,
                r[FEATURES[3]],
                r[FEATURES[4]],
            ]
            for r in rows
        ],
        dtype=object,
    )


def pipeline(c):
    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [
                        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                                               ("scale", StandardScaler())]), [0, 1, 2]),
                        ("category", OneHotEncoder(handle_unknown="ignore"), [3, 4]),
                    ]
                ),
            ),
            ("logistic", LogisticRegression(C=c, max_iter=2000, random_state=42)),
        ]
    )


def precision(labels, indices):
    return float(np.mean(labels[indices])) if len(indices) else None


def choose_c(x, y, groups):
    """All C selection and preprocessing use only outer training rows."""
    splits = min(3, len(set(groups)))
    if splits < 2:
        return 1.0
    best = (float("-inf"), 1.0)
    for c in (0.1, 1.0, 10.0):
        scores = []
        for train, test in GroupKFold(splits).split(x, y, groups):
            if len(set(y[train])) < 2:
                continue
            candidate = pipeline(c).fit(x[train], y[train])
            order = np.argsort(-candidate.predict_proba(x[test])[:, 1], kind="stable")[:25]
            scores.append(float(np.mean(y[test][order])))
        score = float(np.mean(scores)) if scores else float("-inf")
        if score > best[0]:
            best = score, c
    return best[1]


def evaluate(rows, output_dir: Path, source_sha256: str):
    rows = [r for r in rows if r.get(LABEL) is not None]
    if len(rows) < 100:
        raise ValueError("At least 100 labelled rows are required for this evaluation protocol")
    x, y = feature_matrix(rows), np.array([int(r[LABEL]) for r in rows])
    groups = np.array([r["client_id"] for r in rows])
    days = np.array([int(r["день_года"]) for r in rows])
    partitions = []
    for i, (train, test) in enumerate(
        GroupShuffleSplit(5, test_size=0.3, random_state=42).split(x, y, groups)
    ):
        partitions.append((f"client_group_{i}", train, test))
    for cut in (90, 110, 130):
        # A train event's entire 60-day target window ends BEFORE the test period.
        partitions.append(
            (f"temporal_purge60_day{cut}", np.where(days < cut - 60)[0], np.where(days >= cut)[0])
        )
    for i, (train, test) in enumerate(StratifiedShuffleSplit(5, test_size=0.3, random_state=42).split(x, y)):
        partitions.append((f"random_control_{i}", train, test))
    results = []
    with threadpool_limits(limits=1):
        for name, train, test in partitions:
            if len(train) < 25 or len(test) < 25 or len(set(y[train])) < 2:
                results.append({"split": name, "status": "blocked_insufficient_data"})
                continue
            c = choose_c(x[train], y[train], groups[train])
            candidate = pipeline(c).fit(x[train], y[train])
            model_order = test[np.argsort(-candidate.predict_proba(x[test])[:, 1], kind="stable")[:25]]
            base_order = sorted(test, key=lambda i: baseline_key(rows[i]))[:25]
            results.append(
                {
                    "split": name,
                    "status": "evaluated",
                    "train_count": len(train),
                    "test_count": len(test),
                    "train_app_ids": [rows[i]["app_id"] for i in train],
                    "test_app_ids": [rows[i]["app_id"] for i in test],
                    "selected_C": c,
                    "client_overlap": len(set(groups[train]) & set(groups[test])),
                    "max_train_day": int(days[train].max()),
                    "min_test_day": int(days[test].min()),
                    "baseline_precision_at_25": precision(y, base_order),
                    "model_precision_at_25": precision(y, model_order),
                    "baseline_app_ids": [rows[i]["app_id"] for i in base_order],
                    "model_app_ids": [rows[i]["app_id"] for i in model_order],
                }
            )
        c = choose_c(x, y, groups)
        fitted = pipeline(c).fit(x, y)
    preprocess = fitted.named_steps["preprocess"]
    scaler = preprocess.named_transformers_["numeric"].named_steps["scale"]
    imputer = preprocess.named_transformers_["numeric"].named_steps["impute"]
    encoder = preprocess.named_transformers_["category"]
    logistic = fitted.named_steps["logistic"]
    artifact = {
        "format": "glassflow-logistic-json-v1",
        "candidate_only": True,
        "source_sha256": source_sha256,
        "sklearn_version": sklearn.__version__,
        "features": FEATURES,
        "C": c,
        "numeric_mean": scaler.mean_.tolist(),
        "numeric_imputer_medians": imputer.statistics_.tolist(),
        "missing_indicator_features": imputer.indicator_.features_.tolist(),
        "numeric_scale": scaler.scale_.tolist(),
        "categories": [v.tolist() for v in encoder.categories_],
        "coefficients": logistic.coef_.tolist(),
        "intercept": logistic.intercept_.tolist(),
        "classes": logistic.classes_.tolist(),
        "calibrated_probability": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "logistic_candidate.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    report = {
        "source_sha256": source_sha256,
        "target": "new_application_within_60_days",
        "features": FEATURES,
        "seed": 42,
        "splits": results,
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "frozen_runtime_policy": "reference-v1",
        "promoted": False,
        "limitations": [
            "Один небольшой синтетический набор; не доказана причинность или выручка",
            "Random control допускает пересечение клиентов, group split проверяет отдельно",
            "Временной split исключает 60-дневный горизонт; отбор top25 зависит от размера test",
            "Оценка приоритета не является калиброванной вероятностью; артефакт не загружается из UI",
        ],
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    return report
