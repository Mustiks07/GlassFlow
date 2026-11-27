import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from glassflow.core.errors import error_response


def install_local_security(app, *, testing=False):
    token = secrets.token_urlsafe(32)
    app.state.local_token = token

    @app.middleware("http")
    async def local_boundary(request, call_next):
        request.state.correlation_id = str(uuid4())
        host = request.url.hostname
        allowed = {"127.0.0.1", "localhost", "::1"} | ({"testserver"} if testing else set())
        if host not in allowed:
            return error_response(request, 403, "HOST_FORBIDDEN", "Допустим только локальный адрес.")
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            expected = f"{request.url.scheme}://{request.url.netloc}"
            dev = {"http://127.0.0.1:5173", "http://localhost:5173"}
            if origin != expected and origin not in dev:
                return error_response(request, 403, "ORIGIN_FORBIDDEN", "Источник запроса не разрешен.")
            if parsed.scheme not in {"http", "https"}:
                return error_response(request, 403, "ORIGIN_FORBIDDEN", "Источник запроса не разрешен.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if getattr(app.state, "maintenance", False) and request.url.path != "/api/v1/system/shutdown":
                return error_response(request, 503, "RESTORE_PENDING", "Восстановление ожидает перезапуска приложения.")
            presented = request.headers.get("x-glassflow-session") or request.cookies.get(
                "glassflow_session", ""
            )
            if not secrets.compare_digest(presented, token):
                return error_response(
                    request, 403, "LOCAL_SESSION_REQUIRED", "Откройте приложение для начала сессии."
                )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.method == "GET" and request.headers.get("sec-fetch-site") != "cross-site":
            response.set_cookie("glassflow_session", token, httponly=True, samesite="strict")
        return response


def require_owner(request):
    if not secrets.compare_digest(
        request.headers.get("x-glassflow-session", ""), request.app.state.local_token
    ):
        from glassflow.core.errors import AppError

        raise AppError(403, "OWNER_TOKEN_REQUIRED", "Нужно подтверждение локального владельца.")
