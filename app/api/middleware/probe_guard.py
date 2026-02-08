from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class ProbeGuardMiddleware(BaseHTTPMiddleware):
    """Блокирует типовые сканирующие запросы к чужим CMS/секретам."""

    _BLOCKED_PATH_MARKERS = (
        "/wordpress",
        "wp-admin",
        "wp-login.php",
        "setup-config.php",
        "/xmlrpc.php",
        "/.env",
        "/phpmyadmin",
    )

    async def dispatch(self, request: Request, call_next):
        request_path = request.url.path.lower()
        if any(marker in request_path for marker in self._BLOCKED_PATH_MARKERS):
            return JSONResponse(status_code=410, content={"detail": "Resource not available"})
        return await call_next(request)
