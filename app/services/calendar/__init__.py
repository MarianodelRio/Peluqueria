# services/calendar/__init__.py
"""
Public API for the calendar package.
All existing import paths resolve to the same objects — no breaking changes.
"""

# ── Public API ────────────────────────────────────────────────────────────────
from .service import (  # noqa: F401
    get_slots_disponibles,
    get_slots_disponibles_range,
    get_slots_disponibles_evento,
    get_slots_disponibles_evento_range,
    get_slots_disponibles_for_days,
    reservar_cita,
    mover_cita,
    slot_sigue_libre,
)
from .mutations import (  # noqa: F401
    crear_cita,
    cancelar_cita,
    confirmar_cita,
    marcar_manual_confirmado,
    marcar_recordatorio_enviado,
)
from .queries import (  # noqa: F401
    get_eventos_manuales_sin_confirmar,
    get_citas_para_recordatorio,
    get_citas_futuras,
    get_event_by_id,
)
from .client import client, check_calendar_health  # noqa: F401
from .engine import compute_slots as _compute_slots  # noqa: F401
from .engine import slot_cache_key  # noqa: F401
from .repository import events_repo  # noqa: F401
from .caches import (  # noqa: F401
    slot_cache as _slot_cache_obj,
    citas_cache as _citas_cache_obj,
)

# ── Legacy private names — keep existing tests passing without modification ───
# _thread_local: tests do `del cal._thread_local.service` to force service rebuild
_thread_local = client._thread_local

# _slot_cache / _citas_cache: tests do .clear(), direct key assignment, and lock
# acquisition on these objects. raw_data returns the actual internal dict so all
# mutations go directly to the same dict the TTLCache reads from.
_slot_cache = _slot_cache_obj.raw_data
_slot_cache_lock = _slot_cache_obj._lock

_citas_cache = _citas_cache_obj.raw_data
_citas_cache_lock = _citas_cache_obj._lock


def _invalidate_slot_cache(d):
    """Legacy function — delegates to TTLCache.invalidate_matching."""
    date_str = d.isoformat()
    _slot_cache_obj.invalidate_matching(
        lambda k: k.startswith(date_str) or k.startswith(f"evt_{date_str}")
    )


_invalidate_citas_cache = _citas_cache_obj.invalidate
_get_service = client.get_service


def _get_events_in_range(service, start, end):
    """Legacy shim — delegates to events_repo.list_for_range."""
    return events_repo.list_for_range(start, end, service=service)


def _slot_cache_key(d, duracion_min=30, presencia_cliente_min=30):
    """Legacy shim — returns a 'normal' mode cache key (no evt_ prefix)."""
    return slot_cache_key(d, 'normal', duracion_min, presencia_cliente_min)
