# utils/messages.py
"""Residual text messages used alongside interactive messages."""
from datetime import date

from app.utils.slots import format_date_es


def msg_cita_confirmada(d: date, hora: str, servicio: dict) -> str:
    return (
        f"¡Tu cita está confirmada! ✅\n\n"
        f"✂️ {servicio['nombre']} — {servicio['precio']}€\n"
        f"📅 {format_date_es(d).capitalize()}\n"
        f"🕒 {hora}\n\n"
        f"¡Te esperamos! Si necesitas hacer algún cambio, puedes cancelar o reservar una nueva cita desde el menú cuando quieras. 💈"
    )


def msg_cancelacion_ok() -> str:
    return "Tu cita ha sido cancelada ✅\n\nSi quieres reservar una nueva cita o necesitas algo más, escríbenos cuando quieras. ¡Hasta pronto! 💈"


def msg_sin_citas() -> str:
    return "No tienes ninguna cita próxima."


def msg_sin_slots() -> str:
    return "No hay horarios disponibles para ese día. Prueba con otro día."


def msg_slot_no_disponible() -> str:
    return "Ese horario ya no está disponible 😕"


def msg_error_creando_cita() -> str:
    return "Ha ocurrido un error al crear tu cita. Inténtalo de nuevo."


def msg_evento_sin_dias() -> str:
    return (
        "No hay fechas disponibles para el evento en este momento. "
        "Puedes volver al menú cuando quieras."
    )
