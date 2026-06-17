# main.py
"""
FastAPI application entry point.
Starts scheduler on startup, stops on shutdown.
"""
import logging
import logging.handlers
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import validate_config, STRESS_MODE, STRESS_REALISTIC
from app.handlers.webhook import router as webhook_router
from app.services.calendar import check_calendar_health
from app.services.scheduler import create_scheduler
from app.utils.metrics import get_all as get_metrics


def _setup_logging() -> None:
    """
    Configure root logger.
    - Level: LOG_LEVEL env var (default INFO). Falls back to INFO on invalid value.
    - Handlers: stdout always (journald picks it up under systemd).
                Rotating file if LOG_FILE env var is set (10 MB × 3 backups).
    """
    raw_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, raw_level, None)
    if not isinstance(level, int):
        print(f"[APP] Invalid LOG_LEVEL={raw_level!r}, defaulting to INFO", flush=True)
        level = logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    log_file = os.getenv("LOG_FILE", "")
    if log_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception as e:
            print(f"[APP] Could not open log file {log_file!r}: {e}", flush=True)


_setup_logging()
logger = logging.getLogger(__name__)

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    if STRESS_MODE:
        if STRESS_REALISTIC:
            validate_config()
            check_calendar_health()
            from tests.stress.mocks import apply_realistic
            apply_realistic()
            logger.warning("[APP] STRESS_REALISTIC — Calendar real, writes mock")
        else:
            from tests.stress.mocks import apply_all
            apply_all()
            logger.warning("[APP] STRESS_MODE — todos los externos mockeados")

        from tests.stress.stress_router import router as stress_router
        app.include_router(stress_router)
    else:
        validate_config()
        check_calendar_health()
        _scheduler = create_scheduler()
        _scheduler.start()
    yield
    logger.info("[APP] Shutting down scheduler...")
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Peluquería Citas", lifespan=lifespan)
app.include_router(webhook_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions.
    Logs the full traceback internally but returns a generic message to the client
    so no internal details (paths, stack frames, library versions) are exposed.
    """
    logger.error(
        "[APP] Unhandled exception on %s %s", request.method, request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        {"status": "error", "detail": "Internal server error"},
        status_code=500,
    )


@app.get("/health")
def health():
    if STRESS_MODE:
        return JSONResponse(
            {"status": "ok", "calendar": "stress_mode", "metrics": get_metrics()},
            status_code=200,
        )
    cal_ok = check_calendar_health()
    status = "ok" if cal_ok else "degraded"
    return JSONResponse(
        {
            "status": status,
            "calendar": "ok" if cal_ok else "error",
            "metrics": get_metrics(),
        },
        status_code=200 if cal_ok else 503,
    )


@app.get("/metrics")
def metrics_endpoint():
    """Returns operational counters without touching external APIs."""
    return JSONResponse(get_metrics())
