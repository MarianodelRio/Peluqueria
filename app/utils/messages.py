# utils/messages.py
"""Residual text messages used alongside interactive messages."""
from datetime import date

from app.utils.slots import format_date_es


def msg_cita_confirmada(d: date, hora: str, servicio: dict) -> str:
    return (
        f"¡Tu cita está confirmada! ✅\n\n"
        f"✂️ {servicio['nombre']} — {servicio['precio']}€\n"
        f"📅 {format_date_es(d).capitalize()}\n"
        f"🕒 {hora}"
    )


def msg_cancelacion_ok() -> str:
    return "Tu cita ha sido cancelada ✅"


def msg_cancelacion_abortada() -> str:
    return "Cancelación descartada. ¡Hasta pronto!"


def msg_sin_citas() -> str:
    return "No tienes ninguna cita próxima."


def msg_sin_slots() -> str:
    return "No hay horarios disponibles para ese día. Prueba con otro día."


def msg_doble_reserva() -> str:
    return "Ya tienes una cita ese día 🙂\nSi necesitas cambiarla, cancélala primero desde el menú."


def msg_slot_no_disponible() -> str:
    return "Ese horario ya no está disponible 😕"


def msg_error_creando_cita() -> str:
    return "Ha ocurrido un error al crear tu cita. Inténtalo de nuevo."
