"""Public, immutable synthetic demo endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from citefin.services.demo import DEMO_SOURCE_ID, get_demo_pdf, get_demo_workspace

router = APIRouter(prefix="/demo", tags=["public-demo"])


@router.get("/workspace", response_model=dict[str, Any])
def demo_workspace() -> dict[str, Any]:
    """Return the versioned synthetic demo without database reads or writes."""

    return get_demo_workspace()


@router.get("/evidence/{source_id}/content", response_class=Response)
def demo_evidence(source_id: str) -> Response:
    """Return only the allowlisted synthetic evidence document."""

    if source_id != DEMO_SOURCE_ID:
        raise HTTPException(
            status_code=404,
            detail={"code": "demo_source_not_found", "message": "Demo source was not found."},
        )
    return Response(
        get_demo_pdf(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="citefin-g001-synthetic.pdf"',
            "Cache-Control": "public, max-age=3600, immutable",
        },
    )
