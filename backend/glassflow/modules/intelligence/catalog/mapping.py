"""Explicit CatalogProduct → Material mappings.

Only one automatic rule produces ``confirmed``: the normalized catalog name is *identical* to
the materials.csv name and the thickness agrees. A catalog name that is a material name plus a
sheet format is only ``proposed`` and needs a manager confirmation. Everything else is
``unmapped`` or ``ambiguous`` with the candidate list shown — never a silent substitution by a
similar name (e.g. patterned clear 8 mm is not clear-8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .kb import KnowledgeBase, Product
from .materials import MaterialRecord, MaterialsTable
from .text import normalize, stem, words

RULE_VERSION = "mapping-rules-v1"


@dataclass(frozen=True)
class MappingDecision:
    catalog_product_id: str
    material_id: str | None
    status: str  # confirmed | proposed | ambiguous | unmapped
    basis: str
    candidate_material_ids: tuple[str, ...]
    confirmed_by: str | None
    version: int
    message_ru: str | None = None


def _key(text: str) -> str:
    return re.sub(r"[^a-zа-я0-9x]+", " ", normalize(text)).strip()


def _stems(text: str) -> set[str]:
    return {stem(word) for word in words(text) if not word.isdigit() and word != "мм"}


def derive_mapping(product: Product, materials: MaterialsTable) -> MappingDecision:
    if product.is_hardware or product.kind != "material":
        return MappingDecision(
            product.product_id, None, "unmapped", "not_applicable_non_sheet_product", (), None, 0
        )
    name_key = _key(product.name)
    exact = [record for record in materials.records if _key(record.name) == name_key]
    if len(exact) == 1 and (product.thickness_mm in (None, exact[0].thickness_mm)):
        return MappingDecision(
            product.product_id,
            exact[0].material_id,
            "confirmed",
            f"{RULE_VERSION}:exact_normalized_name",
            (exact[0].material_id,),
            f"rule:{RULE_VERSION}",
            0,
        )
    if len(exact) > 1:
        ids = tuple(record.material_id for record in exact)
        return MappingDecision(
            product.product_id, None, "ambiguous", "several_materials_with_identical_name", ids, None, 0,
            "Несколько складских материалов с одинаковым названием; нужен выбор менеджера.",
        )
    # Catalog sheet format of a material ("Зеркало 4 мм, лист 2750 × 1605" vs "Зеркало 4 мм").
    prefixed = [
        record
        for record in materials.records
        if name_key.startswith(_key(record.name) + " лист")
        and record.thickness_mm == product.thickness_mm
        and not record.tempered
    ]
    if len(prefixed) == 1:
        return MappingDecision(
            product.product_id,
            None,
            "proposed",
            f"{RULE_VERSION}:catalog_sheet_format_of_material",
            (prefixed[0].material_id,),
            None,
            0,
            f"Позиция — формат листа материала {prefixed[0].material_id}; соответствие подтверждает менеджер.",
        )
    # Name without thickness whose words are contained in thicker materials: clarification only.
    if product.thickness_mm is None:
        product_stems = _stems(product.name)
        tempered_product = "tempered" in product.attributes.get("families", "")
        contained = [
            record
            for record in materials.records
            if product_stems and product_stems <= _stems(record.name) and record.tempered == tempered_product
        ]
        if contained:
            ids = tuple(record.material_id for record in contained)
            return MappingDecision(
                product.product_id, None, "ambiguous", "catalog_thickness_not_specified", ids, None, 0,
                "В позиции каталога не указана толщина; складское соответствие нужно уточнить.",
            )
    return MappingDecision(
        product.product_id, None, "unmapped", "no_material_with_identical_name", (), None, 0,
        "Для позиции нет подтвержденного складского материала.",
    )


def material_valuation_note(record: MaterialRecord) -> str:
    return (
        f"Ставка materials.csv для {record.material_id} = {record.valuation_rate_per_m2} ₸/м² — "
        "оценка складского материала, не цена клиентской позиции каталога."
    )


def derive_all(kb: KnowledgeBase, materials: MaterialsTable) -> dict[str, MappingDecision]:
    return {product.product_id: derive_mapping(product, materials) for product in kb.products}
