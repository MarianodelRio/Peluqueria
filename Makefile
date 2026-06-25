# ══════════════════════════════════════════════════════════════════════════════
#  Peluquería Citas — Makefile de despliegue y operación
#
#  Uso rápido:
#    make all     →  instalación completa con ngrok (primera vez)
#    make update  →  desplegar cambios de código (día a día)
#
#  Configura NGROK_DOMAIN antes de ejecutar make all.
# ══════════════════════════════════════════════════════════════════════════════

# ── Variables — edita esta línea según tu caso ─────────────────────────────
NGROK_DOMAIN := unpermanently-repairable-devon.ngrok-free.dev
WATCHDOG_INTERVAL := 0

# ── Variables automáticas — no tocar ──────────────────────────────────────
USER        := $(shell whoami)
APP_DIR     := /home/$(USER)/app
VENV        := $(APP_DIR)/venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
PYTEST      := $(shell test -x $(VENV)/bin/pytest && echo $(VENV)/bin/pytest || echo pytest)
RUFF        := $(shell test -x $(VENV)/bin/ruff  && echo $(VENV)/bin/ruff  || echo ruff)
MYPY        := $(shell test -x $(VENV)/bin/mypy  && echo $(VENV)/bin/mypy  || echo mypy)
LOG_DIR     := /var/log/peluqueria

define PELUQUERIA_SERVICE
[Unit]
Description=Peluquería Citas — FastAPI
After=network.target

[Service]
Type=simple
User=$(USER)
WorkingDirectory=$(APP_DIR)
EnvironmentFile=$(APP_DIR)/.env
ExecStart=$(UVICORN) app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=peluqueria

[Install]
WantedBy=multi-user.target
endef
export PELUQUERIA_SERVICE

define NGROK_SERVICE
[Unit]
Description=ngrok tunnel — Peluquería
After=network.target peluqueria.service
Requires=peluqueria.service

[Service]
Type=simple
User=$(USER)
ExecStart=/usr/local/bin/ngrok http --domain=$(NGROK_DOMAIN) 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=perok

[Install]
WantedBy=multi-user.target
endef
export NGROK_SERVICE

define RESTART_SERVICE
[Unit]
Description=Reinicio nocturno del bot

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart peluqueria
ExecStartPost=/usr/bin/journalctl --vacuum-time=1d
ExecStartPost=/usr/bin/truncate -s 0 /var/log/peluqueria/watchdog.log
endef
export RESTART_SERVICE

define RESTART_TIMER
[Unit]
Description=Reinicia el bot cada noche a las 4:00 AM

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
endef
export RESTART_TIMER

.DEFAULT_GOAL := help

# ══════════════════════════════════════════════════════════════════════════════
#  AYUDA
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: help
help:
	@echo ""
	@echo "  Peluquería Citas — comandos disponibles"
	@echo ""
	@echo "  PRIMERA INSTALACIÓN (en orden)"
	@echo "    make setup      Instala dependencias del sistema"
	@echo "    make install    Crea entorno virtual e instala Python deps"
	@echo "    make services   Registra servicios systemd y watchdog cron"
	@echo "    make start      Arranca todos los servicios"
	@echo ""
	@echo "  OPERACIÓN DIARIA"
	@echo "    make update     Descarga cambios de código (git pull + pip)"
	@echo "    make test       Ejecuta la suite de tests (pytest)"
	@echo "    make start      Arranca o reinicia todos los servicios"
	@echo "    make status     Estado de todos los servicios"
	@echo "    make health     Comprueba /health del bot"
	@echo "    make logs       Logs del bot en tiempo real"
	@echo "    make logs-ngrok     Logs de ngrok en tiempo real"
	@echo "    make logs-watchdog  Logs del watchdog"
	@echo ""
	@echo "  UTILIDADES"
	@echo "    make lint       Ejecuta ruff y mypy"
	@echo "    make qr         Genera el QR de WhatsApp → qr_cita.png"
	@echo "    make vacuum-logs    Vacía journal (>1d) y watchdog.log ahora"
	@echo "    make stop       Para todos los servicios"
	@echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  PRIMERA INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: all
all: _check-env setup install services start
	@echo ""
	@echo "  ✓ Instalación completa (modo ngrok)"
	@echo "  Comprueba el estado con: make status"
	@echo "  Comprueba el bot con:    make health"
	@echo ""

# ── Comprobaciones previas ─────────────────────────────────────────────────

.PHONY: _check-env
_check-env:
	@test -f $(APP_DIR)/.env || { echo "ERROR: falta $(APP_DIR)/.env — cópialo de .env.example y rellénalo"; exit 1; }
	@test -f $(APP_DIR)/credentials.json || { echo "ERROR: falta $(APP_DIR)/credentials.json — súbelo desde tu máquina local"; exit 1; }

# ── Dependencias del sistema ───────────────────────────────────────────────

.PHONY: setup
setup:
	@echo "→ Instalando dependencias del sistema..."
	sudo apt-get update -qq
	sudo apt-get install -y python3.11 python3.11-venv git curl
	@echo "→ Instalando ngrok..."
	@if ! command -v ngrok >/dev/null 2>&1; then \
		curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
			| sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null; \
		echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
			| sudo tee /etc/apt/sources.list.d/ngrok.list; \
		sudo apt-get update -qq && sudo apt-get install -y ngrok; \
	else \
		echo "   ngrok ya instalado, omitiendo"; \
	fi
	@echo "→ Creando directorio de logs..."
	sudo mkdir -p $(LOG_DIR)
	sudo chown $(USER):$(USER) $(LOG_DIR)
	@echo "   ✓ setup completado"

# ── Entorno Python ─────────────────────────────────────────────────────────

.PHONY: install
install:
	@echo "→ Creando entorno virtual..."
	@if [ ! -d $(VENV) ]; then python3.11 -m venv $(VENV); fi
	@echo "→ Instalando dependencias Python..."
	$(PIP) install --upgrade pip -q
	$(PIP) install -r $(APP_DIR)/requirements.txt -q
	@echo "   ✓ install completado"

# ── Servicios systemd ─────────────────────────────────────────────────────

.PHONY: services
services: _check-env _service-uvicorn _service-ngrok _service-restart _watchdog-cron
	@echo "→ Configurando token de ngrok..."
	@NGROK_TOKEN=$$(grep -E '^NGROK_TOKEN=' $(APP_DIR)/.env | cut -d= -f2); \
	if [ -n "$$NGROK_TOKEN" ]; then \
		ngrok config add-authtoken $$NGROK_TOKEN; \
	else \
		echo "   AVISO: NGROK_TOKEN no está en .env — configúralo manualmente con:"; \
		echo "   ngrok config add-authtoken TU_TOKEN"; \
	fi
	sudo systemctl daemon-reload
	sudo systemctl enable peluqueria ngrok peluqueria-restart.timer
	@echo "   ✓ servicios systemd instalados — ejecuta 'make start' para arrancarlos"

# ── Generadores de ficheros systemd ───────────────────────────────────────

.PHONY: _service-uvicorn
_service-uvicorn:
	@echo "→ Creando peluqueria.service..."
	@printf '%s\n' "$$PELUQUERIA_SERVICE" | sudo tee /etc/systemd/system/peluqueria.service > /dev/null

.PHONY: _service-ngrok
_service-ngrok:
	@echo "→ Creando ngrok.service..."
	@printf '%s\n' "$$NGROK_SERVICE" | sudo tee /etc/systemd/system/ngrok.service > /dev/null

.PHONY: _service-restart
_service-restart:
	@echo "→ Creando peluqueria-restart.service y timer..."
	@printf '%s\n' "$$RESTART_SERVICE" | sudo tee /etc/systemd/system/peluqueria-restart.service > /dev/null
	@printf '%s\n' "$$RESTART_TIMER" | sudo tee /etc/systemd/system/peluqueria-restart.timer > /dev/null

# ── Watchdog cron ──────────────────────────────────────────────────────────

.PHONY: _watchdog-cron
_watchdog-cron:
	@echo "→ Configurando cron del watchdog..."
	@CRON_LINE="$(WATCHDOG_INTERVAL) * * * * cd $(APP_DIR) && $(PYTHON) watchdog.py >> $(LOG_DIR)/watchdog.log 2>&1"; \
	( crontab -l 2>/dev/null | grep -v watchdog.py; echo "$$CRON_LINE" ) | crontab -
	@echo "   ✓ watchdog activo ($(WATCHDOG_INTERVAL))"

# ══════════════════════════════════════════════════════════════════════════════
#  OPERACIÓN DIARIA
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: update
update:
	@echo "→ Desplegando cambios..."
	cd $(APP_DIR) && git pull
	$(PIP) install -r $(APP_DIR)/requirements.txt -q
	@echo "   ✓ actualización completada — ejecuta 'make start' si necesitas reiniciar"

.PHONY: status
status:
	@echo "── peluqueria ──────────────────────────────────────────"
	@sudo systemctl status peluqueria --no-pager -l | head -8
	@echo ""
	@echo "── ngrok ───────────────────────────────────────────────"
	@sudo systemctl status ngrok --no-pager -l | head -6
	@echo ""
	@echo "── reinicio nocturno ───────────────────────────────────"
	@sudo systemctl status peluqueria-restart.timer --no-pager -l | head -5

.PHONY: health
health:
	@curl -s http://localhost:8000/health | python3 -m json.tool

.PHONY: logs
logs:
	sudo journalctl -u peluqueria -f

.PHONY: logs-ngrok
logs-ngrok:
	sudo journalctl -u ngrok -f

.PHONY: logs-watchdog
logs-watchdog:
	tail -f $(LOG_DIR)/watchdog.log

# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: test
test:
	$(PYTEST) -q

.PHONY: lint
lint:
	$(RUFF) check .
	PYTHONPATH=. $(MYPY) app

.PHONY: qr
qr:
	$(PYTHON) $(APP_DIR)/generar_qr.py
	@echo "   ✓ QR guardado en qr_cita.png"

.PHONY: start
start:
	@if sudo systemctl is-active --quiet peluqueria; then \
		sudo systemctl restart peluqueria; \
	else \
		sudo systemctl start peluqueria; \
	fi
	@sleep 2
	@if sudo systemctl is-active --quiet ngrok; then \
		sudo systemctl restart ngrok; \
	else \
		sudo systemctl start ngrok; \
	fi
	sudo systemctl start peluqueria-restart.timer
	@sudo systemctl is-active --quiet peluqueria \
		&& echo "   ✓ servicios arrancados" \
		|| echo "   ✗ ERROR: el bot no arrancó — ejecuta: make logs"

.PHONY: stop
stop:
	sudo systemctl stop peluqueria
	sudo systemctl stop ngrok
	@echo "   ✓ servicios parados"

.PHONY: vacuum-logs
vacuum-logs:
	sudo journalctl --vacuum-time=1d
	truncate -s 0 $(LOG_DIR)/watchdog.log
	@echo "   ✓ logs vaciados"
