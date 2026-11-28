"""Joint basket selections and recorded physical executions, using C2 geometry.

Selections are durable artifacts, never a collection of independent availability checks.
Executions contain operator-supplied actual geometry and cannot be inferred from a reserve.
All inventory mutations use the parent transaction and canonical CutReservation rows.
"""

from dataclasses import replace

from sqlalchemy import select

from glassflow.contracts.baskets import BasketFacts, BasketLineFacts, BasketReservation, BasketStockFacts
from glassflow.contracts.cutting import (
    ConsumeRequest,
    CutPlan,
    Part,
    ReleaseRequest,
    ReserveRequest,
    SolveInput,
    SolverConfig,
)
from glassflow.contracts.material_use import MaterialUseAssessment, MaterialUseReceipt
from glassflow.core.domain_sources import domain_error, quote_facts
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow, now, uid
from glassflow.core.uow import canonical_hash, get_object
from glassflow.modules.cutting.conversion import input_from_snapshot, snapshot_from_input, to_assignment
from glassflow.modules.cutting.domain import PartSpec, Snapshot
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.metrics import compute_metrics
from glassflow.modules.cutting.service import CuttingService


def selection_input(session, basket, binding):
    service = CuttingService(session)
    snapshot = service.load_snapshot(basket.dataset_id)
    active = service._active_plan_row(basket.dataset_id)
    occupied = {a.remnant_id for a in service._assignments(active)} if active else set()
    data = input_from_snapshot(snapshot, config=SolverConfig(profile="quick", minimum_free_remnants=0),
                               unavailable_remnant_ids=sorted(occupied))
    data.parts = []
    refs = {r.line_id: r for r in binding.lines}
    for line in basket.lines:
        ref = refs.get(line.line_id)
        if not ref or not ref.quote_id:
            raise AppError(409, "BASKET_QUOTE_REQUIRED", "Нужны расчеты всех строк.")
        quote, request, _ = quote_facts(session, basket.dataset_id, ref.quote_id)
        if (quote.customer_id != basket.customer_ref or quote.revision != ref.quote_revision
                or line.request is None or request != line.request):
            raise AppError(409, "BASKET_QUOTE_MISMATCH", "Расчет не соответствует владельцу и параметрам строки.")
        if quote.material_id:
            if not request.dimensions or not request.quantity:
                raise AppError(409, "BASKET_DIMENSIONS_REQUIRED", "Уточните размеры и количество.")
            for copy in range(request.quantity):
                data.parts.append(Part(part_id=f"{line.line_id}:{copy}", order_id=basket.basket_id,
                    material_id=quote.material_id, dimensions=request.dimensions, premium=request.premium))
    return {"dataset_id": basket.dataset_id, "basket_id": basket.basket_id,
            "input_hash": basket.input_hash, "binding": binding.model_dump(mode="json"),
            "cutting_snapshot": data.model_dump(mode="json"), "solver_config": data.config.model_dump()}


def solve_selection(snapshot, context):
    from glassflow.modules.cutting.engine import CuttingEngine
    data = SolveInput.model_validate(snapshot["cutting_snapshot"])
    plan = CuttingEngine().solve(data, context)
    return {**snapshot, "plan": plan.model_dump(mode="json"), "selection_ref": uid(), "selection_version": 1}


def validate_selection(snapshot, result):
    from glassflow.modules.cutting.engine import CuttingEngine
    value = result.get("plan", result)  # incumbents are the ordinary CutPlan DTO
    return CuttingEngine().validate(SolveInput.model_validate(snapshot["cutting_snapshot"]), CutPlan.model_validate(value)).valid


def store_selection(session, dataset_id, result):
    if result["dataset_id"] != dataset_id:
        raise AppError(409, "SELECTION_SCOPE", "Набор плана не совпал.")
    session.add(ObjectRow(dataset_id=dataset_id, kind="cut_selection", id=result["selection_ref"],
                          version=1, data=result.copy()))


def current_selection(session, basket, reference):
    row = get_object(session, basket.dataset_id, "cut_selection", reference)
    value = row.data
    if value["basket_id"] != basket.basket_id or value["input_hash"] != basket.input_hash:
        raise AppError(409, "SELECTION_INPUT_CHANGED", "Совместный план относится к прежним строкам.")
    original = SolveInput.model_validate(value["cutting_snapshot"])
    service = CuttingService(session)
    live = service.load_snapshot(basket.dataset_id)
    used = {p.remnant_id for p in CutPlan.model_validate(value["plan"]).placements if p.remnant_id != "NEW"}
    own = bundle_for_basket(session, basket.dataset_id, basket.basket_id)
    owned = set(own.data["reservations"]) if own and own.data["state"] == "active" else set()
    originals = {r.remnant_id: r for r in original.remnants}
    for rid in used:
        current = live.remnants[rid]
        if rid in owned:
            expected = own.data["remnant_versions"][rid]
            allowed_status = "reserved"
        else:
            expected = originals[rid].version
            allowed_status = "available"
        if current.version != expected or current.status != allowed_status:
            raise AppError(409, "SELECTION_STALE", "Склад изменился после совместного подбора.", conflicts=[rid])
    available = {rid: replace(r, status="available") if rid in owned else r for rid, r in live.remnants.items()}
    snap = snapshot_from_input(original)
    snap.remnants = available
    assignments = [to_assignment(p) for p in CutPlan.model_validate(value["plan"]).placements]
    report = validate_plan(snap, assignments, unavailable_remnant_ids=original.unavailable_remnant_ids)
    if not report.valid:
        raise AppError(409, "SELECTION_INVALID", "Совместная геометрия больше не допустима.")
    metrics, _ = compute_metrics(snap, report)
    return value, snap, report, metrics, {rid: live.remnants[rid].version for rid in used}


def bundle_for_basket(session, dataset_id, basket_id):
    return session.scalar(select(ObjectRow).where(ObjectRow.dataset_id == dataset_id,
        ObjectRow.kind == "cut_bundle", ObjectRow.id == basket_id))


class BasketSource:
    def capture(self, session, basket, binding):
        lines = []
        refs = {r.line_id: r for r in binding.lines}
        for draft in basket.lines:
            ref = refs.get(draft.line_id)
            if not ref or not ref.quote_id:
                lines.append(BasketLineFacts(line_id=draft.line_id, kind="unresolved", clarification=draft.clarification or "Нужен расчет"))
                continue
            quote, request, _ = quote_facts(session, basket.dataset_id, ref.quote_id)
            product = __import__("glassflow.core.domain_sources", fromlist=["intelligence"]).intelligence(session).catalog_for(basket.dataset_id).kb.product(quote.catalog_product_id)
            glass = product.kind == "material"
            lines.append(BasketLineFacts(line_id=draft.line_id, kind="glass" if glass else "catalog",
                quote=quote, quote_customer_ref=quote.customer_id,
                source_request_hash=canonical_hash(request.model_dump(mode="json")),
                compatibility="confirmed" if glass else "not_required"))
        stock = None
        if binding.selection_ref:
            value, _, _, metrics, versions = current_selection(session, basket, binding.selection_ref)
            stock = BasketStockFacts(dataset_id=basket.dataset_id, basket_id=basket.basket_id,
                input_hash=value["input_hash"], selection_ref=binding.selection_ref,
                selection_version=value["selection_version"], line_ids=[r.line_id for r in lines if r.kind == "glass"],
                remnant_versions=versions, validated=True, validation_ref=canonical_hash(value["plan"]),
                planned_area_mm2=metrics.covered_area_mm2, planned_material_value_tg=metrics.replacement_value_tg)
        return BasketFacts(dataset_id=basket.dataset_id, basket_id=basket.basket_id,
                           input_hash=basket.input_hash, lines=lines, stock=stock)

    def reserve(self, session, basket):
        value, snapshot, _, _, versions = current_selection(session, basket, basket.facts.stock.selection_ref)
        service = CuttingService(session)
        grouped = {}
        for placement in CutPlan.model_validate(value["plan"]).placements:
            if placement.remnant_id != "NEW":
                grouped.setdefault(placement.remnant_id, placement)
        reservations, post = {}, {}
        for rid, placement in grouped.items():
            part = snapshot.parts[placement.part_id]
            from glassflow.contracts.common import Dimensions
            change = domain_error(lambda: service.reserve(rid, ReserveRequest(dataset_id=basket.dataset_id,
                expected_version=versions[rid], owner_context=f"basket:{basket.basket_id}:{basket.revision}",
                material_id=part.material_id, dimensions=Dimensions(length_mm=part.length_mm, width_mm=part.width_mm),
                premium=part.premium, x_mm=placement.x_mm, y_mm=placement.y_mm, rot=placement.rot)))
            reservations[rid], post[rid] = change.reservation.reservation_id, change.remnant.version
        reference = BasketReservation(dataset_id=basket.dataset_id, reservation_id=uid(), basket_id=basket.basket_id,
            basket_revision=basket.revision, selection_ref=value["selection_ref"], selection_version=value["selection_version"],
            remnant_versions=post, state="active")
        data = {**reference.model_dump(mode="json"), "reservations": reservations}
        row = bundle_for_basket(session, basket.dataset_id, basket.basket_id)
        if row is not None:
            if row.data["state"] == "active":
                raise AppError(409, "BUNDLE_ACTIVE", "Корзина уже имеет резерв.")
            # Keep old bundles addressable by reservation ID for immutable history.
        session.add(ObjectRow(dataset_id=basket.dataset_id, kind="cut_bundle_history", id=reference.reservation_id, version=0, data=data))
        if row is None:
            session.add(ObjectRow(dataset_id=basket.dataset_id, kind="cut_bundle", id=basket.basket_id, version=0, data=data))
        else:
            row.data, row.version = data, row.version + 1
        session.flush()
        return reference

    def reservation(self, session, dataset_id, reservation_id):
        row = get_object(session, dataset_id, "cut_bundle_history", reservation_id)
        value = row.data.copy()
        service = CuttingService(session)
        states, versions = [], {}
        for rid, ref in value["reservations"].items():
            states.append(service._reservation(dataset_id, ref).status)
            versions[rid] = service.get_remnant(dataset_id, rid).version
        if states and len(set(states)) != 1:
            raise AppError(409, "BUNDLE_PARTIAL", "Складской резерв изменен частично.")
        value["state"] = states[0] if states else value["state"]
        value["remnant_versions"] = versions
        return BasketReservation.model_validate({k: v for k, v in value.items() if k != "reservations"})

    def release(self, session, reservation):
        if self.reservation(session, reservation.dataset_id, reservation.reservation_id) != reservation:
            raise AppError(409, "BUNDLE_CHANGED", "Резерв корзины изменился.")
        history = get_object(session, reservation.dataset_id, "cut_bundle_history", reservation.reservation_id)
        service = CuttingService(session)
        for ref in history.data["reservations"].values():
            res = service._reservation(reservation.dataset_id, ref)
            domain_error(lambda: service.release_reservation(ref, ReleaseRequest(dataset_id=reservation.dataset_id,
                expected_version=res.version, reason="Снятие резерва корзины")))
        data = {**history.data, "state": "released"}
        history.data = data
        bundle_for_basket(session, reservation.dataset_id, reservation.basket_id).data = data
        return self.reservation(session, reservation.dataset_id, reservation.reservation_id)


def physical_snapshot(session, scope, parts):
    service = CuttingService(session)
    live = service.load_snapshot(scope.dataset_id)
    remnants = {}
    for rid, version in scope.remnant_versions.items():
        row = service._remnant_row(scope.dataset_id, rid)
        res = service._active_reservation(row.id)
        owner = f"{scope.subject_type}:{scope.subject_id}:{scope.subject_revision}"
        if (res is None or res.owner_context != owner or live.remnants[rid].version != version
                or (scope.subject_type == "order" and res.id != scope.reservation_id)):
            raise AppError(409, "EXECUTION_RESERVATION_CHANGED", "Исполнение требует собственного действующего резерва.")
        remnants[rid] = replace(live.remnants[rid], status="available")
    return Snapshot(scope.dataset_id, live.materials, remnants, parts)


class MaterialSource:
    def assess(self, session, scope, execution_ref, execution_version):
        row = get_object(session, scope.dataset_id, "cut_execution", execution_ref, execution_version)
        data = row.data
        if data["scope"] != scope.model_dump(mode="json"):
            raise AppError(409, "EXECUTION_SCOPE_CHANGED", "Исполнение относится к другому состоянию заказа.")
        parts = {p.part_id: PartSpec(p.part_id, scope.subject_id, p.material_id,
                 p.dimensions.length_mm, p.dimensions.width_mm, p.premium) for p in
                 [Part.model_validate(p) for p in data["parts"]]}
        snapshot = physical_snapshot(session, scope, parts)
        assignments = [to_assignment(p) for p in CutPlan.model_validate(data["actual_plan"]).placements]
        report = validate_plan(snapshot, assignments)
        if not report.valid or any(a.remnant_id == "NEW" for a in assignments):
            raise AppError(409, "ACTUAL_EXECUTION_INVALID", "Фактическое исполнение не прошло независимую проверку.")
        metrics, _ = compute_metrics(snapshot, report)
        return MaterialUseAssessment(scope=scope, execution_ref=execution_ref, execution_version=execution_version,
            planned_area_mm2=data["planned_area_mm2"], planned_material_value_tg=data["planned_material_value_tg"],
            actual_area_mm2=metrics.covered_area_mm2, actual_material_value_tg=metrics.replacement_value_tg,
            validation_ref=canonical_hash(data["actual_plan"]), material_price_version=data["material_price_version"])

    def confirm(self, session, assessment, confirmation_id, operator, note):
        fresh = self.assess(session, assessment.scope, assessment.execution_ref, assessment.execution_version)
        if fresh != assessment:
            raise AppError(409, "EXECUTION_CHANGED", "Фактическое исполнение изменилось.")
        scope = assessment.scope
        if scope.subject_type == "order":
            reservations = {next(iter(scope.remnant_versions)): scope.reservation_id}
        else:
            reservations = get_object(session, scope.dataset_id, "cut_bundle_history", scope.reservation_id).data["reservations"]
        service = CuttingService(session)
        post = {}
        for rid, ref in reservations.items():
            change = domain_error(lambda: service.consume(rid, ConsumeRequest(dataset_id=scope.dataset_id,
                expected_version=scope.remnant_versions[rid], reservation_id=ref,
                reason=f"Исполнение {assessment.execution_ref}; {operator}: {note}")))
            post[rid] = change.remnant.version
        if scope.subject_type == "basket":
            history = get_object(session, scope.dataset_id, "cut_bundle_history", scope.reservation_id)
            history.data = {**history.data, "state": "consumed", "remnant_versions": post}
            bundle_for_basket(session, scope.dataset_id, scope.subject_id).data = history.data
        return MaterialUseReceipt(assessment=assessment, confirmation_id=confirmation_id,
            source_event_ref=f"cut-execution:{assessment.execution_ref}", reservation_state="consumed",
            post_remnant_versions=post, confirmed_at=now())
