from contextlib import asynccontextmanager, nullcontext
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from glassflow.contracts.common import ApiError, Health, Readiness
from glassflow.core.crm_port import PlatformCrmPort
from glassflow.core.db import SCHEMA_HEAD, create_database, default_data_dir, session_is_ready
from glassflow.core.errors import install_error_handlers
from glassflow.core.jobs import Coordinator, Handler
from glassflow.core.registry import Services
from glassflow.core.security import install_local_security
from glassflow.core.sources import PlatformIntelligenceSources
from glassflow.core.submission import DurableJobSubmitter
from glassflow.modules.crm.router import router as crm_router
from glassflow.modules.cutting.router import router as cutting_router
from glassflow.modules.cutting.workflow_router import router as workflow_router
from glassflow.modules.insights.router import router as insights_router
from glassflow.modules.intelligence.router import router as intelligence_router
from glassflow.modules.platform.basket_router import router as basket_router
from glassflow.modules.platform.economics_router import router as economics_router
from glassflow.modules.platform.material_use_router import router as material_use_router
from glassflow.modules.platform.order_router import router as order_router
from glassflow.modules.platform.router import router as platform_router
from glassflow.modules.platform.runs import crm_job, schedule_cards
from glassflow.modules.sales.router import router as sales_router


def create_app(
    data_dir: Path | None = None, services: Services | None = None, *, testing: bool = False
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from glassflow.launcher import InstanceLock

        lock = nullcontext() if testing else InstanceLock(data_dir or default_data_dir(), "database.lock")
        with lock:
            from glassflow.modules.platform.system import apply_pending_restore

            apply_pending_restore(data_dir or default_data_dir())
            engine, factory = create_database(data_dir)
            app.state.session_factory = factory
            app.state.engine = engine
            app.state.data_dir = Path(engine.url.database).parent
            from glassflow.core.composition import domain_services, wire_app
            app.state.services = services if services is not None else domain_services()
            app.state.intelligence_sources = PlatformIntelligenceSources(factory)
            app.state.crm_port = PlatformCrmPort(factory, app.state.services)
            app.state.secrets = {}
            wire_app(app)
            app.state.maintenance = False
            handlers = {"crm": Handler(crm_job), **app.state.services.job_handlers}
            app.state.job_submitter = DurableJobSubmitter(factory, handlers)

            def private_network_context(snapshot):
                if snapshot.get("ai_profile") == "local_limited":
                    return {}
                safe = snapshot.get("ai_settings", {})
                key = f"{safe.get('profile')}:{safe.get('provider')}"
                return {"api_key": app.state.secrets.get(key)}

            app.state.coordinator = Coordinator(
                factory,
                handlers,
                tick=lambda: schedule_cards(factory),
                result_hooks=app.state.services.result_hooks,
                private_context={"network": private_network_context},
            )
            try:
                app.state.coordinator.start()
                yield
            finally:
                app.state.coordinator.stop()
                app.state.secrets.clear()
                engine.dispose()

    app = FastAPI(
        title="GlassFlow",
        version="0.1.0",
        lifespan=lifespan,
        responses={status: {"model": ApiError} for status in (400, 403, 404, 409, 413, 422, 429, 500, 503)},
    )
    install_error_handlers(app)
    install_local_security(app, testing=testing)

    @app.get("/api/v1/health", response_model=Health, tags=["platform"])
    def health():
        return Health()

    @app.get("/api/v1/ready", response_model=Readiness, tags=["platform"])
    def ready():
        with app.state.session_factory() as session:
            database = session_is_ready(session)
        from sqlalchemy import text

        with app.state.session_factory() as session:
            schema = (
                session.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == SCHEMA_HEAD
            )
        worker = app.state.coordinator.healthy and app.state.coordinator.thread.is_alive()
        probes = {"crm": lambda: True, **app.state.services.readiness}
        modules = {
            name: name in app.state.coordinator.handlers and name in probes and bool(probes[name]())
            for name in ("cutting", "assistant", "quality", "crm", "cards")
        }
        business = all(modules.values()) and database and schema and worker
        return Readiness(
            status="ready" if business else "degraded",
            database=database,
            schema=schema,
            worker=worker,
            business_modules_ready=business,
            modules=modules,
            ai="unchecked" if app.state.secrets else "unavailable",
        )

    for router in [platform_router, cutting_router, workflow_router, intelligence_router, crm_router, sales_router, order_router, economics_router, basket_router, material_use_router, insights_router]:
        app.include_router(router, prefix="/api/v1")
    from glassflow.core.resources import resource_root

    static_dir = resource_root() / "apps" / "web" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


app = create_app()
