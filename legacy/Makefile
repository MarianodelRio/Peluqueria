# ══════════════════════════════════════════════════════════════════════════════
#  Peluquería Citas — Makefile de despliegue y operación
#
#  Uso rápido:
#    make all          →  instalación completa con ngrok (primera vez)
#    make all-nginx    →  instalación completa con nginx (primera vez)
#    make update       →  desplegar cambios de código (día a día)
#
#  Configura NGROK_DOMAIN antes de ejecutar make all (modo ngrok).
#  Configura SERVER_IP   antes de ejecutar make all-nginx (modo nginx).
# ══════════════════════════════════════════════════════════════════════════════

# ── Variables — edita estas dos líneas según tu caso ──────────────────────
NGROK_DOMAIN := tu-dominio.ngrok-free.app
SERVER_IP    := 0.0.0.0

# ── Variables automáticas — no tocar ──────────────────────────────────────
USER        := $(shell whoami)
APP_DIR     := /home/$(USER)/app
VENV        := $(APP_DIR)/venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
LOG_DIR     := /var/log/peluqueria

.DEFAULT_GOAL := help

# ══════════════════════════════════════════════════════════════════════════════
#  AYUDA
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: help
help:
	@echo ""
	@echo "  Peluquería Citas — comandos disponibles"
	@echo ""
	@echo "  PRIMERA INSTALACIÓN"
	@echo "    make all            Instalación completa con ngrok"
	@echo "    make all-nginx      Instalación completa con nginx"
	@echo ""
	@echo "  OPERACIÓN DIARIA"
	@echo "    make update         git pull + pip install + restart"
	@echo "    make status         Estado de todos los servicios"
	@echo "    make health         Comprueba /health del bot"
	@echo "    make logs           Logs del bot en tiempo real"
	@echo "    make logs-ngrok     Logs de ngrok en tiempo real"
	@echo "    make logs-watchdog  Logs del watchdog"
	@echo ""
	@echo "  CONTROL DE SERVICIOS"
	@echo "    make start          Arranca todos los servicios"
	@echo "    make stop           Para todos los servicios"
	@echo "    make restart        Reinicia todos los servicios"
	@echo ""
	@echo "  MIGRACIÓN ngrok → nginx"
	@echo "    make switch-nginx   Instala nginx, para ngrok, configura SSL"
	@echo ""

# ══════════════════════════════════════════════════════════════════════════════
#  PRIMERA INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: all
all: _check-env setup install _services-ngrok watchdog
	@echo ""
	@echo "  ✓ Instalación completa (modo ngrok)"
	@echo "  Comprueba el estado con: make status"
	@echo "  Comprueba el bot con:    make health"
	@echo ""

.PHONY: all-nginx
all-nginx: _check-env setup install _services-nginx watchdog
	@echo ""
	@echo "  ✓ Instalación completa (modo nginx)"
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

# ── Servicios systemd — modo ngrok ────────────────────────────────────────

.PHONY: _services-ngrok
_services-ngrok: _service-uvicorn _service-ngrok _service-restart
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
	sudo systemctl start peluqueria
	@sleep 3
	sudo systemctl start ngrok
	sudo systemctl start peluqueria-restart.timer
	@echo "   ✓ servicios ngrok activos"

# ── Servicios systemd — modo nginx ────────────────────────────────────────

.PHONY: _services-nginx
_services-nginx: _service-uvicorn _service-restart _nginx-config
	sudo systemctl daemon-reload
	sudo systemctl enable peluqueria nginx peluqueria-restart.timer
	sudo systemctl start peluqueria nginx
	sudo systemctl start peluqueria-restart.timer
	@echo "   ✓ servicios nginx activos"

# ── Generadores de ficheros systemd ───────────────────────────────────────

.PHONY: _service-uvicorn
_service-uvicorn:
	@echo "→ Creando peluqueria.service..."
	@sudo tee /etc/systemd/system/peluqueria.service > /dev/null <<EOF
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
EOF

.PHONY: _service-ngrok
_service-ngrok:
	@echo "→ Creando ngrok.service..."
	@sudo tee /etc/systemd/system/ngrok.service > /dev/null <<EOF
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
EOF

.PHONY: _service-restart
_service-restart:
	@echo "→ Creando peluqueria-restart.service y timer..."
	@sudo tee /etc/systemd/system/peluqueria-restart.service > /dev/null <<EOF
[Unit]
Description=Reinicio nocturno del bot

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart peluqueria
EOF
	@sudo tee /etc/systemd/system/peluqueria-restart.timer > /dev/null <<EOF
[Unit]
Description=Reinicia el bot cada noche a las 4:00 AM

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── Nginx ──────────────────────────────────────────────────────────────────

.PHONY: _nginx-config
_nginx-config:
	@echo "→ Instalando nginx y generando certificado SSL..."
	sudo apt-get install -y nginx openssl
	sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
		-keyout /etc/ssl/private/peluqueria.key \
		-out /etc/ssl/certs/peluqueria.crt \
		-subj "/CN=$(SERVER_IP)" 2>/dev/null
	@sudo tee /etc/nginx/sites-available/peluqueria > /dev/null <<EOF
server {
    listen 443 ssl;
    server_name $(SERVER_IP);
    ssl_certificate     /etc/ssl/certs/peluqueria.crt;
    ssl_certificate_key /etc/ssl/private/peluqueria.key;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$$host;
        proxy_set_header X-Real-IP \$$remote_addr;
        proxy_set_header X-Forwarded-For \$$proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }
}
server {
    listen 80;
    server_name $(SERVER_IP);
    return 301 https://\$$host\$$request_uri;
}
EOF
	sudo ln -sf /etc/nginx/sites-available/peluqueria /etc/nginx/sites-enabled/
	sudo rm -f /etc/nginx/sites-enabled/default
	sudo nginx -t
	@echo "   ✓ nginx configurado"

# ── Watchdog cron ──────────────────────────────────────────────────────────

.PHONY: watchdog
watchdog:
	@echo "→ Configurando cron del watchdog..."
	@CRON_LINE="*/5 * * * * cd $(APP_DIR) && $(PYTHON) watchdog.py >> $(LOG_DIR)/watchdog.log 2>&1"; \
	( crontab -l 2>/dev/null | grep -v watchdog.py; echo "$$CRON_LINE" ) | crontab -
	@echo "   ✓ watchdog activo (cada 5 minutos)"

# ══════════════════════════════════════════════════════════════════════════════
#  OPERACIÓN DIARIA
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: update
update:
	@echo "→ Desplegando cambios..."
	cd $(APP_DIR) && git pull
	$(PIP) install -r $(APP_DIR)/requirements.txt -q
	sudo systemctl restart peluqueria
	@sleep 2
	@sudo systemctl is-active --quiet peluqueria \
		&& echo "   ✓ bot reiniciado correctamente" \
		|| echo "   ✗ ERROR: el bot no arrancó — ejecuta: make logs"

.PHONY: status
status:
	@echo "── peluqueria ──────────────────────────────────────────"
	@sudo systemctl status peluqueria --no-pager -l | head -8
	@echo ""
	@echo "── ngrok / nginx ───────────────────────────────────────"
	@sudo systemctl status ngrok --no-pager -l 2>/dev/null | head -6 \
		|| sudo systemctl status nginx --no-pager -l 2>/dev/null | head -6 \
		|| echo "   ningún túnel activo"
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
#  CONTROL DE SERVICIOS
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: start
start:
	sudo systemctl start peluqueria
	@sleep 2
	sudo systemctl start ngrok 2>/dev/null || sudo systemctl start nginx 2>/dev/null || true
	@echo "   ✓ servicios arrancados"

.PHONY: stop
stop:
	sudo systemctl stop peluqueria
	sudo systemctl stop ngrok 2>/dev/null || sudo systemctl stop nginx 2>/dev/null || true
	@echo "   ✓ servicios parados"

.PHONY: restart
restart:
	sudo systemctl restart peluqueria
	@sleep 2
	sudo systemctl restart ngrok 2>/dev/null || sudo systemctl restart nginx 2>/dev/null || true
	@echo "   ✓ servicios reiniciados"

# ══════════════════════════════════════════════════════════════════════════════
#  MIGRACIÓN ngrok → nginx
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: switch-nginx
switch-nginx: _nginx-config _service-restart
	@echo "→ Parando ngrok y activando nginx..."
	sudo systemctl stop ngrok 2>/dev/null || true
	sudo systemctl disable ngrok 2>/dev/null || true
	sudo systemctl daemon-reload
	sudo systemctl enable nginx
	sudo systemctl restart nginx
	sudo systemctl restart peluqueria-restart.timer
	@echo ""
	@echo "   ✓ Migración completada"
	@echo "   Ahora actualiza la URL del webhook en Meta:"
	@echo "   https://$(SERVER_IP)/webhook"
	@echo ""
