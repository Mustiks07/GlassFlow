"""Evidence-gated reports. Never substitutes research numbers or synthetic examples."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def decimal(value):
    if not isinstance(value, str):
        raise ValueError("Money must be a decimal string")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Money must be finite")
    return result


def economic_scenario(data):
    studies = data["labor_studies"]
    if len(studies) < 10 or len({s["task_id"] for s in studies}) != len(studies):
        raise ValueError("At least ten distinct paired manual/app tasks required")
    manual, application, differences = [], [], []
    for study in studies:
        if not all(
            study.get(k)
            for k in ("protocol", "observer", "measured_at", "start_definition", "end_definition")
        ):
            raise ValueError("Missing real labor measurement provenance")
        m, a = decimal(study["manual_active_seconds"]), decimal(study["app_active_seconds"])
        if m <= 0 or a <= 0:
            raise ValueError("Active seconds must be measured positive values")
        manual.append(m)
        application.append(a)
        differences.append(m - a)
    if not data.get("hourly_rate_basis") or not data.get("monthly_volume_basis"):
        raise ValueError("Rate and monthly volume need explicit source or assumption")
    final_value, baseline_value = (
        decimal(data["final_material_value_tg"]),
        decimal(data["baseline_material_value_tg"]),
    )
    if (
        min(final_value, baseline_value) < 0
        or not data.get("baseline_validation_ref")
        or not data.get("final_validation_ref")
    ):
        raise ValueError("Both actual plans need value and validation evidence")
    delta = (final_value - baseline_value) * decimal(data["monthly_dataset_multiplier"])
    labor = (
        median(differences)
        / Decimal(3600)
        * decimal(data["monthly_operations"])
        * decimal(data["hourly_rate_tg"])
    )
    costs = sum(
        (decimal(data[k]) for k in ("ai_monthly_tg", "hosting_monthly_tg", "support_monthly_tg")), Decimal(0)
    )
    if any(
        decimal(data[k]) < 0
        for k in (
            "monthly_dataset_multiplier",
            "monthly_operations",
            "hourly_rate_tg",
            "ai_monthly_tg",
            "hosting_monthly_tg",
            "support_monthly_tg",
            "implementation_tg",
        )
    ):
        raise ValueError("Costs and volumes cannot be negative")
    if not data.get("ai_cost_basis"):
        raise ValueError(
            "AI cost needs actual usage/tariff/date/quota evidence or explicit scenario assumption"
        )
    net = delta + labor - costs
    return {
        "material_delta_tg": delta,
        "labor_effect_tg": labor,
        "monthly_costs_tg": costs,
        "scenario_net_effect_tg": net,
        "payback_months": decimal(data["implementation_tg"]) / net if net > 0 else None,
        "manual_median_seconds": median(manual),
        "app_median_seconds": median(application),
        "paired_saved_median_seconds": median(differences),
        "paired_saved_min_seconds": min(differences),
        "paired_saved_max_seconds": max(differences),
        "study_count": len(studies),
    }


def amount(value):
    if value is None:
        return "Не определена при эффекте <= 0"
    return format(value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP), ",.2f").replace(",", " ")


def require_evidence(evidence, preview):
    if evidence.get("synthetic") and not preview:
        raise ValueError("Synthetic evidence cannot produce final reports")
    manifest = evidence["manifest"]
    if not all(manifest.get(k) for k in ("run_id", "dataset_id", "input_hash", "source_hashes")):
        raise ValueError("Actual run provenance required")
    if not preview and manifest.get("status") != "ready":
        raise ValueError("Final reports require a ready same-run manifest")
    return manifest


def styles(font):
    pdfmetrics.registerFont(TTFont("GlassFlowReport", str(font)))
    return {
        name: ParagraphStyle(
            name,
            fontName="GlassFlowReport",
            fontSize=size,
            leading=leading,
            textColor=colors.HexColor("#142E39"),
            spaceAfter=after,
            alignment=TA_LEFT,
        )
        for name, size, leading, after in [
            ("title", 22, 27, 9),
            ("subtitle", 9, 13, 12),
            ("heading", 13, 18, 8),
            ("body", 9, 13, 6),
            ("small", 7, 10, 4),
        ]
    }


def paragraph(value, style):
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def footer(canvas, doc):
    canvas.setFont("GlassFlowReport", 7)
    canvas.setFillColor(colors.HexColor("#59707A"))
    canvas.drawString(18 * mm, 12 * mm, "GlassFlow | Проверяемые данные, прозрачные ограничения")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))


def build_economics(evidence, destination, font, *, preview=False):
    manifest = require_evidence(evidence, preview)
    data, style = evidence["economics"], styles(font)
    result = economic_scenario(data)
    story = [paragraph("Экономика условного месяца", style["title"])]
    if preview:
        story.append(paragraph("СИНТЕТИЧЕСКИЙ ТЕСТ МАКЕТА / НЕ ДЛЯ СДАЧИ", style["heading"]))
    story.append(
        paragraph(
            "Открытый учебный набор принят за условный месяц. Сценарная оценка не является выручкой или прибылью KSM.",
            style["subtitle"],
        )
    )
    items = [
        (
            "Оценка материала итогового плана",
            data["final_material_value_tg"],
            "Σ(L×W / 1 000 000 × materials rate) для деталей из остатков",
        ),
        ("Оценка сопоставимого baseline", data["baseline_material_value_tg"], data["baseline_description"]),
        (
            "Месячный прирост к baseline",
            result["material_delta_tg"],
            "(Итог - baseline) × месячный множитель; не складывается с валовой оценкой",
        ),
        (
            "Сценарное высвобождение труда",
            result["labor_effect_tg"],
            "Медиана парной экономии секунд / 3600 × операций в месяц × ставка часа",
        ),
        (
            "Сервисы и поддержка в месяц",
            result["monthly_costs_tg"],
            f"AI {data['ai_monthly_tg']}; хостинг {data['hosting_monthly_tg']}; поддержка {data['support_monthly_tg']}",
        ),
        (
            "Чистый сценарный эффект / месяц",
            result["scenario_net_effect_tg"],
            "Прирост оценки материала + труд - сервисы; не бухгалтерская прибыль",
        ),
        ("Разовое внедрение", data["implementation_tg"], data["implementation_basis"]),
        (
            "Сценарная окупаемость, месяцев",
            result["payback_months"],
            "Внедрение / положительный чистый эффект",
        ),
    ]
    table_rows = [
        [
            paragraph("Показатель", style["body"]),
            paragraph("₸ / месяцы", style["body"]),
            paragraph("Основание", style["body"]),
        ]
    ]
    for title, value, basis in items:
        table_rows.append(
            [
                paragraph(title, style["body"]),
                paragraph(amount(decimal(value) if isinstance(value, str) else value), style["body"]),
                paragraph(basis, style["small"]),
            ]
        )
    table = Table(table_rows, colWidths=[64 * mm, 37 * mm, 73 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEBEA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7F8")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 10),
        paragraph(
            f"Активное время: {result['study_count']} сопоставимых задач; вручную {amount(result['manual_median_seconds'])} с, в приложении {amount(result['app_median_seconds'])} с. Парная экономия: медиана {amount(result['paired_saved_median_seconds'])} с, диапазон {amount(result['paired_saved_min_seconds'])}-{amount(result['paired_saved_max_seconds'])} с. Задержка ответ_через_мин не используется.",
            style["small"],
        ),
    ]
    for text in [
        f"Ставка часа: {data['hourly_rate_tg']} ₸. {data['hourly_rate_basis']}",
        f"Месячный объем: {data['monthly_operations']} операций; множитель набора {data['monthly_dataset_multiplier']}. {data['monthly_volume_basis']}",
        f"AI: {data['ai_cost_basis']}",
        "Карточки не считаются продажами; CRM Precision@25 не переводится в выручку. Закупочные затраты и маржа компании неизвестны.",
        f"Run {manifest['run_id']}; dataset {manifest['dataset_id']}; inputs SHA256 {manifest['input_hash']}",
    ]:
        story.append(paragraph(text, style["small"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    if len(PdfReader(destination).pages) != 1:
        destination.unlink()
        raise ValueError("Economics must fit exactly one readable page; shorten evidence notes")
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in result.items()}


class CutDiagram(Flowable):
    def __init__(self, example):
        super().__init__()
        self.example, self.width, self.height = example, 170 * mm, 94 * mm

    def draw(self):
        source = self.example
        length, width = source["length_mm"], source["width_mm"]
        scale = min((self.width - 10) / length, (self.height - 24) / width)
        canvas = self.canv
        offset = self.height - 14 - width * scale
        canvas.setStrokeColor(colors.HexColor("#244651"))
        canvas.setFillColor(colors.HexColor("#ECF5F4"))
        canvas.rect(0, offset, length * scale, width * scale, fill=1)
        for part in source["placements"]:
            pw, ph = part["length_mm"], part["width_mm"]
            if part["rot"] == 1:
                pw, ph = ph, pw
            x = part["x_mm"] * scale
            y = offset + (width - part["y_mm"] - ph) * scale
            canvas.setFillColor(colors.HexColor("#B8DBD5"))
            canvas.rect(x, y, pw * scale, ph * scale, fill=1)
            canvas.setFillColor(colors.HexColor("#142E39"))
            canvas.setFont("GlassFlowReport", 7)
            canvas.drawString(x + 2, y + max(2, ph * scale / 2), part["part_id"])
        canvas.setFont("GlassFlowReport", 8)
        canvas.drawString(
            0,
            self.height - 9,
            f"{source['remnant_id']} | {length}×{width} мм | координаты из проверенного плана",
        )


def build_examples(evidence, destination, font, *, preview=False):
    manifest = require_evidence(evidence, preview)
    examples = evidence["examples"]
    for kind in ("cutting", "answers", "reminders", "quality"):
        if len(examples.get(kind, [])) < 3:
            raise ValueError(f"Need at least 3 actual {kind} examples")
        for item in examples[kind]:
            if not item.get("dataset_id") or not item.get("run_id") or not item.get("source_ref"):
                raise ValueError(f"Missing provenance for {kind}")
    style = styles(font)
    story = [
        paragraph("GlassFlow в работе", style["title"]),
        paragraph(
            "Фактические результаты предметных сервисов с источниками и ограничениями.", style["subtitle"]
        ),
    ]
    if preview:
        story.append(paragraph("СИНТЕТИЧЕСКИЙ ТЕСТ МАКЕТА / НЕ ДЛЯ СДАЧИ", style["heading"]))
    for index, item in enumerate(examples["cutting"][:3]):
        if index:
            story.append(PageBreak())
        story += [
            paragraph(f"Раскрой {index + 1}", style["heading"]),
            CutDiagram(item),
            paragraph(item["description"], style["body"]),
            paragraph(
                f"Dataset {item['dataset_id']}; run {item['run_id']}; {item['source_ref']}", style["small"]
            ),
        ]
        placement_rows = [["Деталь", "x, y (мм)", "Поворот", "Размеры (мм)"]]
        for p in item["placements"]:
            placement_rows.append(
                [
                    p["part_id"],
                    f"{p['x_mm']}, {p['y_mm']}",
                    str(p["rot"]),
                    f"{p['length_mm']}×{p['width_mm']}",
                ]
            )
        table = Table(
            [[paragraph(c, style["small"]) for c in row] for row in placement_rows],
            colWidths=[45 * mm, 45 * mm, 35 * mm, 45 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEBEA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)
    sections = [
        ("answers", "Ответы ассистента", [("question", "Запрос"), ("answer", "Ответ")]),
        (
            "reminders",
            "Локальные напоминания",
            [
                ("recipient_client_id", "Адресат"),
                ("source_app_ids", "Основания"),
                ("subject_type", "Тип предмета"),
                ("reason", "Почему этот клиент"),
                ("text", "Задача"),
            ],
        ),
        (
            "quality",
            "Контроль диалогов",
            [
                ("client", "Клиент"),
                ("manager", "Менеджер"),
                ("verdict", "Вердикт"),
                ("correct", "Корректное число"),
            ],
        ),
    ]
    for kind, heading, fields in sections:
        story += [PageBreak(), paragraph(heading, style["title"])]
        for index, item in enumerate(examples[kind][:3], 1):
            story.append(paragraph(f"Пример {index}", style["heading"]))
            for key, label in fields:
                story.append(paragraph(f"{label}: {item.get(key, '')}", style["body"]))
            story.append(
                paragraph(
                    f"Dataset {item['dataset_id']}; run {item['run_id']}; {item['source_ref']}",
                    style["small"],
                )
            )
            story.append(Spacer(1, 10))
        if kind == "reminders":
            story.append(
                paragraph(
                    "Адресат задачи отличается от заказчика расчета. Аналогичный расчет - пример; внешние сообщения не отправляются и исторические продажи не меняются.",
                    style["small"],
                )
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return {"run_id": manifest["run_id"], "pages": len(PdfReader(destination).pages)}


def build_reports(evidence_path: Path, output_dir: Path, font: Path, *, preview=False):
    evidence = json.loads(evidence_path.read_text(encoding="utf8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "economics": build_economics(evidence, output_dir / "economics.pdf", font, preview=preview),
        "examples": build_examples(evidence, output_dir / "examples.pdf", font, preview=preview),
        "status": "synthetic_layout_preview" if preview else "requires_visual_review",
        "visual_review": "not_run",
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    result["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output_dir.glob("*.pdf")}
    (output_dir / "report-build.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    return result
