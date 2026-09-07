"""FastAPI application entry point."""

from fastapi import FastAPI

from citefin import __version__
from citefin.api.analysis_runs import router as analysis_runs_router
from citefin.api.documents import router as documents_router
from citefin.api.evidence import router as evidence_router
from citefin.api.facts import router as facts_router
from citefin.api.financial_analysis import router as financial_analysis_router
from citefin.api.health import router as health_router
from citefin.api.metrics import router as metrics_router
from citefin.api.reports import router as reports_router
from citefin.api.risk_detection import router as risk_detection_router


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
    application.include_router(evidence_router, prefix="/api/v1")
    application.include_router(facts_router, prefix="/api/v1")
    application.include_router(financial_analysis_router, prefix="/api/v1")
    application.include_router(metrics_router, prefix="/api/v1")
    application.include_router(risk_detection_router, prefix="/api/v1")
    application.include_router(reports_router, prefix="/api/v1")
    return application


app = create_app()
