from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


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
