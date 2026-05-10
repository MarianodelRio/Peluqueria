# utils/admin.py
"""
Admin utilities — system status report for the /estado command.
These strings are admin-only and not client-facing, so they live here
rather than in messages.py.
"""
import logging
import time
from datetime import datetime

import pytz

from app.config import TIMEZONE
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
                f"  RAM: {mem.percent:.1f}% ({mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB)",
                f"  Disco: {disk.percent:.1f}% ({disk.used // (1024**3):.1f} GB / {disk.total // (1024**3):.1f} GB)",
                f"  Uptime: {uptime_h}h {uptime_m}m",
            ]
        except Exception as ps_err:
            logger.error("[ADMIN] psutil error: %s", ps_err)
            sistema_lines = [f"  Sistema: error al leer metricas ({ps_err})"]

        # --- Calendar health ---
        try:
            cal_ok = check_calendar_health()
            cal_line = "  Calendar: OK" if cal_ok else "  Calendar: ERROR - no se pudo conectar"
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
