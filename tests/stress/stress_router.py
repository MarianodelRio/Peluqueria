# tests/stress/stress_router.py
"""
FastAPI router exposing stress test metrics and control endpoints.
Mounted only when STRESS_MODE=1.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tests.stress.timing_store import store
from app.handlers import conversation

router = APIRouter(prefix="/stress")


@router.get("/stats")
def stress_stats():
    """Return timing stats, RSS memory usage, and active conversation state count."""
    stats = store.get_stats()

    rss_mb = None
    try:
        import psutil
        import os
        proc = psutil.Process(os.getpid())
        rss_mb = proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        pass

    stats["rss_mb"] = rss_mb
    stats["states_count"] = len(conversation._states)
    return JSONResponse(stats)


@router.delete("/clear")
def stress_clear():
    """Reset timing counters (does not affect in-flight requests)."""
    store.clear()
    return {"status": "cleared"}
