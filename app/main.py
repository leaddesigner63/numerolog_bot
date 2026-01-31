from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.webhooks import router as webhook_router
from app.core.config import settings
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    application = FastAPI(title="Numerolog Bot API")
    application.include_router(health_router)
    application.include_router(webhook_router)
    return application


app = create_app()
