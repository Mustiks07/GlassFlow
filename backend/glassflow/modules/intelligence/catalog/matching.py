"""Free-text → catalog product resolution.

Deterministic, explainable scoring over features derived from the KB product names:
word stems, thickness, colour, product family, codes, sizes and sheet formats. A candidate
is excluded on an explicit conflict (another thickness, colour or family the user named, a
negated family such as «без рифления», another sheet format). The result is ``exact`` only
when one product explains the request without missing distinguishing attributes; otherwise
``ambiguous`` with the tied candidates, so the caller asks a targeted question instead of
guessing (and never picks the cheapest option).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .kb import KnowledgeBase, Product
from .text import normalize, similarity, stem, stems_match

STOPWORDS = {
    "для", "и", "с", "со", "на", "по", "из", "в", "во", "мм", "шт", "или", "а", "от", "до", "за",
}
LOW_WEIGHT = {"лист": 0.3, "стекл": 0.8}
COLOR_FORMS = {
    "прозрачное": ["прозрачное", "прозрачный", "прозрачного", "прозрачная"],
    "серое": ["серое", "серый", "серого", "серая", "серым"],
    "бронза": ["бронза", "бронзовое", "бронзовый", "бронзы"],
}
COLOR_LEXICON = {
    "прозрачное": ["прозрачн"],
    "серое": ["сер"],
    "бронза": ["бронз"],
    "green": ["green"],
    "золото": ["золот"],
    "чёрный/белый": ["черн", "бел"],
}
FAMILY_LEXICON = {
    "tempered": ["кален"],
    "patterned": ["рифлен"],
    "mirror": ["зеркал"],
    "lacobel": ["лакобел"],
    "matelux": ["мателюкс"],
    "checkered": ["квадратик"],
    "reflective": ["отражающ"],
}
_CODE = re.compile(r"\b(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)+\b|\b[a-z]+\d+[a-z0-9]*\b")
_UNIT_CODES = {"m2", "m3", "mm2", "mm3", "cm2", "cm3"}
UNSUPPORTED_IDENTIFIERS = {"unknown_catalog_code", "unknown_catalog_brand", "unknown_hardware_identity"}
_DIMS = re.compile(r"\b\d+(?:x\d+)+\b")
_THICKNESS = re.compile(r"(?<![\dx])(\d{1,2})\s*(?:-?\s*мм|миллиметр\w*|-?ти\s*мм|-?ми\s*мм)\b")
_NEGATION = re.compile(r"\b(?:без|не)\s+([а-яa-z]+)")
_TOKEN = re.compile(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*")


def _matching_text(text: str) -> str:
    value = normalize(text)
    value = re.sub(r"(?<=\d)\s*на\s*(?=\d)", "x", value)
    value = re.sub(r"(\d)\s*-\s*(?:ти|ми|х)\b", r"\1", value)
    value = re.sub(r"(\d)(мм|см)\b", r"\1 \2", value)
    return value


@dataclass(frozen=True)
class Feature:
    kind: str  # word | code | dims | number | thickness | color | family
    value: str
    weight: float


@dataclass
class QueryFeatures:
    text: str
    stems: list[str]
    codes: set[str]
    dims: set[str]
    numbers: set[str]
    thickness: set[int]
    colors: set[str]
    families: set[str]
    negated_families: set[str]
    negated_stems: set[str] = field(default_factory=set)


def _split_token(token: str) -> list[str]:
    if "-" in token and not _CODE.fullmatch(token):
        return [part for part in token.split("-") if part]
    return [token]


def _product_features(product: Product) -> list[Feature]:
    text = _matching_text(product.name)
    aliases = {stem(word) for group in re.findall(r"\(([^)]*)\)", text) for word in _TOKEN.findall(group)}
    features: list[Feature] = []
    consumed: set[str] = set()
    for code in _CODE.findall(text):
        features.append(Feature("code", code, 3.0))
        consumed.update(re.findall(r"[a-z0-9]+", code))
        consumed.add(code)
    for dims in _DIMS.findall(text):
        features.append(Feature("dims", dims, 1.5))
        consumed.update(dims.split("x"))
    if product.kind == "material":
        if product.thickness_mm is not None:
            features.append(Feature("thickness", str(product.thickness_mm), 2.0))
            consumed.add(str(product.thickness_mm))
        for color in product.attributes.get("color", "").split(","):
            if color:
                features.append(Feature("color", color, 2.0))
                consumed.update(COLOR_LEXICON.get(color, []))
        for family in product.attributes.get("families", "").split(","):
            if family:
                features.append(Feature("family", family, 2.0))
                consumed.update(FAMILY_LEXICON.get(family, []))
    seen: set[str] = set()
    for raw in _TOKEN.findall(text):
        if raw in consumed:
            continue
        for token in _split_token(raw):
            if token in consumed or token in STOPWORDS:
                continue
            if token.isdigit():
                if token not in seen:
                    features.append(Feature("number", token, 1.0))
                    seen.add(token)
                continue
            token_stem = stem(token)
            if token_stem in consumed or token_stem in seen or len(token_stem) < 2:
                continue
            seen.add(token_stem)
            kind = "alias" if token_stem in aliases else "word"
            features.append(Feature(kind, token_stem, LOW_WEIGHT.get(token_stem, 1.0)))
    return features


def query_features(text: str) -> QueryFeatures:
    value = _matching_text(text)
    tokens = [part for raw in _TOKEN.findall(value) for part in ([raw] + _split_token(raw) if "-" in raw else [raw])]
    stems = [stem(token) for token in tokens if not token.isdigit()]
    negated_stems = {stem(word) for word in _NEGATION.findall(value)}
    colors = {
        color
        for color, roots in COLOR_LEXICON.items()
        if color != "чёрный/белый" and any(stems_match(root, s) for root in roots for s in stems)
    }
    for color, forms in COLOR_FORMS.items():
        if color not in colors and any(
            len(token) >= 5 and similarity(token, form) >= 0.8 for token in tokens if token.isalpha() for form in forms
        ):
            colors.add(color)
    families = set()
    negated_families = set()
    for family, roots in FAMILY_LEXICON.items():
        hits = [
            s
            for s in stems
            if any(
                s == root or (len(s) >= 5 and (s.startswith(root) or similarity(s, root) >= 0.8)) for root in roots
            )
        ]
        if not hits:
            continue
        if all(hit in negated_stems for hit in hits):
            negated_families.add(family)
        else:
            families.add(family)
    if any(s in {"обычн", "прост", "стандартн", "простое"} for s in stems):
        negated_families |= {"tempered", "patterned", "checkered"} - families
    return QueryFeatures(
        text=value,
        stems=stems,
        codes=set(_CODE.findall(value)) - _UNIT_CODES,
        dims=set(_DIMS.findall(value)),
        numbers={token for token in tokens if token.isdigit()},
        thickness={int(match) for match in _THICKNESS.findall(value)},
        colors=colors,
        families=families,
        negated_families=negated_families,
        negated_stems=negated_stems,
    )


@dataclass
class Candidate:
    product: Product
    score: float
    matched: list[str]
    missing: list[str]
    soft: list[str]
    code_hit: bool = False

    @property
    def blocking_missing(self) -> list[str]:
        return [item for item in self.missing if not item.startswith(("code:", "optional:"))]

    @property
    def complete(self) -> bool:
        return self.code_hit or not self.blocking_missing


@dataclass
class MatchResult:
    status: str  # exact | ambiguous | not_found
    candidates: list[Candidate]
    reason_code: str | None = None

    @property
    def product(self) -> Product | None:
        return self.candidates[0].product if self.status == "exact" else None


def _hit(feature: Feature, query: QueryFeatures) -> bool:
    if feature.kind in {"word", "alias"}:
        return any(stems_match(feature.value, s) for s in query.stems if s not in query.negated_stems)
    if feature.kind == "code":
        return feature.value in query.codes
    if feature.kind == "dims":
        head = feature.value.split("x")[0]
        return feature.value in query.dims or (len(head) >= 4 and head in query.numbers)
    if feature.kind == "number":
        return feature.value in query.numbers
    if feature.kind == "thickness":
        return int(feature.value) in query.thickness
    if feature.kind == "color":
        if feature.value == "чёрный/белый":
            return any(stems_match(s, "черн") or stems_match(s, "бел") for s in query.stems)
        return feature.value in query.colors
    if feature.kind == "family":
        return feature.value in query.families
    return False


def _score(product: Product, features: list[Feature], query: QueryFeatures, kb_formats: set[str]) -> Candidate | None:
    product_families = {f.value for f in features if f.kind == "family"}
    product_colors = {f.value for f in features if f.kind == "color"}
    product_thickness = {int(f.value) for f in features if f.kind == "thickness"}
    product_dims = {f.value for f in features if f.kind == "dims"}
    soft: list[str] = []
    score = 0.0
    if product.kind == "material":
        if query.thickness and product_thickness and not (product_thickness & query.thickness):
            return None
        if query.colors and product_colors and not (product_colors & query.colors):
            return None
        if query.families - product_families:
            return None
        if query.negated_families & product_families:
            return None
        if query.thickness and not product_thickness:
            soft.append("thickness_not_in_catalog")
            score -= 0.5
        if query.colors and not product_colors:
            soft.append("color_not_in_catalog")
            score -= 0.25
    if (kb_formats - product_dims) & query.dims:
        return None
    for feature in features:
        if feature.kind == "code" and feature.value not in query.codes:
            prefix = feature.value.split("-")[0]
            if any(code != feature.value and code.split("-")[0] == prefix for code in query.codes):
                return None
    hits = {id(feature): _hit(feature, query) for feature in features}
    alias_hit = any(hits[id(f)] for f in features if f.kind == "alias")
    matched: list[str] = []
    missing: list[str] = []
    for feature in features:
        label = f"{feature.kind}:{feature.value}"
        if hits[id(feature)]:
            matched.append(label)
            score += feature.weight
            continue
        optional = (
            feature.kind == "alias"
            or (alias_hit and feature.kind == "word")
            or (feature.kind == "word" and feature.weight < 1.0)
        )
        if feature.kind == "code":
            missing.append(label)
            score -= 0.25
        elif optional:
            missing.append(f"optional:{label}")
            score -= 0.1
        else:
            missing.append(label)
            score -= 0.6 * feature.weight
    weights = {f"{f.kind}:{f.value}": f.weight for f in features}
    head_kinds = {"word", "alias", "code", "dims", "color", "family"}
    if not any(label.split(":")[0] in head_kinds for label in matched):
        return None
    meaningful = sum(weights[label] for label in matched if not label.startswith("number:"))
    if meaningful < 1.0:
        return None
    if product.kind != "material" and query.families:
        family_roots = {root for roots in FAMILY_LEXICON.values() for root in roots} | {"стекл"}
        own_words = [
            label for label in matched
            if label.split(":")[0] in {"word", "alias", "code", "dims"} and label.split(":", 1)[1] not in family_roots
        ]
        if not own_words:
            return None
    if normalize(product.name) in query.text and not soft:
        score += 3.0
    code_hit = any(label.startswith("code:") for label in matched)
    return Candidate(product, score, matched, missing, soft, code_hit)


def match_products(kb: KnowledgeBase, text: str, *, kinds: set[str] | None = None, limit: int = 6) -> MatchResult:
    query = query_features(text)
    catalogue_text = " ".join(_matching_text(product.name) for product in kb.products)
    brands = re.findall(r"\b(?:бренд\w*|марк[аи]|производител[ья])\s*[:—-]?\s*[«\"]?([a-zа-я][a-zа-я0-9-]*)", query.text)
    if any(not re.search(rf"\b{re.escape(brand)}\b", catalogue_text) for brand in brands):
        return MatchResult("not_found", [], "unknown_catalog_brand")
    coded_products = {
        product.product_id for product in kb.products
        if query.codes <= (set(_CODE.findall(_matching_text(product.name))) | {normalize(product.product_id)})
    }
    if query.codes and not coded_products:
        return MatchResult("not_found", [], "unknown_catalog_code")
    formats = {product.attributes["sheet_format_mm"] for product in kb.products if "sheet_format_mm" in product.attributes}
    candidates: list[Candidate] = []
    for product in kb.products:
        if query.codes and product.product_id not in coded_products:
            continue
        if kinds and product.kind not in kinds:
            continue
        candidate = _score(product, _product_features(product), query, formats)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return MatchResult("not_found", [])
    if any(c.code_hit for c in candidates):
        candidates = [c for c in candidates if c.code_hit]
    candidates.sort(key=lambda c: (-c.score, c.product.position))
    if candidates[0].product.is_hardware:
        catalogue_latin = set(re.findall(r"[a-z]+", catalogue_text))
        unknown_latin = set(re.findall(r"\b[a-z]{2,}\b", query.text)) - catalogue_latin - {"mm", "cm", "kzt", "pcs", "sku", "id"}
        uncertain = re.search(r"\bнеизвестн\w*", query.text)
        if unknown_latin or (uncertain and not candidates[0].complete):
            return MatchResult("not_found", [], "unknown_hardware_identity")
    complete = [c for c in candidates if c.complete]
    if complete:
        best = complete[0]
        tied = [c for c in complete if abs(c.score - best.score) < 1e-9]
        if len(tied) == 1:
            return MatchResult("exact", [best] + [c for c in candidates if c is not best][: limit - 1])
        return MatchResult("ambiguous", tied[:limit])
    best = candidates[0]
    distinguishing_hit = len(candidates) > 1 and any(
        not label.startswith("number:") and all(label not in other.matched for other in candidates[1:])
        for label in best.matched
    )
    if best.product.is_hardware and not distinguishing_hit:
        return MatchResult("ambiguous", candidates[:limit], "hardware_identity_incomplete")
    # A shorter catalogue name scores higher, but does not identify a SKU.
    mentioned = {value for value in best.matched if not value.startswith("number:")}
    indistinguishable = [candidate for candidate in candidates
                         if {value for value in candidate.matched if not value.startswith("number:")} == mentioned]
    if len(indistinguishable) > 1:
        return MatchResult("ambiguous", indistinguishable[:limit])
    tied = [c for c in candidates if best.score - c.score < 0.5]
    if len(tied) == 1 and (best.score >= 0.5 or len(candidates) == 1 or best.score - candidates[1].score >= 1.0):
        return MatchResult("exact", [best] + candidates[1:limit])
    if len(tied) == 1:
        tied = [c for c in candidates if best.score - c.score < 1.5]
    return MatchResult("ambiguous", tied[:limit])
