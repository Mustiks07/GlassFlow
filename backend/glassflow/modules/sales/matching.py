"""Deterministic U03 matching from reviewed structured evidence; no claim of buyer interest."""

from glassflow.contracts.crm import BuyerApplicationEvidence, BuyerMatch
from glassflow.core.uow import canonical_hash

APPLICATIONS = {
    "furniture_insert": "мебельная вставка",
    "mirror_interior": "зеркальный элемент интерьера",
    "display_insert": "вставка витрины",
    "partition_panel": "панель перегородки",
    "finished_panel": "готовая панель исходного размера",
}


def snapshot_hash(remnant, version):
    return canonical_hash({"remnant": remnant.model_dump(mode="json"),
                           "registry_version": version, "policy": "evidence-v1"})


def fits(dimensions, application):
    low, high = application.min_dimensions, application.max_dimensions
    return any(length >= low.length_mm and width >= low.width_mm
               and (high is None or length <= high.length_mm and width <= high.width_mm)
               for length, width in ((dimensions.length_mm, dimensions.width_mm),
                                     (dimensions.width_mm, dimensions.length_mm)))


def match_buyers(registry_row, remnant, material):
    if remnant.status != "available":
        return []
    evidence = {e["name"]: e for e in registry_row.data["evidence"]["records"]}
    matches = []
    tempered = material["закалённое"] == "1"
    for buyer in sorted(registry_row.data["buyers"], key=lambda b: (-b["score"], b["buyer_id"])):
        proof = evidence[buyer["name"]]
        for raw in proof.get("applications", []):
            application = BuyerApplicationEvidence.model_validate(raw)
            if (remnant.material_id not in application.material_ids
                    or not fits(remnant.dimensions, application)
                    or (tempered and application.requires_cutting)
                    or (application.application == "mirror_interior"
                        and "зеркал" not in material["название"].casefold())):
                continue
            label = APPLICATIONS[application.application]
            constraints = ["Предполагаемое применение; размеры и пригодность подтверждает менеджер.",
                           "Нет подтверждения интереса организации или факта покупки."]
            if tempered:
                constraints.append("Закаленное стекло: только исходный размер, подрезка запрещена.")
            elif application.requires_cutting:
                constraints.append("Подрезка требует отдельной проверки и расчета C2.")
            if remnant.defect:
                constraints.append("У куска отмечен дефект; применение требует осмотра.")
            dims = remnant.dimensions
            matches.append(BuyerMatch(
                buyer_id=buyer["buyer_id"], name=buyer["name"], registry_version=registry_row.id,
                remnant_id=remnant.remnant_id, remnant_version=remnant.version,
                material_id=remnant.material_id, dimensions=dims, application=label,
                activity=application.activity, source_url=application.source_url,
                checked_at=application.checked_at, dimensions_basis=application.dimensions_basis,
                constraints=constraints,
                explanation=f"{material['название']}, {dims.length_mm}×{dims.width_mm} мм: предполагается {label}. "
                            f"Публичная деятельность: {application.activity}. {constraints[0]}",
            ))
            break  # One independently explainable suggestion per organization.
    return matches
