"""Production composition of all domains. Explicit Services remain available to isolated tests."""

from glassflow.core.domain_jobs import (
    assistant_job,
    cards_job,
    cutting_job,
    quality_job,
    store_cards,
    store_cutting,
    validate_cutting,
)
from glassflow.core.jobs import Handler
from glassflow.core.registry import Services


def import_cutting(session, dataset_id, parsed):
    from glassflow.core.snapshots import cutting_snapshot
    from glassflow.modules.cutting.conversion import snapshot_from_input
    from glassflow.modules.cutting.service import CuttingService
    from glassflow.modules.platform.imports import dataset

    row = dataset(session, dataset_id)
    inputs = {kind: [r["data"] for r in parsed[kind]] for kind in ("materials", "stock", "orders")}
    snapshot = snapshot_from_input(cutting_snapshot(dataset_id, inputs, {}))
    CuttingService(session).register_dataset(dataset_id, row.mode, snapshot,
        parent_dataset_id=row.parent_id, source_hash=row.fingerprint)


class SalesSource:
    def get_plan(self, session, dataset_id, plan_id):
        from glassflow.modules.cutting.service import CuttingService
        service = CuttingService(session)
        plan = service.get_plan(dataset_id, plan_id)
        plan.free_original_remnant_ids = [r.remnant_id for r in service.free_remnants(dataset_id, plan_id).free_original]
        return plan

    def validate_plan(self, session, dataset_id, plan):
        from glassflow.modules.cutting.service import CuttingService
        return CuttingService(session).validate(dataset_id, plan.plan_id, plan.revision)

    def get_remnant(self, session, dataset_id, remnant_id):
        from glassflow.modules.cutting.service import CuttingService
        return CuttingService(session).get_remnant(dataset_id, remnant_id)


def domain_services():
    from glassflow.core.domain_sources import OrderSource, SubjectSource
    from glassflow.modules.cutting.workflows import (
        BasketSource,
        MaterialSource,
        solve_selection,
        store_selection,
        validate_selection,
    )
    from glassflow.modules.intelligence.baskets import parse_basket
    return Services(import_hooks=[import_cutting], sales_source=SalesSource(),
        order_source=OrderSource(), subjects=SubjectSource(),
        basket_source=BasketSource(), material_use=MaterialSource(),
        job_handlers={"cutting": Handler(cutting_job, validate=validate_cutting),
                      "assistant": Handler(assistant_job, lane="network"),
                      "quality": Handler(quality_job), "cards": Handler(cards_job),
                      "basket.parse": Handler(parse_basket, lane="network"),
                      "basket.selection": Handler(solve_selection, validate=validate_selection)},
        result_hooks={"cutting": store_cutting, "cards": store_cards, "basket.selection": store_selection},
        readiness={name: lambda: True for name in ("cutting", "assistant", "quality", "cards")})


def wire_app(app):
    from glassflow.core.domain_runtime import runtime_for
    from glassflow.modules.cutting.engine import CuttingPortAdapter
    from glassflow.modules.intelligence.service import DbLedger, IntelligenceService
    from glassflow.modules.platform.system import get_settings

    factory = app.state.session_factory
    app.state.intelligence_service = IntelligenceService(app.state.intelligence_sources, factory,
        inventory=CuttingPortAdapter(factory), crm=app.state.crm_port)

    composed_service = app.state.intelligence_service

    def refresh_runtime():
        if app.state.intelligence_service is not composed_service:
            return app.state.intelligence_service
        with factory() as session:
            settings = get_settings(session, app.state.secrets)
        key = app.state.secrets.get(f"{settings.profile}:{settings.provider}")
        signature = (settings.model_dump_json(), key)
        service = app.state.intelligence_service
        if getattr(service, "_settings_signature", None) != signature:
            service.runtime = runtime_for(settings, key, DbLedger(factory))
            service._settings_signature = signature
        return service

    app.state.refresh_intelligence = refresh_runtime
    refresh_runtime()

    async def check_ai(settings, secret):
        from glassflow.contracts.intelligence import AICheckRequest
        service = refresh_runtime()
        result = await service.check_ai(AICheckRequest(live=settings.profile != "local_limited"))
        from glassflow.core.models import now
        return {"available": result.status == "available", "provider": settings.provider,
                "model_id": settings.model_id, "capabilities": result.capabilities, "checked_at": now()}

    app.state.services.ai_check = check_ai
