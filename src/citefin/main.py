"""FastAPI application entry point."""

from fastapi import FastAPI

from citefin import __version__
from citefin.api.analysis_runs import router as analysis_runs_router
from citefin.api.documents import router as documents_router
from citefin.api.health import router as health_router


def create_app() -> FastAPI:
    """Build the HTTP application without hidden startup side effects."""

    application = FastAPI(
        title="CiteFin API",
        summary="Evidence-driven financial analysis agent",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(analysis_runs_router, prefix="/api/v1")
    application.include_router(documents_router, prefix="/api/v1")
    return application


app = create_app()
