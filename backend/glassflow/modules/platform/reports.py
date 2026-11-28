"""Evidence-gated reports. Never substitutes research numbers or synthetic examples."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
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

from glassflow.modules.platform.economics import economic_scenario, serialized_result


def decimal(value):
    if not isinstance(value, str):
        raise ValueError("Money must be a decimal string")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Money must be finite")
    return result


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


def build_economics(evidence, destination, font, *, preview=False, scenario_preview=False):
    if destination.exists() and not preview:
        raise ValueError("Existing economics artifact is protected; choose a new output version")
    manifest = require_evidence(evidence, preview)
    data, style = evidence["economics"], styles(font)
    if not preview and data.get("measurement_status") == "synthetic":
        raise ValueError("Synthetic labor studies cannot produce final economics")
    result = economic_scenario(data)
    story = [paragraph("Экономика условного месяца", style["title"])]
    if scenario_preview:
        story.append(paragraph("СЦЕНАРНЫЙ РАСЧЕТ / НЕ ФИНАЛЬНАЯ ЗАПИСКА", style["heading"]))
        story.append(paragraph(f"Замеры: {data['measurement_status']}. Источники предоставлены пользователем.", style["small"]))
    elif preview:
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
            "Сценарный прирост к baseline",
            result["material_delta_tg"],
            f"(Итог - baseline) × месячный множитель × доля {data.get('material_use_fraction', '1')}; без двойного счета",
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
        f"Диапазон net {amount(result['net_range_low_tg'])}—{amount(result['net_range_high_tg'])} ₸: углы допущений и разброс замеров, не доверительный интервал.",
        f"Доля использования: {data.get('material_use_basis', 'Сценарное допущение')}. Подтвержденное использование: {data.get('confirmed_material_use_value_tg') or 'нет данных'}; потенциальная продажа {data.get('potential_remnant_sale_tg', '0')}; выручка фактической продажи {data.get('actual_sale_revenue_tg') or 'нет данных'} ₸. Эти суммы не добавлены к net.",
        f"Run {manifest['run_id']}; dataset {manifest['dataset_id']}; inputs SHA256 {manifest['input_hash']}",
    ]:
        story.append(paragraph(text, style["small"]))
    if evidence.get("scenario_identity"):
        identity = evidence["scenario_identity"]
        story.append(paragraph(f"Scenario {identity['scenario_id']} v{identity['version']}; formula {identity['formula_version']}; result SHA256 {identity['result_hash']}", style["small"]))
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
    return serialized_result(data)


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
    if destination.exists() and not preview:
        raise ValueError("Existing examples artifact is protected; choose a new output version")
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


def build_reports(evidence_path: Path, output_dir: Path, font: Path, *, preview=False, only="all"):
    if only not in {"all", "examples", "economics"}:
        raise ValueError("Unknown report selection")
    evidence = json.loads(evidence_path.read_text(encoding="utf8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "synthetic_layout_preview" if preview else "requires_visual_review",
        "visual_review": "not_run",
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    if only in {"all", "economics"}:
        result["economics"] = build_economics(evidence, output_dir / "economics.pdf", font, preview=preview)
    if only in {"all", "examples"}:
        result["examples"] = build_examples(evidence, output_dir / "examples.pdf", font, preview=preview)
    result["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output_dir.glob("*.pdf")}
    (output_dir / "report-build.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    (output_dir / "report-evidence.json").write_bytes(evidence_path.read_bytes())
    return result
