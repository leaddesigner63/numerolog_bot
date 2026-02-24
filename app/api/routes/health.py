from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "numerolog_bot"}


@router.get("/api")
async def api_root() -> dict[str, str]:
    return {"status": "ok", "service": "numerolog_bot"}


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": f"database_unavailable: {exc.__class__.__name__}",
            },
        )
