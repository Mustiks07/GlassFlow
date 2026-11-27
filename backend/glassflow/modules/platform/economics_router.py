import tempfile
from pathlib import Path

from fastapi import APIRouter, Header, Query, Request, Response

from glassflow.contracts.economics import EconomicsCreate, EconomicsScenario, EconomicsUpdate
from glassflow.core.errors import AppError
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform import economics_service as service
from glassflow.modules.platform.reports import build_economics

router = APIRouter(prefix="/economics/scenarios", tags=["economics"])


@router.post("", response_model=EconomicsScenario)
def create(body: EconomicsCreate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, "economics.create", idempotency_key,
                          body.model_dump(mode="json"),
                          lambda: service.calculate(session, body, request.state.correlation_id))


@router.put("/{scenario_id}", response_model=EconomicsScenario)
def update(scenario_id: str, body: EconomicsUpdate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"economics.update:{scenario_id}", idempotency_key,
                          body.model_dump(mode="json"),
                          lambda: service.calculate(session, body, request.state.correlation_id, scenario_id))


@router.get("/{scenario_id}", response_model=EconomicsScenario)
def get(scenario_id: str, dataset_id: str, request: Request, version: int | None = Query(None, ge=0)):
    with request.app.state.session_factory() as session:
        return service.load(session, dataset_id, scenario_id, version)


@router.get("/{scenario_id}/pdf", response_class=Response)
def pdf(scenario_id: str, dataset_id: str, request: Request, version: int = Query(..., ge=0)):
    with request.app.state.session_factory() as session:
        scenario = service.load(session, dataset_id, scenario_id, version)
    evidence = service.pdf_evidence(scenario)
    font = next((p for p in (Path("C:/Windows/Fonts/arial.ttf"),
                             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")) if p.is_file()), None)
    if font is None:
        raise AppError(503, "REPORT_FONT_MISSING", "Нет шрифта с поддержкой кириллицы.")
    with tempfile.TemporaryDirectory(prefix="glassflow-scenario-") as directory:
        destination = Path(directory) / "scenario.pdf"
        try:
            result = build_economics(evidence, destination, font, preview=True, scenario_preview=True)
        except ValueError:
            raise AppError(422, "REPORT_LAYOUT_TOO_LARGE", "Сократите текстовые основания, чтобы сохранить читаемую страницу.") from None
        if result != scenario.results.model_dump():
            raise AppError(409, "SCENARIO_RESULT_MISMATCH", "PDF и сохраненный расчет не совпали.")
        content = destination.read_bytes()
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="scenario-v{version}.pdf"',
        "X-GlassFlow-Input-Hash": scenario.input_hash, "X-GlassFlow-Result-Hash": scenario.result_hash,
    })
