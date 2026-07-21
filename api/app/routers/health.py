"""GET /api/health — liveness check. Real from day one (no data needed)."""

from fastapi import APIRouter

from app.models import Health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version="0.1.0")
