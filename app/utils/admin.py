# utils/admin.py
"""
Admin utilities — system status report and other admin commands.
These strings are admin-only and not client-facing, so they live here
rather than in messages.py.
"""
import logging
import os
import threading
import time
from datetime import datetime

import pytz

from app.config import TIMEZONE, LOG_FILE
from app.utils import metrics
from app.services.calendar import check_calendar_health

logger = logging.getLogger(__name__)


def build_status_report() -> str:
    """
    Build a real-time system status report string.
    Never raises — all failures are caught and reflected as error markers
    inside the returned string.
    """
    try:
        # --- System metrics (psutil) ---
        sistema_lines = []
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            uptime_sec = int(time.time() - psutil.boot_time())
            uptime_h = uptime_sec // 3600
            uptime_m = (uptime_sec % 3600) // 60

            sistema_lines = [
                f"  CPU: {cpu:.1f}%",
                (
                    f"  RAM: {mem.percent:.1f}%"
                    f" ({mem.used // (1024**2)} MB"
                    f" / {mem.total // (1024**2)} MB)"
                ),
                (
                    f"  Disco: {disk.percent:.1f}%"
                    f" ({disk.used // (1024**3):.1f} GB"
                    f" / {disk.total // (1024**3):.1f} GB)"
                ),
                f"  Uptime: {uptime_h}h {uptime_m}m",
            ]
        except Exception as ps_err:
            logger.error("[ADMIN] psutil error: %s", ps_err)
            sistema_lines = [f"  Sistema: error al leer metricas ({ps_err})"]

        # --- Calendar health ---
        try:
            cal_ok = check_calendar_health()
            if cal_ok:
                cal_line = "  Calendar: OK"
            else:
                cal_line = "  Calendar: ERROR - no se pudo conectar"
        except Exception as cal_err:
            logger.error("[ADMIN] Calendar health error: %s", cal_err)
            cal_line = f"  Calendar: ERROR - {cal_err}"

        # --- Bot metrics ---
        all_metrics = metrics.get_all()
        uptime_bot_sec = all_metrics.pop("uptime_seconds", 0)
        uptime_bot_h = uptime_bot_sec // 3600
        uptime_bot_m = (uptime_bot_sec % 3600) // 60

        metrics_lines = [f"  Bot uptime: {uptime_bot_h}h {uptime_bot_m}m"]
        for k, v in sorted(all_metrics.items()):
            metrics_lines.append(f"  {k}: {v}")

        # --- Timestamp ---
        now_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%d/%m/%Y %H:%M:%S")

        lines = [
            "*Estado del sistema*",
            "",
            "*Sistema*",
        ] + sistema_lines + [
            "",
            "*Servicios externos*",
            cal_line,
            "",
            "*Metricas del bot*",
        ] + metrics_lines + [
            "",
            f"_Generado: {now_str}_",
        ]

        return "\n".join(lines)

    except Exception as err:
        logger.error("[ADMIN] Unexpected error building status report: %s", err)
        return f"[ADMIN] Error generando informe de estado: {err}"


def build_help_message() -> str:
    """
    Return a static Spanish-language help string listing all admin commands.
    No external calls.
    """
    return (
        "*Comandos de administración*\n"
        "\n"
        "/status — Estado del sistema (CPU, RAM, Calendar, métricas del bot)\n"
        "/help — Muestra este mensaje de ayuda\n"
        "/logs — Últimas líneas del fichero de log\n"
        "/restart — Reinicia el proceso del bot\n"
    )


def read_log_tail(n_lines: int = 30) -> str:
    """
    Return the last n_lines lines of LOG_FILE as a string.

    Returns an error string (never raises) when:
    - LOG_FILE is empty (not configured)
    - the file does not exist
    - any OS or other error occurs

    The result is truncated to 4000 characters from the end; when truncation
    occurs the string is prefixed with "[...truncado]\\n".
    """
    try:
        if not LOG_FILE:
            return "[ADMIN] LOG_FILE no está configurado."
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        tail = "".join(lines[-n_lines:])
        if len(tail) > 4000:
            tail = "[...truncado]\n" + tail[-4000:]
        return tail if tail else "[ADMIN] El fichero de log está vacío."
    except FileNotFoundError:
        return f"[ADMIN] Fichero de log no encontrado: {LOG_FILE}"
    except OSError as exc:
        logger.error("[ADMIN] Error leyendo log: %s", exc)
        return f"[ADMIN] Error al leer el log: {exc}"
    except Exception as exc:
        logger.error("[ADMIN] Unexpected error reading log: %s", exc)
        return f"[ADMIN] Error inesperado al leer el log: {exc}"


def schedule_restart(delay_sec: float = 2.0) -> None:
    """
    Schedule a process exit after delay_sec seconds.
    Uses a daemon thread so it does not block shutdown.
    """
    t = threading.Timer(delay_sec, os._exit, args=(0,))
    t.daemon = True
    t.start()
