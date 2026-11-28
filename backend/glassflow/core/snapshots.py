"""DTO mapping only, no geometry, prices or mutable duplicate domain repositories."""

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import Material, Part, Remnant, SolveInput, SolverConfig


def cutting_snapshot(dataset_id, rows, config):
    return SolveInput(
        dataset_id=dataset_id,
        config=SolverConfig.model_validate(config),
        materials=[
            Material(
                material_id=r["material_id"],
                name=r["название"],
                thickness_mm=int(r["толщина_мм"]),
                unit_price_tg=str(r["цена_нового_стекла_тг_за_м2"]),
                tempered=r["закалённое"] == "1",
            )
            for r in rows["materials"]
        ],
        remnants=[
            Remnant(
                dataset_id=dataset_id,
                remnant_id=r["remnant_id"],
                material_id=r["material_id"],
                dimensions=Dimensions(length_mm=int(r["длина_мм"]), width_mm=int(r["ширина_мм"])),
                age_days=int(r["возраст_дней"]) if r["возраст_дней"] is not None else None,
                defect=r["дефект"] == "1",
                location_raw=r["место"],
                status="available",
                version=0,
            )
            for r in rows["stock"]
        ],
        parts=[
            Part(
                part_id=r["part_id"],
                order_id=r["order_id"],
                material_id=r["material_id"],
                dimensions=Dimensions(length_mm=int(r["длина_мм"]), width_mm=int(r["ширина_мм"])),
                premium=r["премиум"] == "1",
                product_type=r["тип_изделия"],
            )
            for r in rows["orders"]
        ],
    )


def sale_readiness_snapshot(session, dataset_id, registry_version, config, *, base_plan_id=None):
    """Trusted current C2 stock + reviewed sales evidence. Never accepts browser eligibility."""
    from glassflow.contracts.cutting import SolveRequest
    from glassflow.core.uow import canonical_hash
    from glassflow.modules.cutting.engine import input_hash
    from glassflow.modules.cutting.sale_readiness import inventory_fingerprint
    from glassflow.modules.cutting.service import CuttingService
    from glassflow.modules.platform.imports import records
    from glassflow.modules.sales.matching import match_buyers
    from glassflow.modules.sales.service import registry

    service = CuttingService(session)
    base = service.get_plan(dataset_id, base_plan_id) if base_plan_id else None
    data = service.solve_input(SolveRequest(dataset_id=dataset_id, base_plan_id=base_plan_id, config=config,
        mode="keep_committed" if base and base.status == "committed" else "replan"))
    buyers = registry(session, dataset_id, registry_version)
    originals = {r.public_id: r.data for r in records(session, dataset_id, "stock")}
    materials = {r.public_id: r.data for r in records(session, dataset_id, "materials")}
    eligible, evidence = [], {}
    blocked = set(data.unavailable_remnant_ids) | set(data.occupied_remnant_ids)
    for piece in data.remnants:
        raw = originals.get(piece.remnant_id)
        if (not raw or not piece.original or piece.status != "available" or piece.remnant_id in blocked
                or (piece.material_id, piece.dimensions.length_mm, piece.dimensions.width_mm) !=
                (raw["material_id"], int(raw["длина_мм"]), int(raw["ширина_мм"]))):
            continue
        matches = match_buyers(buyers, piece, materials[piece.material_id])
        if len({m.buyer_id for m in matches}) >= 3:
            eligible.append(piece.remnant_id)
            evidence[piece.remnant_id] = [m.model_dump(mode="json") for m in matches]
    context = {"registry_version": registry_version, "eligible_original_ids": sorted(eligible),
               "registry_fingerprint": canonical_hash({"id": buyers.id, "version": buyers.version, "data": buyers.data}),
               "inventory_fingerprint": inventory_fingerprint(data), "input_fingerprint": input_hash(data),
               "matching_fingerprint": canonical_hash(evidence), "base_plan_id": base_plan_id}
    return data, context
