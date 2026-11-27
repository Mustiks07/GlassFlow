from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from glassflow.contracts.common import Health, Readiness
from glassflow.core.db import create_database, session_is_ready
from glassflow.core.errors import install_error_handlers
from glassflow.core.registry import Services
from glassflow.core.security import install_local_security
from glassflow.modules.crm.router import router as crm_router
from glassflow.modules.cutting.router import router as cutting_router
from glassflow.modules.intelligence.router import router as intelligence_router
from glassflow.modules.platform.router import router as platform_router
from glassflow.modules.sales.router import router as sales_router


def create_app(data_dir: Path | None = None, services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, factory = create_database(data_dir)
        app.state.session_factory = factory
        app.state.engine = engine
        app.state.data_dir = Path(engine.url.database).parent
        app.state.services = services or Services()
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="GlassFlow", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    install_local_security(app, testing=data_dir is not None)

    @app.get("/api/v1/health", response_model=Health, tags=["platform"])
    def health():
        return Health()

    @app.get("/api/v1/ready", response_model=Readiness, tags=["platform"])
    def ready():
        with app.state.session_factory() as session:
            database = session_is_ready(session)
        return Readiness(status="foundation", database=database, business_modules_ready=False)

    for router in [platform_router, cutting_router, intelligence_router, crm_router, sales_router]:
        app.include_router(router, prefix="/api/v1")
    static_dir = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


app = create_app()
