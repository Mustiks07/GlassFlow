"""Canonical C2/C3 facts in the caller's SQLite snapshot and transaction."""

from contextlib import contextmanager
from dataclasses import replace

from glassflow.contracts.cutting import ReleaseRequest, ReserveRequest
from glassflow.contracts.intelligence import QuoteRequest
from glassflow.contracts.orders import OrderFacts, OrderReservation
from glassflow.core.errors import AppError
from glassflow.core.sources import PlatformIntelligenceSources
from glassflow.core.uow import canonical_hash
from glassflow.modules.cutting.domain import PartSpec
from glassflow.modules.cutting.models import CutRemnant
from glassflow.modules.cutting.service import CuttingError, CuttingService
from glassflow.modules.intelligence.service import IntelligenceError, IntelligenceService


class BoundFactory:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def __call__(self):
        yield self.session

    def begin(self):
        return self()


def intelligence(session):
    factory = BoundFactory(session)
    return IntelligenceService(PlatformIntelligenceSources(factory, session), factory)


def quote_facts(session, dataset_id, quote_id):
    return domain_error(lambda: _quote_facts(session, dataset_id, quote_id))


def _quote_facts(session, dataset_id, quote_id):
    service = intelligence(session)
    catalog = service.catalog_for(dataset_id)
    row = service._rows(session, dataset_id, quote_id)[-1]
    quote = service._view(row, catalog.kb.version)
    request = QuoteRequest.model_validate_json(row.request_json)
    mapping = service.effective_mappings(catalog).get(quote.catalog_product_id)
    mapping_version = canonical_hash({"kb": catalog.kb.version, "mapping": vars(mapping) if mapping else None})
    if quote.stale or (quote.material_id and (mapping is None or mapping.status != "confirmed"
                                            or mapping.material_id != quote.material_id)):
        raise AppError(409, "QUOTE_SOURCE_CHANGED", "Прайс или соответствие материала изменились; нужен пересчет.")
    return quote, request, mapping_version


def domain_error(fn):
    try:
        return fn()
    except (CuttingError, IntelligenceError) as exc:
        raise AppError(exc.status, exc.code, exc.message_ru, conflicts=exc.conflict_objects) from None


class OrderSource:
    def capture(self, session, dataset_id, quote_id, remnant_id, order_id):
        quote, request, mapping_version = quote_facts(session, dataset_id, quote_id)
        service = CuttingService(session)
        remnant = domain_error(lambda: service.get_remnant(dataset_id, remnant_id))
        snapshot = service.load_snapshot(dataset_id)
        row = service._remnant_row(dataset_id, remnant_id)
        reservation = service._active_reservation(row.id)
        owned = reservation is not None and reservation.owner_context.startswith(f"order:{order_id}:")
        piece = replace(snapshot.remnants[remnant_id], status="available") if owned else snapshot.remnants[remnant_id]
        compatible = False
        if request.dimensions and request.quantity and quote.material_id:
            part = PartSpec("__request__", order_id, quote.material_id, request.dimensions.length_mm,
                            request.dimensions.width_mm, request.premium)
            from glassflow.modules.cutting.eligibility import pair_reason
            compatible = pair_reason(snapshot, part, piece) is None and bool(service._positions(
                snapshot, part, piece, [], request.quantity, snapshot.is_tempered(quote.material_id)))
            positions = service._positions(snapshot, part, piece, [], request.quantity,
                                           snapshot.is_tempered(quote.material_id)) if compatible else []
            compatible = compatible and len(positions) == request.quantity
        # Reservation bookkeeping is carried in OrderReservation. Avoid changing
        # any other fact merely because the owning order acquired its own piece.
        remnant.active_reservation_id = None
        return OrderFacts(dataset_id=dataset_id, quote=quote, quote_customer_ref=quote.customer_id,
            remnant=remnant, requested_dimensions=request.dimensions or remnant.dimensions,
            quantity=request.quantity or 1, kb_version=quote.kb_version,
            mapping_version=mapping_version, compatible=compatible, alternative_remnant_ids=[])

    def reserve(self, session, facts, order_id, order_revision):
        change = domain_error(lambda: CuttingService(session).reserve(facts.remnant.remnant_id,
            ReserveRequest(dataset_id=facts.dataset_id, expected_version=facts.remnant.version,
                owner_context=f"order:{order_id}:{order_revision}", material_id=facts.quote.material_id,
                dimensions=facts.requested_dimensions)))
        return OrderReservation(dataset_id=facts.dataset_id, reservation_id=change.reservation.reservation_id,
            order_id=order_id, order_revision=order_revision, remnant_id=facts.remnant.remnant_id,
            remnant_version=change.remnant.version, state="active")

    def reservation(self, session, dataset_id, reservation_id):
        service = CuttingService(session)
        res = domain_error(lambda: service._reservation(dataset_id, reservation_id))
        prefix, order_id, revision = res.owner_context.split(":")
        if prefix != "order":
            raise AppError(409, "RESERVATION_OWNER", "Резерв другого владельца.")
        remnant = session.get(CutRemnant, res.remnant_row_id)
        return OrderReservation(dataset_id=dataset_id, reservation_id=res.id, order_id=order_id,
            order_revision=int(revision), remnant_id=remnant.remnant_id,
            remnant_version=remnant.version, state=res.status)

    def release(self, session, reservation):
        service = CuttingService(session)
        current = self.reservation(session, reservation.dataset_id, reservation.reservation_id)
        if current != reservation:
            raise AppError(409, "RESERVATION_CHANGED", "Резерв изменился.")
        res = service._reservation(reservation.dataset_id, reservation.reservation_id)
        domain_error(lambda: service.release_reservation(res.id, ReleaseRequest(
            dataset_id=reservation.dataset_id, expected_version=res.version, reason="Снятие резерва заказа")))
        return self.reservation(session, reservation.dataset_id, reservation.reservation_id)


class SubjectSource:
    def check(self, session, dataset_id, subject_type, subject_ref, expected_version, **compatibility):
        if subject_type == "quote_example":
            quote, _, _ = quote_facts(session, dataset_id, subject_ref)
            return {"valid": quote.revision == expected_version and quote.status not in {"cancelled", "superseded"},
                    "version": quote.revision}
        facts = OrderSource().capture(session, dataset_id, compatibility["compatibility_ref"], subject_ref, "reminder")
        return {"valid": facts.remnant.status == "available" and facts.remnant.version == expected_version,
                "version": facts.remnant.version, "compatibility_valid": facts.compatible,
                "compatibility_version": facts.quote.revision}
