"""HTTP commands for joint preparation and operator-recorded actual execution."""

from fastapi import APIRouter, Header, Request
from pydantic import Field

from glassflow.contracts.baskets import BasketBind
from glassflow.contracts.cutting import CutPlan, Part, Placement
from glassflow.contracts.material_use import MaterialUseRequest
from glassflow.core.jobs import enqueue, job_dto
from glassflow.core.models import ObjectRow, uid
from glassflow.core.uow import audit, canonical_hash, idempotent, write_transaction
from glassflow.modules.cutting.conversion import to_assignment
from glassflow.modules.cutting.domain import PartSpec
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.metrics import compute_metrics
from glassflow.modules.cutting.workflows import physical_snapshot, selection_input
from glassflow.modules.platform import baskets
from glassflow.modules.platform.material_use import scope_for

router = APIRouter(tags=["cutting-workflows"])


class ExecutionCreate(MaterialUseRequest):
    parts: list[Part] = Field(min_length=1, max_length=1000)
    placements: list[Placement] = Field(min_length=1, max_length=1000)


@router.post("/baskets/{basket_id}/selection")
def prepare(basket_id: str, body: BasketBind, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        def action():
            basket = baskets.load(session, body.dataset_id, basket_id, body.expected_version)
            snapshot = selection_input(session, basket, body)
            job = enqueue(session, body.dataset_id, "basket.selection", snapshot)
            session.flush()
            return job_dto(job).model_dump(mode="json")
        return idempotent(session, body.dataset_id, f"basket.selection:{basket_id}", idempotency_key,
                          body.model_dump(mode="json"), action)


@router.post("/cutting/executions")
def record_execution(body: ExecutionCreate, request: Request, idempotency_key: str | None = Header(None)):
    from glassflow.core.errors import AppError
    with write_transaction(request.app.state.session_factory) as session:
        def action():
            subject, scope = scope_for(session, body)
            # A final execution must account for every ordered copy. Dimensions
            # may differ with an explicit discrepancy reason at confirmation;
            # omitted copies or downgraded premium/material cannot disappear.
            if scope.subject_type == "order":
                from glassflow.core.domain_sources import quote_facts
                _, original, _ = quote_facts(session, scope.dataset_id, subject.facts.quote.quote_id)
                if (len(body.parts) != subject.facts.quantity or any(
                        p.material_id != subject.facts.quote.material_id or (original.premium and not p.premium)
                        for p in body.parts)):
                    raise AppError(409, "EXECUTION_PARTS_MISMATCH", "Исполнение должно включать все детали заказа с исходным материалом и качеством.")
            else:
                from glassflow.core.uow import get_object
                data = get_object(session, scope.dataset_id, "cut_selection", subject.facts.stock.selection_ref).data
                expected = {p["part_id"]: p for p in data["cutting_snapshot"]["parts"]}
                if set(expected) != {p.part_id for p in body.parts} or any(
                    p.material_id != expected[p.part_id]["material_id"] or (expected[p.part_id]["premium"] and not p.premium)
                    for p in body.parts):
                    raise AppError(409, "EXECUTION_PARTS_MISMATCH", "Исполнение должно включать все детали совместного плана.")
            parts = {p.part_id: PartSpec(p.part_id, scope.subject_id, p.material_id,
                p.dimensions.length_mm, p.dimensions.width_mm, p.premium) for p in body.parts}
            if len(parts) != len(body.parts):
                raise AppError(422, "DUPLICATE_PART", "Повтор фактической детали.")
            snapshot = physical_snapshot(session, scope, parts)
            report = validate_plan(snapshot, [to_assignment(p) for p in body.placements])
            if not report.valid or any(p.remnant_id == "NEW" for p in body.placements):
                raise AppError(409, "ACTUAL_EXECUTION_INVALID", "Фактическая геометрия недопустима.",
                               conflicts=[i.as_text() for i in report.issues])
            metrics, free = compute_metrics(snapshot, report)
            if scope.subject_type == "basket":
                planned_area = subject.facts.stock.planned_area_mm2
                planned_value = subject.facts.stock.planned_material_value_tg
            else:
                from decimal import Decimal
                facts = subject.facts
                planned_area = facts.requested_dimensions.length_mm * facts.requested_dimensions.width_mm * facts.quantity
                planned_value = format(Decimal(planned_area) / Decimal(1_000_000) * snapshot.materials[facts.quote.material_id].price_per_m2, ".2f")
            plan = CutPlan(dataset_id=scope.dataset_id, plan_id=uid(), revision=1, status="validated",
                placements=body.placements, metrics=metrics, free_original_remnant_ids=free, search_status="feasible")
            ref = uid()
            value = {"execution_ref": ref, "execution_version": 1, "scope": scope.model_dump(mode="json"),
                "parts": [p.model_dump(mode="json") for p in body.parts], "actual_plan": plan.model_dump(mode="json"),
                "planned_area_mm2": planned_area, "planned_material_value_tg": planned_value,
                "material_price_version": canonical_hash({k: str(m.price_per_m2) for k, m in snapshot.materials.items()}),
                "operator": body.operator, "note": body.note}
            session.add(ObjectRow(dataset_id=body.dataset_id, kind="cut_execution", id=ref, version=1, data=value))
            audit(session, body.dataset_id, "cut.execution_recorded", ref, request.state.correlation_id,
                  operator=body.operator, note=body.note, source_hash=canonical_hash(value))
            return {"execution_ref": ref, "execution_version": 1, "actual_area_mm2": metrics.covered_area_mm2,
                    "actual_material_value_tg": metrics.replacement_value_tg}
        return idempotent(session, body.dataset_id, "cut.execution", idempotency_key, body.model_dump(mode="json"), action)


@router.post("/cutting/execution-template")
def execution_template(body: MaterialUseRequest, request: Request):
    """A proposed layout, explicitly NOT evidence of physical execution."""
    from glassflow.core.uow import get_object
    from glassflow.modules.cutting.service import CuttingService
    with request.app.state.session_factory() as session:
        subject, scope = scope_for(session, body)
        if scope.subject_type == "basket":
            data = get_object(session, scope.dataset_id, "cut_selection", subject.facts.stock.selection_ref).data
            parts = data["cutting_snapshot"]["parts"]
            placements = data["plan"]["placements"]
        else:
            facts = subject.facts
            from glassflow.core.domain_sources import quote_facts
            _, original, _ = quote_facts(session, scope.dataset_id, facts.quote.quote_id)
            parts = [Part(part_id=f"actual:{i}", order_id=scope.subject_id, material_id=facts.quote.material_id,
                dimensions=facts.requested_dimensions, premium=original.premium).model_dump(mode="json") for i in range(facts.quantity)]
            snapshot = physical_snapshot(session, scope, {p["part_id"]: PartSpec(p["part_id"], scope.subject_id,
                p["material_id"], p["dimensions"]["length_mm"], p["dimensions"]["width_mm"], False) for p in parts})
            remnant = snapshot.remnants[facts.remnant.remnant_id]
            part = next(iter(snapshot.parts.values()))
            positions = CuttingService._positions(snapshot, part, remnant, [], facts.quantity, snapshot.is_tempered(part.material_id))
            placements = [Placement(part_id=p["part_id"], remnant_id=remnant.remnant_id, x_mm=x, y_mm=y, rot=rot).model_dump(mode="json")
                          for p, (x, y, rot) in zip(parts, positions, strict=True)]
        return {"parts": parts, "placements": placements, "physical_execution_confirmed": False,
                "message_ru": "Проверьте фактические детали, размеры и размещения перед записью исполнения."}
