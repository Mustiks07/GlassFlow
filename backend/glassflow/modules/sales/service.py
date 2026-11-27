import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import select

from glassflow.contracts.crm import Buyer, SaleCard
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow, now, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.imports import dataset, records

BUYER_FIELDS = ["name", "city", "category", "url", "why", "source_url", "score"]
CATEGORIES = {
    "мебельная фабрика",
    "дизайн-студия",
    "строительная компания",
    "окна и двери",
    "магазин",
    "торговый центр",
    "кафе или ресторан",
    "салон",
    "другое",
}


def normalized_name(value):
    return re.sub(r"\W+", "", value.casefold())


def public_url(value):
    p = urlsplit(value)
    return (
        p.scheme in {"http", "https"}
        and bool(p.hostname)
        and "." in p.hostname
        and not p.username
        and not p.password
    )


def import_buyers(session, dataset_id, csv_bytes, evidence_bytes, correlation):
    dataset(session, dataset_id)
    errors = []
    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != BUYER_FIELDS:
            raise ValueError("Expected exact buyer columns")
        raw = list(reader)
        payload = json.loads(evidence_bytes.decode("utf-8-sig"))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("records"), list)
            or not payload.get("dedupe_policy")
        ):
            raise ValueError("Expected evidence records and dedupe_policy")
        evidence = payload["records"]
    except (UnicodeError, ValueError, csv.Error):
        raise AppError(
            422, "BUYER_FORMAT_INVALID", "Нужны точный CSV покупателей и evidence records/dedupe_policy."
        ) from None
    if len(raw) != 50:
        errors.append("Нужно ровно 50 организаций")
    buyers, names, entities = [], set(), set()
    for index, row in enumerate(raw, 2):
        try:
            if None in row or any(v is None or not v.strip() for v in row.values()):
                raise ValueError()
            if not re.fullmatch(r"\d+", row["score"]):
                raise ValueError()
            buyer = Buyer(**{**row, "score": int(row["score"])})
            if (
                buyer.category not in CATEGORIES
                or not public_url(buyer.url)
                or not public_url(buyer.source_url)
            ):
                raise ValueError()
            name = normalized_name(buyer.name)
            if name in names:
                errors.append(f"Строка {index}: повтор названия")
            names.add(name)
            matching = [e for e in evidence if isinstance(e, dict) and e.get("name") == buyer.name]
            if len(matching) != 1:
                errors.append(f"Строка {index}: нет однозначного evidence")
                match = {}
            else:
                match = matching[0]
            required = [
                "name",
                "city",
                "profile",
                "source_url",
                "checked_at",
                "reviewer",
                "confirmation",
                "entity_id",
            ]
            if not all(isinstance(match.get(k), str) and match[k].strip() for k in required):
                errors.append(f"Строка {index}: неполное evidence")
            elif match["city"] != buyer.city or match["source_url"] != buyer.source_url:
                errors.append(f"Строка {index}: evidence не совпадает с CSV")
            else:
                try:
                    checked = date.fromisoformat(match["checked_at"][:10])
                    if checked > date.today():
                        raise ValueError()
                except ValueError:
                    errors.append(f"Строка {index}: неверная дата проверки")
                if match["entity_id"] in entities:
                    errors.append(f"Строка {index}: дублирующийся организационный объект")
                entities.add(match["entity_id"])
            buyer.buyer_id = hashlib.sha256(name.encode("utf8")).hexdigest()[:24]
            buyers.append(buyer.model_dump())
        except (ValidationError, ValueError, TypeError):
            errors.append(f"Строка {index}: неверные поля покупателя")
    if sum(b["city"].casefold() in {"астана", "astana", "г. астана"} for b in buyers) < 30:
        errors.append("Нужно не менее 30 организаций в Астане")
    if len({b["category"] for b in buyers}) < 5:
        errors.append("Нужно не менее 5 разрешенных категорий")
    version = canonical_hash(
        [hashlib.sha256(csv_bytes).hexdigest(), hashlib.sha256(evidence_bytes).hexdigest()]
    )
    row = session.get(ObjectRow, (dataset_id, "buyer_registry", version))
    if row is None:
        row = ObjectRow(
            dataset_id=dataset_id,
            kind="buyer_registry",
            id=version,
            version=0,
            data={
                "buyers": buyers,
                "evidence": payload,
                "errors": errors,
                "created_at": now(),
                "status": "needs_review" if errors else "verified",
                "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
                "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                "verification": "Проверены полнота и согласованность evidence рецензента; не факт покупки",
            },
        )
        session.add(row)
        audit(session, dataset_id, "buyers.import", version, correlation)
    return {
        "version": version,
        "status": row.data["status"],
        "errors": row.data["errors"],
        "count": len(buyers),
    }


def registry(session, dataset_id, version, require_verified=True):
    row = get_object(session, dataset_id, "buyer_registry", version)
    if require_verified and row.data["status"] != "verified":
        raise AppError(
            409, "BUYERS_NOT_VERIFIED", "Реестр не прошел проверку evidence.", conflicts=row.data["errors"]
        )
    return row


def card_price(length_mm, width_mm, rate, factor):
    factor = Decimal(factor)
    if not Decimal("0.30") <= factor <= Decimal("0.70"):
        raise AppError(422, "FACTOR_OUT_OF_RANGE", "Коэффициент должен быть от 0.30 до 0.70.")
    equivalent = Decimal(length_mm) * Decimal(width_mm) / Decimal(1_000_000) * Decimal(rate)
    value = equivalent * factor
    for places in range(2, 13):
        rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if equivalent * Decimal("0.30") <= rounded <= equivalent * Decimal("0.70"):
            return format(rounded, "f")
    raise AppError(422, "PRICE_PRECISION_UNRESOLVED", "Нельзя округлить цену в разрешенных границах.")


def source_plan(session, services, dataset_id, plan_id, revision):
    source = services.sales_source
    if source is None:
        raise AppError(503, "CUTTING_SERVICE_UNAVAILABLE", "Источник утвержденного плана не подключен.")
    plan = source.get_plan(session, dataset_id, plan_id)
    if (
        plan.dataset_id != dataset_id
        or plan.plan_id != plan_id
        or plan.revision != revision
        or plan.status not in {"validated", "committed"}
    ):
        raise AppError(409, "STALE_PLAN", "Нужна финальная проверенная ревизия выбранного плана.")
    validation = source.validate_plan(session, dataset_id, plan)
    if not validation.valid:
        raise AppError(
            409, "INVALID_PLAN", "План не прошел независимую проверку.", conflicts=validation.errors
        )
    return plan


def generate_cards(session, body, services, correlation):
    plan = source_plan(session, services, body.dataset_id, body.plan_id, body.plan_revision)
    buyers = registry(session, body.dataset_id, body.buyer_registry_version).data["buyers"]
    originals = {r.public_id: r.data for r in records(session, body.dataset_id, "stock")}
    materials = {r.public_id: r.data for r in records(session, body.dataset_id, "materials")}
    used = {p.remnant_id for p in plan.placements if p.remnant_id != "NEW"}
    candidates = []
    for rid in plan.free_original_remnant_ids:
        if rid not in originals or rid in used or rid in {r.remnant_id for r in candidates}:
            continue
        current = services.sales_source.get_remnant(session, body.dataset_id, rid)
        if (
            current.dataset_id == body.dataset_id
            and current.remnant_id == rid
            and current.status == "available"
        ):
            candidates.append(current)
    if len(candidates) < 5:
        raise AppError(
            409,
            "RECOMPUTE_REQUIRED",
            "Меньше пяти целых свободных исходных кусков; нужен совместный пересчет с C2.",
            conflicts=[f"free_original_count:{len(candidates)}", "coverage_delta:requires_C2_comparison"],
        )
    result = []
    for remnant in candidates[:5]:
        original = originals[remnant.remnant_id]
        material = materials[original["material_id"]]
        # Contest cards describe the full original piece, never a virtual child or changed measurement.
        if (remnant.dimensions.length_mm, remnant.dimensions.width_mm, remnant.material_id) != (
            int(original["длина_мм"]),
            int(original["ширина_мм"]),
            original["material_id"],
        ):
            raise AppError(
                409, "ORIGINAL_CHANGED", "Замер исходного куска изменился; выберите актуальный снимок."
            )
        length, width = int(original["длина_мм"]), int(original["ширина_мм"])
        price = card_price(length, width, material["цена_нового_стекла_тг_за_м2"], body.factor)
        tempered = material["закалённое"] == "1"
        application = (
            "готовая вставка подходящего размера без подрезки"
            if tempered
            else "вставки и элементы интерьера после проверки размеров"
        )
        condition = "с дефектом" if remnant.defect else "без отмеченного дефекта"
        terms = (
            ("зеркал", "мебел", "интерьер")
            if "mirror" in remnant.material_id
            else ("стекл", "перегород", "витрин")
        )
        top = sorted(
            buyers,
            key=lambda b: (
                -sum(t in (b["why"] + b["category"]).casefold() for t in terms),
                -b["score"],
                b["buyer_id"],
            ),
        )[:3]
        card = SaleCard(
            card_id=uid(),
            dataset_id=body.dataset_id,
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            remnant_id=remnant.remnant_id,
            remnant_version=remnant.version,
            buyer_registry_version=body.buyer_registry_version,
            factor=body.factor,
            title=f"{material['название']}, {length}×{width} мм",
            price_tg=price,
            description=f"Целый исходный остаток {length}×{width} мм, {condition}. Место: {remnant.location_raw}. Возможное применение: {application}. Совместимость уточняет менеджер.",
            target_buyer=top[0]["name"],
            top3_buyers=[b["name"] for b in top],
            top3_buyer_ids=[b["buyer_id"] for b in top],
            status="ready",
        )
        session.add(
            ObjectRow(
                dataset_id=body.dataset_id,
                kind="sale_card",
                id=card.card_id,
                version=0,
                data=card.model_dump(),
            )
        )
        audit(session, body.dataset_id, "card.create", card.card_id, correlation, plan_revision=plan.revision)
        result.append(card.model_dump())
    return {"cards": result}


def recheck_card(session, row, services, correlation):
    card = SaleCard.model_validate(row.data)
    if card.status == "stale":
        return card
    stale = False
    try:
        plan = source_plan(session, services, row.dataset_id, card.plan_id, card.plan_revision)
        current = services.sales_source.get_remnant(session, row.dataset_id, card.remnant_id)
        registry(session, row.dataset_id, card.buyer_registry_version)
        stale = (
            card.remnant_id not in plan.free_original_remnant_ids
            or current.status != "available"
            or current.version != card.remnant_version
        )
    except AppError as exc:
        if exc.status == 503:
            raise
        stale = True
    if stale:
        card.status = "stale"
        card.version += 1
        row.version, row.data = card.version, card.model_dump()
        audit(session, row.dataset_id, "card.stale", card.card_id, correlation, after=card.version)
    return card


def list_cards(session, dataset_id, services, correlation, plan_id=None):
    dataset(session, dataset_id)
    result = []
    for row in session.scalars(
        select(ObjectRow).where(ObjectRow.dataset_id == dataset_id, ObjectRow.kind == "sale_card")
    ):
        if plan_id is None or row.data["plan_id"] == plan_id:
            result.append(recheck_card(session, row, services, correlation))
    return result
