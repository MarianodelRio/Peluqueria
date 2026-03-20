# main.py
"""
FastAPI application entry point.
Starts scheduler on startup, stops on shutdown.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.handlers.webhook import router as webhook_router
from app.services.scheduler import create_scheduler
from app.services.calendar import check_calendar_health

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    logger.info("[APP] Starting scheduler...")
    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("[APP] Scheduler started. App ready.")
    yield
    logger.info("[APP] Shutting down scheduler...")
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Peluquería Citas", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health():
    cal_ok = check_calendar_health()
    status = "ok" if cal_ok else "degraded"
    return JSONResponse(
        {"status": status, "calendar": "ok" if cal_ok else "error"},
        status_code=200 if cal_ok else 503,
    )
