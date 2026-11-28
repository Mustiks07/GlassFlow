"""N09 immutable document snapshots; a label is never a mutation capability."""

import io
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from glassflow.contracts.baskets import Basket
from glassflow.contracts.cutting import CutPlan, SolveInput
from glassflow.contracts.insights import PieceLabel, PieceLabelResolved, WarehouseDocument
from glassflow.contracts.orders import OrderSheet
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow, now, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.cutting.service import CuttingError, CuttingService
from glassflow.modules.platform import baskets, orders
from glassflow.modules.platform.imports import dataset


def current_piece(session, dataset_id, remnant_id):
    try:
        return CuttingService(session).get_remnant(dataset_id, remnant_id)
    except CuttingError as exc:
        raise AppError(exc.status, exc.code, exc.message_ru, conflicts=exc.conflict_objects) from None


def workspace(session, dataset_id):
    if dataset(session, dataset_id).mode != "workspace":
        raise AppError(
            409, "WORKSPACE_REQUIRED", "Физические бирки и выдачу оформляйте в рабочей копии склада."
        )


def create_label(session, body, correlation):
    workspace(session, body.dataset_id)
    remnant = current_piece(session, body.dataset_id, body.remnant_id)
    if remnant.version != body.expected_version:
        raise AppError(409, "REMNANT_VERSION_CONFLICT", "Кусок изменён; перечитайте актуальную запись.")
    label_id = uid()
    payload = json.dumps(
        {
            "schema": "glassflow-piece-v1",
            "dataset_id": body.dataset_id,
            "remnant_id": remnant.remnant_id,
            "label_id": label_id,
            "printed_version": remnant.version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    label = PieceLabel(
        dataset_id=body.dataset_id,
        label_id=label_id,
        operator=body.operator,
        created_at=now(),
        printed_version=remnant.version,
        snapshot=remnant,
        snapshot_hash=canonical_hash(remnant.model_dump(mode="json")),
        scan_payload=payload,
    )
    session.add(
        ObjectRow(
            dataset_id=body.dataset_id,
            kind="piece_label",
            id=label_id,
            version=0,
            data=label.model_dump(mode="json"),
        )
    )
    audit(
        session,
        body.dataset_id,
        "piece_label.created",
        label_id,
        correlation,
        operator=body.operator,
        remnant_id=remnant.remnant_id,
        printed_version=remnant.version,
    )
    return label.model_dump(mode="json")


def label(session, dataset_id, label_id):
    return PieceLabel.model_validate(get_object(session, dataset_id, "piece_label", label_id).data)


def resolve_label(session, dataset_id, label_id):
    printed = label(session, dataset_id, label_id)
    current = current_piece(session, dataset_id, printed.snapshot.remnant_id)
    return PieceLabelResolved(
        label=printed,
        current=current,
        changed=canonical_hash(current.model_dump(mode="json")) != printed.snapshot_hash,
    )


def create_issue_sheet(session, body, services, correlation):
    workspace(session, body.dataset_id)
    kind = "order_sheet" if body.subject_type == "order" else "basket"
    row = get_object(session, body.dataset_id, kind, body.subject_id, body.expected_version)
    if body.subject_type == "order":
        subject = OrderSheet.model_validate(row.data)
        if (
            subject.lifecycle in {"completed", "cancelled"}
            or subject.quote_state != "confirmed"
            or not subject.facts
        ):
            raise AppError(409, "ORDER_NOT_READY", "Нужен актуальный подтверждённый заказ.")
        facts = orders.capture(session, subject, services)
    else:
        subject = Basket.model_validate(row.data)
        if subject.state not in {"confirmed", "reserved", "checked", "handed_over"} or not subject.binding:
            raise AppError(409, "BASKET_NOT_READY", "Нужна актуальная подтверждённая корзина.")
        facts = baskets.capture(session, subject, subject.binding, services)
    if canonical_hash(facts.model_dump(mode="json")) != subject.facts_hash:
        raise AppError(409, "ISSUE_SOURCE_STALE", "Расчёт или склад изменились; обновите задание.")
    snapshot = subject.model_dump(mode="json")
    if body.subject_type == "basket" and facts.stock:
        from glassflow.modules.cutting.workflows import current_selection
        value, _, _, _, versions = current_selection(session, subject, facts.stock.selection_ref)
        plan = CutPlan.model_validate(value["plan"])
        parts = {p.part_id: p for p in SolveInput.model_validate(value["cutting_snapshot"]).parts}
        snapshot["warehouse_pieces"] = []
        for remnant_id, expected in sorted(versions.items()):
            piece = current_piece(session, body.dataset_id, remnant_id)
            if piece.version != expected or facts.stock.remnant_versions.get(remnant_id) != expected:
                raise AppError(409, "ISSUE_SOURCE_STALE", "Кусок изменился; обновите складское задание.")
            placements = [p for p in plan.placements if p.remnant_id == remnant_id]
            snapshot["warehouse_pieces"].append({"remnant": piece.model_dump(mode="json"),
                "placements": [p.model_dump(mode="json") for p in placements],
                "parts": [parts[p.part_id].model_dump(mode="json") for p in placements]})
    document = WarehouseDocument(
        dataset_id=body.dataset_id,
        document_id=uid(),
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        subject_version=subject.version,
        created_at=now(),
        operator=body.operator,
        snapshot=snapshot,
        snapshot_hash=canonical_hash(snapshot),
    )
    session.add(
        ObjectRow(
            dataset_id=body.dataset_id,
            kind="warehouse_document",
            id=document.document_id,
            version=0,
            data=document.model_dump(mode="json"),
        )
    )
    audit(
        session,
        body.dataset_id,
        "warehouse_document.created",
        document.document_id,
        correlation,
        subject_id=body.subject_id,
        subject_version=subject.version,
        operator=body.operator,
    )
    return document.model_dump(mode="json")


def issue_sheet(session, dataset_id, document_id):
    return WarehouseDocument.model_validate(
        get_object(session, dataset_id, "warehouse_document", document_id).data
    )


def pdf_document(title, lines, *, qr_payload=None, small=False):
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
        raise AppError(503, "REPORT_FONT_MISSING", "Для печати нужен шрифт с кириллицей.")
    if "GlassFlowOperational" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("GlassFlowOperational", str(font)))
    style = ParagraphStyle(
        "operational", fontName="GlassFlowOperational", fontSize=9, leading=12, spaceAfter=5
    )
    heading = ParagraphStyle("heading", parent=style, fontSize=15, leading=19, spaceAfter=12)
    story = [Paragraph(escape(title), heading)]
    width = (A5 if small else A4)[0] - 24 * mm
    if qr_payload:
        qr = QrCodeWidget(qr_payload)
        x0, y0, x1, y1 = qr.getBounds()
        drawing = Drawing(32 * mm, 32 * mm, transform=[32 * mm / (x1 - x0), 0, 0, 32 * mm / (y1 - y0), 0, 0])
        drawing.add(qr)
        story.extend([drawing, Spacer(1, 4 * mm)])
    cells = [[Paragraph(escape(str(k)), style), Paragraph(escape(str(v)), style)] for k, v in lines]
    table = Table(cells, colWidths=[width * 0.31, width * 0.69], hAlign="LEFT", splitInRow=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E7E6")),
            ]
        )
    )
    story.append(table)
    output = io.BytesIO()
    SimpleDocTemplate(
        output,
        pagesize=A5 if small else A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
    ).build(story)
    return output.getvalue()


def label_pdf(value):
    piece = value.snapshot
    return pdf_document(
        "Бирка остатка",
        [
            ("Кусок", piece.remnant_id),
            ("Материал", piece.material_id),
            ("Размер, мм", f"{piece.dimensions.length_mm} × {piece.dimensions.width_mm}"),
            ("Место", piece.location_raw or "Неизвестно"),
            ("Версия", value.printed_version),
            ("Состояние при печати", piece.status),
            ("Набор", value.dataset_id),
            ("Создана", value.created_at),
            ("Оператор", value.operator),
            ("Проверка", "Личная проверка и выдача фиксируются в отдельном задании склада."),
            ("Важно", value.confirmation_note_ru),
        ],
        qr_payload=value.scan_payload,
        small=True,
    )


def issue_pdf(value):
    s = value.snapshot
    state = s.get("warehouse_state", s.get("state", ""))
    state_ru = {"unchecked": "Не сверено", "checked": "Сверено оператором", "handed_over": "Передано в работу",
                "confirmed": "Заказ подтвержден", "reserved": "Зарезервировано", "stale": "Требует обновления"}
    lines = [
        ("Тип/ID", f"{value.subject_type} / {value.subject_id}"),
        ("Версия задания", value.subject_version),
        ("Создан", value.created_at),
        ("Оператор", value.operator),
        ("Клиент", s.get("customer_ref", "")),
        ("Состояние склада", state_ru.get(state, state)),
    ]
    if value.subject_type == "order":
        task = s.get("warehouse_task") or {}
        facts = s.get("facts") or {}
        piece = task.get("remnant") or facts.get("remnant") or {}
        dims = task.get("requested_dimensions") or facts.get("requested_dimensions") or {}
        lines += [
            ("Материал", task.get("material_id") or piece.get("material_id", "")),
            ("Деталь, мм", f"{dims.get('length_mm', '?')} × {dims.get('width_mm', '?')}"),
            ("Количество", task.get("quantity", facts.get("quantity", ""))),
            ("Кусок / версия", f"{piece.get('remnant_id', '')} / {piece.get('version', '')}"),
            ("Место", piece.get("location_raw") or "Неизвестно"),
        ]
    else:
        for item in s.get("lines", []):
            request = item.get("request") or {}
            dims = request.get("dimensions") or {}
            lines.append(
                (
                    item.get("line_id", "Позиция"),
                    f"{item.get('text', '')}; {dims.get('length_mm', '?')} × {dims.get('width_mm', '?')} мм; количество {request.get('quantity', 'неизвестно')}",
                )
            )
        lines.append(("Совместный подбор", str(s.get("binding", {}).get("selection_ref", ""))))
        for item in s.get("warehouse_pieces", []):
            piece = item["remnant"]
            dims = piece["dimensions"]
            lines += [
                ("Кусок / версия", f"{piece['remnant_id']} / {piece['version']}"),
                ("Материал / размер", f"{piece['material_id']} / {dims['length_mm']} × {dims['width_mm']} мм"),
                ("Место", piece.get("location_raw") or "Неизвестно"),
                ("Детали из куска", "; ".join(f"{p['part_id']}: {p['dimensions']['length_mm']} × {p['dimensions']['width_mm']} мм"
                                             for p in item["parts"])),
            ]
        if not s.get("warehouse_pieces") and (s.get("facts") or {}).get("stock"):
            lines.append(("Места выдачи", "В старом снимке отсутствуют. Откройте актуальное задание в приложении."))
    lines.append(("Важно", value.notice_ru))
    return pdf_document("Лист задания складу", lines)
