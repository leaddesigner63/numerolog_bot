from fastapi import APIRouter

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
