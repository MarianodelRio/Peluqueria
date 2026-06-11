# tests/test_parser.py
"""
Unit tests for utils/parser.py.
All functions must be case-insensitive, accent-tolerant and never raise.
"""
from app.utils.parser import (
    _norm,
    _strip_html,
    parse_nombre,
    parse_tel,
    parse_estado,
    parse_reminder,
    parse_cfg,
    parse_servicio_from_title,
    set_field,
    remove_field,
)


# ── _norm ───────────────────────────────────────────────────────────────────

class TestNorm:
    def test_lowercase(self):
        assert _norm("CONFIRMADA") == "confirmada"

    def test_accent_stripped(self):
        # sí → si  (combining acute removed)
        assert _norm("sí") == "si"
        assert _norm("Sí") == "si"
        assert _norm("SÍ") == "si"

    def test_nfc_precomposed(self):
        # NFC variant (single codepoint é) and NFD (e + combining accent) both → e
        assert _norm("\xe9") == "e"          # é precomposed
        assert _norm("é") == "e"       # e + combining acute

    def test_whitespace_stripped(self):
        assert _norm("  pendiente  ") == "pendiente"

    def test_empty_string(self):
        assert _norm("") == ""

    def test_none_like_empty(self):
        # _norm only receives str; falsy str → ""
        assert _norm("") == ""

    def test_mixed(self):
        assert _norm("  PéNdIeNtE  ") == "pendiente"


# ── _strip_html ──────────────────────────────────────────────────────────────

class TestStripHtml:
    def test_no_html(self):
        assert _strip_html("Nombre: Juan") == "Nombre: Juan"

    def test_br_becomes_newline(self):
        result = _strip_html("Estado: confirmada<br>Recordatorio: no")
        assert "\n" in result
        assert "<br>" not in result

    def test_tags_removed(self):
        result = _strip_html("<p>Hola</p>")
        assert "<p>" not in result
        assert "Hola" in result

    def test_entities_decoded(self):
        assert _strip_html("&amp;") == "&"
        assert _strip_html("&nbsp;") == "\xa0"
        assert _strip_html("&lt;b&gt;") == "<b>"

    def test_empty(self):
        assert _strip_html("") == ""

    def test_none_passthrough(self):
        # _strip_html("") should not raise; falsy check covers None in callers
        assert _strip_html("") == ""


# ── parse_nombre ─────────────────────────────────────────────────────────────

class TestParseNombre:
    def test_basic(self):
        assert parse_nombre("Nombre: Juan García") == "Juan García"

    def test_case_insensitive(self):
        assert parse_nombre("NOMBRE: María") == "María"

    def test_extra_spaces(self):
        assert parse_nombre("Nombre:   Paco  ") == "Paco"

    def test_missing(self):
        assert parse_nombre("Estado: confirmada") is None

    def test_empty(self):
        assert parse_nombre("") is None

    def test_none(self):
        assert parse_nombre(None) is None

    def test_multiline(self):
        desc = "Nombre: Luis\nTelefono: 34600000001\nEstado: confirmada"
        assert parse_nombre(desc) == "Luis"


# ── parse_tel ────────────────────────────────────────────────────────────────

class TestParseTel:
    def test_telefono_field(self):
        assert parse_tel("Telefono: 34600000001") == "34600000001"

    def test_tel_legacy(self):
        assert parse_tel("Tel: 34600000001") == "34600000001"

    def test_spaces_stripped(self):
        assert parse_tel("Telefono: 346 000 000 01") == "34600000001"

    def test_dashes_stripped(self):
        assert parse_tel("Telefono: 346-000-000-01") == "34600000001"

    def test_plus_prefix_stripped_for_normalisation(self):
        # '+' is stripped so WhatsApp numbers (no '+') match
        # manual Calendar entries ('+34...')
        result = parse_tel("Telefono: +34600000001")
        assert result == "34600000001"

    def test_9digit_spanish_number_normalised(self):
        # Barber writes '600000001' (no country code) → normalised to '34600000001'
        assert parse_tel("Telefono: 600000001") == "34600000001"

    def test_9digit_with_spaces_normalised(self):
        assert parse_tel("Telefono: 600 000 001") == "34600000001"

    def test_9digit_with_plus_normalised(self):
        # '+600000001' is unusual but should also normalise correctly
        assert parse_tel("Telefono: +600000001") == "34600000001"

    def test_11digit_with_country_code_unchanged(self):
        # Already has '34' prefix → no double-prepend
        assert parse_tel("Telefono: 34600000001") == "34600000001"

    def test_too_short_rejected(self):
        # fewer than 7 digits → None
        assert parse_tel("Telefono: 123") is None

    def test_too_long_rejected(self):
        # more than 15 digits → None
        assert parse_tel("Telefono: 1234567890123456") is None

    def test_missing(self):
        assert parse_tel("Estado: confirmada") is None

    def test_empty(self):
        assert parse_tel("") is None

    def test_html_in_description(self):
        # Google Calendar may inject HTML
        assert parse_tel("Telefono: 34600000001<br>Estado: confirmada") == "34600000001"


# ── parse_estado ─────────────────────────────────────────────────────────────

class TestParseEstado:
    def test_confirmada(self):
        assert parse_estado("Estado: confirmada") == "confirmada"

    def test_pendiente(self):
        assert parse_estado("Estado: pendiente") == "pendiente"

    def test_uppercase(self):
        assert parse_estado("ESTADO: CONFIRMADA") == "confirmada"

    def test_with_accent(self):
        # e.g. someone types "Confirmáda" — normalised → "confirmada"
        assert parse_estado("Estado: Confirmáda") == "confirmada"

    def test_unknown_value(self):
        assert parse_estado("Estado: cancelada") is None

    def test_missing(self):
        assert parse_estado("Nombre: Juan") is None

    def test_empty(self):
        assert parse_estado("") is None


# ── parse_reminder ───────────────────────────────────────────────────────────

class TestParseReminder:
    def test_recordatorio_si(self):
        assert parse_reminder("Recordatorio: sí") == "si"

    def test_recordatorio_si_no_accent(self):
        assert parse_reminder("Recordatorio: si") == "si"

    def test_recordatorio_no(self):
        assert parse_reminder("Recordatorio: no") == "no"

    def test_uppercase(self):
        assert parse_reminder("RECORDATORIO: SI") == "si"

    def test_legacy_reminder24h(self):
        assert parse_reminder("Reminder24h: si") == "si"
        assert parse_reminder("Reminder24h: no") == "no"

    def test_recordatorio_takes_priority_over_legacy(self):
        # Both present — Recordatorio wins
        desc = "Recordatorio: no\nReminder24h: si"
        assert parse_reminder(desc) == "no"

    def test_invalid_value(self):
        assert parse_reminder("Recordatorio: quiza") is None

    def test_empty(self):
        assert parse_reminder("") is None


# ── parse_cfg ─────────────────────────────────────────────────────────────────

class TestParseCfg:
    def test_cerrado(self):
        assert parse_cfg("[CFG] CERRADO") == {"type": "cerrado"}

    def test_vacaciones(self):
        assert parse_cfg("[CFG] Vacaciones") == {"type": "vacaciones"}

    def test_horario(self):
        result = parse_cfg("[CFG] HORARIO 10:00-14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_horario_no_space(self):
        # Tolerance: no space between "horario" and the time
        result = parse_cfg("[CFG] HORARIO10:00-14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_horario_en_dash(self):
        # En-dash separator (–)
        result = parse_cfg("[CFG] HORARIO 10:00–14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_cfg_lowercase(self):
        assert parse_cfg("[cfg] cerrado") == {"type": "cerrado"}

    def test_cfg_with_accents(self):
        # Vacáciones (weird accent) — _norm strips it
        assert parse_cfg("[CFG] Vacáciones") == {"type": "vacaciones"}

    def test_no_cfg_tag(self):
        assert parse_cfg("CERRADO") is None

    def test_cfg_unknown_type(self):
        # [CFG] but no recognised keyword → None
        assert parse_cfg("[CFG] DESCANSO") is None

    def test_empty(self):
        assert parse_cfg("") is None

    def test_none(self):
        assert parse_cfg(None) is None

    def test_horario_single_digit_hour(self):
        result = parse_cfg("[CFG] HORARIO 9:00-13:00")
        assert result == {"type": "horario", "start": "9:00", "end": "13:00"}


# ── parse_servicio_from_title ─────────────────────────────────────────────────

class TestParseServicioFromTitle:
    def test_basic_corte(self):
        result = parse_servicio_from_title("Corte - Juan Garcia")
        assert result == ("corte", "Juan Garcia")

    def test_corte_barba_y(self):
        result = parse_servicio_from_title("Corte y barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_corte_barba_plus(self):
        result = parse_servicio_from_title("Corte+barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_corte_barba_space(self):
        result = parse_servicio_from_title("Corte barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_mechas(self):
        result = parse_servicio_from_title("Mechas - Ana Lopez")
        assert result == ("mechas", "Ana Lopez")

    def test_unknown_returns_none(self):
        assert parse_servicio_from_title("Tinte - Lucia") == (None, None)

    def test_empty_string(self):
        assert parse_servicio_from_title("") == (None, None)

    def test_none_input(self):
        assert parse_servicio_from_title(None) == (None, None)

    def test_accent_tolerance(self):
        # "Méchas" with accent on e — _norm strips it
        assert parse_servicio_from_title("Méchas - Ángela") == ("mechas", "Ángela")

    def test_nombre_original_casing_preserved(self):
        # Right part returned with original casing
        key, nombre = parse_servicio_from_title("Corte - María José")
        assert key == "corte"
        assert nombre == "María José"

    def test_no_separator_returns_none(self):
        assert parse_servicio_from_title("Corte Juan Garcia") == (None, None)

    def test_em_dash_separator(self):
        # em-dash (–) used as separator
        result = parse_servicio_from_title("Corte – Juan Garcia")
        assert result == ("corte", "Juan Garcia")


# ── set_field ─────────────────────────────────────────────────────────────────

class TestSetField:
    def test_append_new_field(self):
        result = set_field("Nombre: Ana", "Estado", "confirmada")
        assert "Estado: confirmada" in result
        assert "Nombre: Ana" in result

    def test_replace_existing_field(self):
        desc = "Nombre: Ana\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert "Estado: confirmada" in result
        assert "pendiente" not in result

    def test_case_insensitive_replace(self):
        desc = "ESTADO: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert (
            result.count("Estado") == 1
            or result.count("estado") + result.count("Estado") == 1
        )
        assert "pendiente" not in result

    def test_removes_duplicates(self):
        # Two Estado lines — set_field should collapse to one
        desc = "Estado: pendiente\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert result.count("Estado:") == 1
        assert "confirmada" in result

    def test_empty_description(self):
        result = set_field("", "Estado", "confirmada")
        assert result == "Estado: confirmada"

    def test_none_description(self):
        result = set_field(None, "Estado", "confirmada")
        assert result == "Estado: confirmada"

    def test_other_fields_preserved(self):
        desc = "Nombre: Juan\nTelefono: 34600000001\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert "Nombre: Juan" in result
        assert "Telefono: 34600000001" in result


# ── remove_field ──────────────────────────────────────────────────────────────

class TestRemoveField:
    def test_removes_existing(self):
        desc = "Estado: confirmada\nNombre: Ana"
        result = remove_field(desc, "Estado")
        assert "Estado" not in result
        assert "Nombre: Ana" in result

    def test_case_insensitive(self):
        result = remove_field("ESTADO: confirmada\nNombre: Ana", "Estado")
        assert "ESTADO" not in result

    def test_noop_when_missing(self):
        desc = "Nombre: Ana"
        assert remove_field(desc, "Estado") == desc

    def test_empty(self):
        assert remove_field("", "Estado") == ""

    def test_none(self):
        assert remove_field(None, "Estado") == ""
