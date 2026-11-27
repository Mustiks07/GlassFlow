"""Synthetic layout and arithmetic checks; never release or measured business evidence."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from glassflow.modules.platform.reports import build_reports, economic_scenario


def synthetic_evidence():
    provenance = dict(
        dataset_id="synthetic-dataset", run_id="synthetic-run", source_ref="Synthetic test evidence"
    )
    economics = dict(
        final_material_value_tg="100000",
        baseline_material_value_tg="90000",
        baseline_validation_ref="synthetic-baseline-check",
        final_validation_ref="synthetic-final-check",
        baseline_description="Синтетический сопоставимый baseline для проверки формулы",
        monthly_dataset_multiplier="1",
        monthly_operations="100",
        hourly_rate_tg="3600",
        hourly_rate_basis="Явное синтетическое допущение теста",
        monthly_volume_basis="Явное тестовое допущение",
        ai_monthly_tg="0",
        ai_cost_basis="Тестовый сценарий без сетевых вызовов; не подтвержденная free quota",
        hosting_monthly_tg="1000",
        support_monthly_tg="2000",
        implementation_tg="14000",
        implementation_basis="Синтетическое допущение теста",
        labor_studies=[
            dict(
                task_id=f"test-{i}",
                manual_active_seconds="60",
                app_active_seconds="30",
                protocol="Synthetic protocol",
                observer="pytest",
                measured_at="2026-11-27",
                start_definition="Начало",
                end_definition="Конец",
            )
            for i in range(10)
        ],
    )
    examples = {
        "cutting": [
            {
                **provenance,
                "remnant_id": f"TEST-R{i}",
                "length_mm": 1000,
                "width_mm": 500,
                "description": "Синтетическая схема, не реальный производственный результат.",
                "placements": [
                    {"part_id": "TEST-P", "x_mm": 5, "y_mm": 5, "rot": 0, "length_mm": 450, "width_mm": 300}
                ],
            }
            for i in range(3)
        ],
        "answers": [
            {
                **provenance,
                "question": "Синтетический вопрос?",
                "answer": "Синтетический проверочный текст без коммерческого обещания.",
            }
            for _ in range(3)
        ],
        "reminders": [
            {
                **provenance,
                "recipient_client_id": "TEST-C",
                "source_app_ids": ["TEST-A"],
                "subject_type": "interest",
                "reason": "Явный синтетический тест",
                "text": "Уточнить интерес к группе.",
            }
            for _ in range(3)
        ],
        "quality": [
            {
                **provenance,
                "client": "Проверочный вопрос",
                "manager": "Проверочный ответ",
                "verdict": "ERROR",
                "correct": "10000",
            }
            for _ in range(3)
        ],
    }
    return {
        "synthetic": True,
        "manifest": {
            **provenance,
            "input_hash": "0" * 64,
            "source_hashes": {"synthetic": "0" * 64},
            "status": "ready",
        },
        "economics": economics,
        "examples": examples,
    }


def test_economics_no_double_count_or_invented_payback():
    data = synthetic_evidence()["economics"]
    result = economic_scenario(data)
    assert result["scenario_net_effect_tg"] == Decimal("10000")  # delta 10000 + labor 3000 - services 3000
    assert result["payback_months"] == Decimal("1.4")
    data["hosting_monthly_tg"] = "1000000"
    assert economic_scenario(data)["payback_months"] is None
    data["labor_studies"] = []
    with pytest.raises(ValueError, match="ten"):
        economic_scenario(data)


def test_cyrillic_pdf_and_preview_cannot_be_final(tmp_path):
    font = next(
        (
            p
            for p in [
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            ]
            if p.is_file()
        ),
        None,
    )
    if font is None:
        pytest.skip("Cyrillic TrueType font unavailable in test environment")
    evidence = tmp_path / "synthetic.json"
    evidence.write_text(json.dumps(synthetic_evidence(), ensure_ascii=False), encoding="utf8")
    with pytest.raises(ValueError, match="Synthetic"):
        build_reports(evidence, tmp_path / "final", font)
    result = build_reports(evidence, tmp_path / "preview", font, preview=True)
    assert result["status"] == "synthetic_layout_preview" and result["visual_review"] == "not_run"
    pdf = PdfReader(tmp_path / "preview/economics.pdf")
    assert len(pdf.pages) == 1
    assert "Экономика условного месяца" in pdf.pages[0].extract_text()
    examples = PdfReader(tmp_path / "preview/examples.pdf")
    assert len(examples.pages) == 6 and "TEST-R0" in examples.pages[0].extract_text()
