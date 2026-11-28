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
