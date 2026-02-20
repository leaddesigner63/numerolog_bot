from fastapi import FastAPI

from app.api.middleware import ProbeGuardMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.worker_health import router as worker_health_router
from app.api.routes.admin import router as admin_router
from app.api.routes.webhooks import router as webhook_router
from app.api.routes.public import router as public_router
from app.core.config import settings
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    application = FastAPI(title="Numerolog Bot API")
    application.add_middleware(ProbeGuardMiddleware)
    application.include_router(health_router)
    application.include_router(worker_health_router)
    application.include_router(admin_router)
    application.include_router(webhook_router)
    application.include_router(public_router)
    return application


app = create_app()
