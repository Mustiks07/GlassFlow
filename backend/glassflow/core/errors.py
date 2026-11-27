from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException


class FeatureUnavailable(Exception):
    def __init__(self, feature: str):
        self.feature = feature


async def feature_unavailable_handler(request: Request, exc: FeatureUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "code": "FEATURE_NOT_IMPLEMENTED",
            "message_ru": f"Модуль {exc.feature} еще не реализован в каркасе проекта.",
            "field_errors": [],
            "conflict_objects": [],
            "retryable": False,
            "correlation_id": str(uuid4()),
        },
    )


class AppError(Exception):
    def __init__(self, status, code, message, *, fields=None, conflicts=None, retryable=False):
        self.status, self.code, self.message = status, code, message
        self.fields, self.conflicts = fields or [], conflicts or []
        self.retryable = retryable


def error_response(request, status, code, message, fields=None, conflicts=None, retryable=False):
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message_ru": message,
            "field_errors": fields or [],
            "conflict_objects": conflicts or [],
            "retryable": retryable,
            "correlation_id": getattr(request.state, "correlation_id", str(uuid4())),
        },
    )


def install_error_handlers(app):
    app.add_exception_handler(FeatureUnavailable, feature_unavailable_handler)

    @app.exception_handler(AppError)
    async def application_error(request, exc):
        return error_response(
            request, exc.status, exc.code, exc.message, exc.fields, exc.conflicts, exc.retryable
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in exc.errors()]
        return error_response(request, 422, "VALIDATION_ERROR", "Проверьте поля запроса.", fields)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, f"HTTP_{exc.status_code}", "Запрос не выполнен.")

    @app.exception_handler(OperationalError)
    async def database_error(request, exc):
        return error_response(
            request, 503, "DATABASE_UNAVAILABLE", "База временно недоступна.", retryable=True
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error_response(request, 500, "INTERNAL_ERROR", "Внутренняя ошибка. Сохраните код обращения.")
