# utils/interactive.py
"""
Builders for WhatsApp Cloud API interactive message payloads.

WhatsApp limits:
- button reply: max 3 buttons, button text max 20 chars, id max 256 chars
- list message: max 10 TOTAL rows across ALL sections, row title max 24 chars
  → always keep rows ≤ 9 content rows + 1 nav row = 10 max
"""
from datetime import date
from typing import List, Optional
from app.config import INTERACTIVE_FOOTER, CONTACT_PHONE, SERVICIOS, BUSINESS_NAME
from app.utils.slots import format_date_es


# ── Helpers ────────────────────────────────────────────────────────────────

def _trunc(text: str, max_len: int) -> str:
    """Truncate text to max_len chars."""
    return text[:max_len] if len(text) > max_len else text


def _button(id_: str, title: str) -> dict:
    return {"type": "reply", "reply": {"id": id_, "title": _trunc(title, 20)}}


def _row(id_: str, title: str, description: str = "") -> dict:
    row = {"id": id_, "title": _trunc(title, 24)}
    if description:
        row["description"] = _trunc(description, 72)
    return row


def _section(title: str, rows: list) -> dict:
    return {"title": title, "rows": rows}


def _interactive_buttons(body: str, buttons: list,
                         header: Optional[str] = None) -> dict:
    msg: dict = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "footer": {"text": INTERACTIVE_FOOTER},
            "action": {"buttons": buttons},
        },
    }
    if header:
        msg["interactive"]["header"] = {"type": "text", "text": header}
    return msg


def _interactive_list(body: str, button_label: str, sections: list,
                      header: Optional[str] = None) -> dict:
    msg: dict = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "footer": {"text": INTERACTIVE_FOOTER},
            "action": {"button": _trunc(button_label, 20), "sections": sections},
        },
    }
    if header:
        msg["interactive"]["header"] = {"type": "text", "text": header}
    return msg


# ── Public builders ────────────────────────────────────────────────────────

def build_main_menu() -> dict:
    """Main menu with 3 reply buttons."""
    return _interactive_buttons(
        header=f"✂️ {BUSINESS_NAME}",
        body="💈 ¡Bienvenido!\n¿En qué podemos ayudarte hoy?\n\n📞 Para otras consultas, llámanos al " + CONTACT_PHONE,
        buttons=[
            _button("menu_book",   "📅 Pedir cita"),
            _button("menu_view",   "📋 Mis citas"),
            _button("menu_cancel", "❌ Cancelar cita"),
        ],
    )


def build_period_select(d: date, morning_range: str, afternoon_range: str) -> dict:
    """
    Ask user to choose morning or afternoon.
    morning_range / afternoon_range: 'HH:MM-HH:MM' strings, e.g. '10:00-14:00'.
    Only call this when both periods have available slots.
    """
    buttons = [
        _button("period_morning",   f"Mañana {morning_range}"),
        _button("period_afternoon", f"Tarde {afternoon_range}"),
        _button("back_to_day",       "📅 Cambiar día"),
    ]
    return _interactive_buttons(
        header=f"📅 {format_date_es(d).capitalize()}",
        body="¿Prefieres mañana o tarde?",
        buttons=buttons,
    )


def build_days_list(days: List[date]) -> dict:
    """List of available days + back to menu."""
    days = days[:9]
    rows = [_row(f"day_{d.isoformat()}", format_date_es(d).capitalize()) for d in days]
    rows.append(_row("back_to_menu", "↩️ Volver al menú"))
    return _interactive_list(
        header="📅 Elige un día",
        body="Selecciona el día para tu cita:",
        button_label="Ver días",
        sections=[_section("Días disponibles", rows)],
    )


def build_back_to_menu_message(body: str) -> dict:
    """Single-button interactive message with a 'back to menu' button."""
    return _interactive_buttons(body=body, buttons=[_button("back_to_menu", "↩️ Volver al menú")])


def build_hours_list(d: date, slots: List[str], came_from_period: bool = False) -> dict:
    """List of available time slots + single contextual nav row.

    came_from_period=True:  caps slots at 9, appends back_to_period (10 rows max).
    came_from_period=False: caps slots at 9, appends back_to_day    (10 rows max).
    """
    capped = slots[:9]
    rows = [_row(f"hour_{d.isoformat()}_{s.replace(':', '')}", f"🕒 {s}") for s in capped]
    if came_from_period:
        rows.append(_row("back_to_period", "↩️ Cambiar turno"))
    else:
        rows.append(_row("back_to_day", "📅 Cambiar día"))
    return _interactive_list(
        header=f"🕒 {format_date_es(d).capitalize()}",
        body="Selecciona la hora:",
        button_label="Ver horas",
        sections=[_section("Horas disponibles", rows)],
    )


def build_service_select() -> dict:
    """Ask user to choose a service (interactive list, dynamic from SERVICIOS)."""
    rows = [
        _row(f"service_{key}", svc["nombre"], f"{svc['precio']} €")
        for key, svc in SERVICIOS.items()
    ]
    rows.append(_row("back_to_menu", "↩️ Volver al menú"))
    return _interactive_list(
        header="✂️ Elige tu servicio",
        body="¿Qué servicio quieres?",
        button_label="Ver servicios",
        sections=[_section("Servicios", rows)],
    )


def build_appointments_view(citas: list) -> dict:
    """
    Show all future appointments as a button message.
    citas: list of dicts with keys 'id', 'start' (datetime).
    """
    if not citas:
        return _interactive_buttons(
            body="No tienes citas próximas.",
            buttons=[_button("back_to_menu", "↩️ Volver al menú")],
        )

    body = "Tus próximas citas:\n\n"
    for c in citas[:8]:
        d = c['start'].date()
        hora = c['start'].strftime('%H:%M')
        body += f"📅 {format_date_es(d).capitalize()} — 🕒 {hora}\n"
    body += "\nSi necesitas algo más, escríbenos cuando quieras 😊"

    return _interactive_buttons(
        header=f"📋 {BUSINESS_NAME}",
        body=body,
        buttons=[_button("back_to_menu", "↩️ Volver al menú")],
    )


def build_cancel_select(citas: list) -> dict:
    """
    List of future appointments to choose which to cancel.
    Flat list, max 9 appointments + 1 nav = 10 rows.
    """
    if not citas:
        return _interactive_buttons(
            body="No tienes citas para cancelar.",
            buttons=[_button("back_to_menu", "↩️ Volver al menú")],
        )

    rows = []
    for c in citas[:9]:  # hard cap at 9 to leave room for back button
        d = c['start'].date()
        hora = c['start'].strftime('%H:%M')
        rows.append(_row(
            f"cancel_appt_{c['id']}",
            _trunc(f"📅 {format_date_es(d)}", 24),
            f"🕒 {hora}",
        ))
    rows.append(_row("back_to_menu", "↩️ Volver al menú"))

    return _interactive_list(
        header="❌ Cancelar cita",
        body="¿Qué cita quieres cancelar?",
        button_label="Ver citas",
        sections=[_section("Tus citas", rows)],
    )


