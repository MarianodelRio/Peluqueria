# tests/stress/mocks.py
"""
Monkey-patch mocks for stress testing.
Replaces all external API calls (WhatsApp, Google Calendar) with fast stubs
that simulate realistic latency and record timing data.

Call apply_all() once during stress-mode startup (from main.py lifespan).
"""
import time
from random import uniform

from tests.stress.timing_store import store
import app.services.whatsapp as _wa
import app.services.calendar as _cal


def apply_all() -> None:
    """Patch all external-facing service functions with stress-test stubs."""

    # ── WhatsApp stubs ────────────────────────────────────────────────────────

    def _send_text_message(to: str, text: str, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    def _send_interactive(to: str, payload: dict, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    def _send_template(to: str, *args, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    setattr(_wa, "send_text_message", _send_text_message)
    setattr(_wa, "send_interactive", _send_interactive)
    setattr(_wa, "send_template", _send_template)

    # ── Calendar stubs ────────────────────────────────────────────────────────

    def _get_slots_disponibles_for_days(days, **kwargs) -> dict:
        time.sleep(uniform(0.3, 0.6))
        return {d: ["10:00", "10:30", "11:00", "11:30"] for d in days}

    def _get_citas_futuras(phone: str, **kwargs) -> list:
        time.sleep(uniform(0.2, 0.4))
        return []

    def _mock_reservar_cita(*args, **kwargs):
        time.sleep(uniform(0.2, 0.4))
        return ("stress_fake_event_id", None)

    def _mock_get_slots_disponibles(d, **kwargs):
        time.sleep(uniform(0.05, 0.1))
        return ["10:00", "10:30", "11:00", "11:30"]

    import app.services.calendar.service as _cal_svc

    def _mock_slot_sigue_libre(*args, **kwargs) -> bool:
        time.sleep(uniform(0.05, 0.1))
        return True

    setattr(_cal, "get_slots_disponibles_for_days", _get_slots_disponibles_for_days)
    setattr(_cal, "get_citas_futuras", _get_citas_futuras)
    setattr(_cal, "reservar_cita", _mock_reservar_cita)
    setattr(_cal, "get_slots_disponibles", _mock_get_slots_disponibles)
    setattr(_cal_svc, "slot_sigue_libre", _mock_slot_sigue_libre)


def apply_realistic() -> None:
    """Patch only WhatsApp and Calendar writes; leave Calendar reads real."""
    import app.services.calendar.mutations as _cal_mutations
    import app.services.calendar.service as _cal_svc

    # ── WhatsApp stubs ────────────────────────────────────────────────────────

    def _send_text_message(to: str, text: str, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    def _send_interactive(to: str, payload: dict, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    def _send_template(to: str, *args, **kwargs) -> None:
        time.sleep(uniform(0.05, 0.15))
        store.mark_responded(to)

    setattr(_wa, "send_text_message", _send_text_message)
    setattr(_wa, "send_interactive", _send_interactive)
    setattr(_wa, "send_template", _send_template)

    # ── Calendar write stubs ──────────────────────────────────────────────────

    def _mock_crear_cita(*args, **kwargs):
        time.sleep(uniform(0.2, 0.4))
        return "stress_realistic_fake_id"

    setattr(_cal, "crear_cita", _mock_crear_cita)
    setattr(_cal_mutations, "crear_cita", _mock_crear_cita)
    setattr(_cal_svc, "crear_cita", _mock_crear_cita)
