"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from citefin import __version__
from citefin.api.analysis_runs import router as analysis_runs_router
from citefin.api.checkpoints import router as checkpoints_router
from citefin.api.documents import router as documents_router
from citefin.api.evaluations import router as evaluations_router
from citefin.api.evidence import router as evidence_router
from citefin.api.evidence_viewer import router as evidence_viewer_router
from citefin.api.facts import router as facts_router
from citefin.api.financial_analysis import router as financial_analysis_router
from citefin.api.goal_gate import router as goal_gate_router
from citefin.api.health import router as health_router
from citefin.api.metrics import router as metrics_router
from citefin.api.progress import router as progress_router
from citefin.api.reports import router as reports_router
from citefin.api.risk_detection import router as risk_detection_router
from citefin.api.workbench import router as workbench_router

STATIC_DIR = Path(__file__).with_name("static")


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
    application.include_router(checkpoints_router, prefix="/api/v1")
    application.include_router(documents_router, prefix="/api/v1")
    application.include_router(evidence_router, prefix="/api/v1")
    application.include_router(evidence_viewer_router, prefix="/api/v1")
    application.include_router(evaluations_router, prefix="/api/v1")
    application.include_router(facts_router, prefix="/api/v1")
    application.include_router(financial_analysis_router, prefix="/api/v1")
    application.include_router(goal_gate_router, prefix="/api/v1")
    application.include_router(metrics_router, prefix="/api/v1")
    application.include_router(progress_router, prefix="/api/v1")
    application.include_router(risk_detection_router, prefix="/api/v1")
    application.include_router(reports_router, prefix="/api/v1")
    application.include_router(workbench_router, prefix="/api/v1")
    application.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="frontend-assets",
    )

    @application.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        """Serve the F016 minimal UI without exposing a second API surface."""

        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    return application


app = create_app()
