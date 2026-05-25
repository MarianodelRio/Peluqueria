# tests/test_config.py
"""
Unit tests for _load_and_validate_yaml in app/config.py.
All tests operate against temporary files via tmp_path; no live config.yaml is modified.
"""
import pytest
import yaml
import pathlib

from app.config import _load_and_validate_yaml


# ── Helper ─────────────────────────────────────────────────────────────────────

def _write_yaml(tmp_path: pathlib.Path, data: dict) -> pathlib.Path:
    """Write a YAML file to tmp_path and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _minimal_valid() -> dict:
    """Return a minimal valid config dict that passes all 8 rules."""
    return {
        "negocio": {
            "nombre": "Test Barber",
            "telefono_contacto": "+34 600 000 000",
        },
        "horario": {
            "lunes": [["10:00", "14:00"]],
        },
        "ventana_busqueda_dias": 14,
        "servicios": {
            "corte": {
                "nombre": "Corte de pelo",
                "precio": 10,
                "duracion_min": 30,
                "presencia_cliente_min": 30,
            },
        },
        "lookaheads_dias": {
            "citas_cliente": 30,
            "citas_manuales": 60,
        },
        "recordatorio_horas_antes": {
            "desde": 23,
            "hasta": 25,
        },
        "envios": {
            "recordatorios": True,
            "confirmaciones": True,
        },
    }


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestValidConfigLoads:
    def test_valid_config_loads_all_constants(self, tmp_path):
        p = _write_yaml(tmp_path, _minimal_valid())
        cfg = _load_and_validate_yaml(str(p))

        assert "negocio" in cfg
        assert cfg["negocio"]["nombre"] == "Test Barber"
        assert cfg["negocio"]["telefono_contacto"] == "+34 600 000 000"
        assert isinstance(cfg["horario"], dict)
        assert isinstance(cfg["ventana_busqueda_dias"], int)
        assert isinstance(cfg["servicios"], dict)
        assert isinstance(cfg["lookaheads_dias"]["citas_cliente"], int)
        assert isinstance(cfg["lookaheads_dias"]["citas_manuales"], int)
        assert isinstance(cfg["recordatorio_horas_antes"]["desde"], int)
        assert isinstance(cfg["recordatorio_horas_antes"]["hasta"], int)
        assert isinstance(cfg["envios"]["recordatorios"], bool)
        assert isinstance(cfg["envios"]["confirmaciones"], bool)


# ── File-level errors ──────────────────────────────────────────────────────────

class TestFileErrors:
    def test_missing_file_raises_runtime_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="Cannot load config.yaml"):
            _load_and_validate_yaml(str(tmp_path / "nonexistent.yaml"))

    def test_invalid_yaml_raises_runtime_error(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("{unclosed: bracket", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Cannot load config.yaml"):
            _load_and_validate_yaml(str(p))


# ── Rule 2: negocio ────────────────────────────────────────────────────────────

class TestRule2Negocio:
    def test_missing_nombre_raises(self, tmp_path):
        data = _minimal_valid()
        data["negocio"]["nombre"] = ""
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 2"):
            _load_and_validate_yaml(str(p))

    def test_missing_telefono_raises(self, tmp_path):
        data = _minimal_valid()
        data["negocio"]["telefono_contacto"] = ""
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 2"):
            _load_and_validate_yaml(str(p))


# ── Rule 3: horario ────────────────────────────────────────────────────────────

class TestRule3Horario:
    def test_bad_day_key_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"]["martes_mal"] = [["10:00", "14:00"]]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))

    def test_range_with_one_element_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"]["lunes"] = [["10:00"]]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))

    def test_fin_equal_to_inicio_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"]["lunes"] = [["10:00", "10:00"]]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))

    def test_fin_before_inicio_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"]["lunes"] = [["14:00", "10:00"]]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))

    def test_overlapping_ranges_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"]["lunes"] = [["10:00", "14:00"], ["13:00", "18:00"]]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))

    def test_empty_horario_raises(self, tmp_path):
        data = _minimal_valid()
        data["horario"] = {}
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 3"):
            _load_and_validate_yaml(str(p))


# ── Rule 4: ventana_busqueda_dias ─────────────────────────────────────────────

class TestRule4VentanaBusquedaDias:
    def test_zero_raises(self, tmp_path):
        data = _minimal_valid()
        data["ventana_busqueda_dias"] = 0
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 4"):
            _load_and_validate_yaml(str(p))

    def test_string_raises(self, tmp_path):
        data = _minimal_valid()
        data["ventana_busqueda_dias"] = "14"
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 4"):
            _load_and_validate_yaml(str(p))

    def test_bool_raises(self, tmp_path):
        data = _minimal_valid()
        data["ventana_busqueda_dias"] = True
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 4"):
            _load_and_validate_yaml(str(p))


# ── Rule 5: servicios ─────────────────────────────────────────────────────────

class TestRule5Servicios:
    def test_empty_servicios_raises(self, tmp_path):
        data = _minimal_valid()
        data["servicios"] = {}
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 5"):
            _load_and_validate_yaml(str(p))

    def test_presencia_less_than_duracion_raises(self, tmp_path):
        data = _minimal_valid()
        data["servicios"]["corte"]["presencia_cliente_min"] = 20
        data["servicios"]["corte"]["duracion_min"] = 30
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 5"):
            _load_and_validate_yaml(str(p))

    def test_negative_precio_raises(self, tmp_path):
        data = _minimal_valid()
        data["servicios"]["corte"]["precio"] = -1
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 5"):
            _load_and_validate_yaml(str(p))

    def test_zero_duracion_min_raises(self, tmp_path):
        data = _minimal_valid()
        data["servicios"]["corte"]["duracion_min"] = 0
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 5"):
            _load_and_validate_yaml(str(p))


# ── Rule 5 sub-case: too many services ────────────────────────────────────────

class TestRule5TooManyServicios:
    def test_ten_services_raises(self, tmp_path):
        data = _minimal_valid()
        for i in range(10):
            data["servicios"][f"svc_{i}"] = {
                "nombre": f"Servicio {i}",
                "precio": 10,
                "duracion_min": 30,
                "presencia_cliente_min": 30,
            }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 5"):
            _load_and_validate_yaml(str(p))


# ── Rule 6: lookaheads_dias ───────────────────────────────────────────────────

class TestRule6LookaheadsDias:
    def test_citas_cliente_zero_raises(self, tmp_path):
        data = _minimal_valid()
        data["lookaheads_dias"]["citas_cliente"] = 0
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 6"):
            _load_and_validate_yaml(str(p))

    def test_citas_manuales_zero_raises(self, tmp_path):
        data = _minimal_valid()
        data["lookaheads_dias"]["citas_manuales"] = 0
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 6"):
            _load_and_validate_yaml(str(p))


# ── Rule 7: recordatorio_horas_antes ─────────────────────────────────────────

class TestRule7RecordatorioHorasAntes:
    def test_desde_zero_raises(self, tmp_path):
        data = _minimal_valid()
        data["recordatorio_horas_antes"]["desde"] = 0
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 7"):
            _load_and_validate_yaml(str(p))

    def test_hasta_equal_to_desde_raises(self, tmp_path):
        data = _minimal_valid()
        data["recordatorio_horas_antes"]["desde"] = 23
        data["recordatorio_horas_antes"]["hasta"] = 23
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 7"):
            _load_and_validate_yaml(str(p))

    def test_hasta_less_than_desde_raises(self, tmp_path):
        data = _minimal_valid()
        data["recordatorio_horas_antes"]["desde"] = 25
        data["recordatorio_horas_antes"]["hasta"] = 23
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 7"):
            _load_and_validate_yaml(str(p))


# ── Rule 8: envios booleans ───────────────────────────────────────────────────

class TestRule8Envios:
    def test_envios_missing_recordatorios_key_raises(self, tmp_path):
        data = _minimal_valid()
        del data["envios"]["recordatorios"]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 8"):
            _load_and_validate_yaml(str(p))

    def test_envios_missing_confirmaciones_key_raises(self, tmp_path):
        data = _minimal_valid()
        del data["envios"]["confirmaciones"]
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 8"):
            _load_and_validate_yaml(str(p))

    def test_envios_recordatorios_string_raises(self, tmp_path):
        data = _minimal_valid()
        data["envios"]["recordatorios"] = "yes"
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 8"):
            _load_and_validate_yaml(str(p))

    def test_envios_confirmaciones_int_raises(self, tmp_path):
        data = _minimal_valid()
        data["envios"]["confirmaciones"] = 1
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 8"):
            _load_and_validate_yaml(str(p))


# ── Rule 9: evento block ──────────────────────────────────────────────────────

class TestRule9Evento:
    """Rule 9: evento block is optional; deep validation only when activo is True."""

    def test_evento_absent_passes(self, tmp_path):
        """No evento key at all is valid."""
        data = _minimal_valid()
        p = _write_yaml(tmp_path, data)
        cfg = _load_and_validate_yaml(str(p))
        assert "evento" not in cfg or cfg.get("evento") is None

    def test_evento_activo_false_skips_deep_validation(self, tmp_path):
        """activo: false with no other fields passes without error."""
        data = _minimal_valid()
        data["evento"] = {"activo": False}
        p = _write_yaml(tmp_path, data)
        cfg = _load_and_validate_yaml(str(p))
        assert cfg["evento"]["activo"] is False

    def test_valid_active_evento_passes(self, tmp_path):
        """activo: true with valid nombre and dias passes."""
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "nombre": "Navidad",
            "dias": {"2099-12-25": [["10:00", "14:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        cfg = _load_and_validate_yaml(str(p))
        assert cfg["evento"]["activo"] is True

    def test_missing_nombre_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "dias": {"2099-12-25": [["10:00", "14:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))

    def test_empty_nombre_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "nombre": "   ",
            "dias": {"2099-12-25": [["10:00", "14:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))

    def test_missing_dias_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {"activo": True, "nombre": "Navidad"}
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))

    def test_invalid_date_key_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "nombre": "Navidad",
            "dias": {"not-a-date": [["10:00", "14:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))

    def test_fin_before_inicio_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "nombre": "Navidad",
            "dias": {"2099-12-25": [["14:00", "10:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))

    def test_overlapping_ranges_raises(self, tmp_path):
        data = _minimal_valid()
        data["evento"] = {
            "activo": True,
            "nombre": "Navidad",
            "dias": {"2099-12-25": [["10:00", "14:00"], ["13:00", "18:00"]]},
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 9"):
            _load_and_validate_yaml(str(p))


# ── Rule 10: admin_phone ──────────────────────────────────────────────────────

class TestRule10AdminPhone:
    """Rule 10: admin_phone is optional; when present must be a digit-only string."""

    def test_valid_admin_phone_passes(self, tmp_path):
        data = _minimal_valid()
        data["negocio"]["admin_phone"] = "34612345678"
        p = _write_yaml(tmp_path, data)
        _load_and_validate_yaml(str(p))

    def test_admin_phone_absent_passes(self, tmp_path):
        data = _minimal_valid()
        p = _write_yaml(tmp_path, data)
        _load_and_validate_yaml(str(p))

    def test_admin_phone_with_plus_prefix_raises(self, tmp_path):
        data = _minimal_valid()
        data["negocio"]["admin_phone"] = "+34612345678"
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 10"):
            _load_and_validate_yaml(str(p))

    def test_admin_phone_as_integer_raises(self, tmp_path):
        data = _minimal_valid()
        data["negocio"]["admin_phone"] = 34612345678
        p = _write_yaml(tmp_path, data)
        with pytest.raises(RuntimeError, match="Rule 10"):
            _load_and_validate_yaml(str(p))
