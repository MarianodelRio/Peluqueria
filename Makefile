# ══════════════════════════════════════════════════════════════════════════════
#  Peluquería Citas — Makefile de despliegue y operación
#
#  Uso rápido:
#    make all     →  instalación completa con nginx + DuckDNS (primera vez)
#    make update  →  desplegar cambios de código (día a día)
#
#  Configura PUBLIC_DOMAIN y ADMIN_EMAIL antes de ejecutar make all.
# ══════════════════════════════════════════════════════════════════════════════

# ── Variables — edita estas líneas según tu caso ──────────────────────────
PUBLIC_DOMAIN     := peluqueriabot.duckdns.org
ADMIN_EMAIL       := marianorio24@gmail.com
WATCHDOG_INTERVAL := 0

# ── Variables automáticas — no tocar ──────────────────────────────────────
USER        := $(shell whoami)
APP_DIR     := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
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
ExecStart=$(UVICORN) app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=peluqueria

[Install]
WantedBy=multi-user.target
endef
export PELUQUERIA_SERVICE

define NGINX_CONF
server {
    listen 80;
    server_name $(PUBLIC_DOMAIN);
    return 301 https://$$host$$request_uri;
}

server {
    listen 443 ssl;
    server_name $(PUBLIC_DOMAIN);

    ssl_certificate     /etc/letsencrypt/live/$(PUBLIC_DOMAIN)/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$(PUBLIC_DOMAIN)/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers   HIGH:!aNULL:!MD5;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $$host;
        proxy_set_header   X-Real-IP         $$remote_addr;
        proxy_set_header   X-Forwarded-For   $$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $$scheme;
        proxy_read_timeout 30s;
        proxy_buffering    off;
        client_max_body_size 512k;
    }
}
endef
export NGINX_CONF

define RESTART_SERVICE
[Unit]
Description=Reinicio nocturno del bot

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart peluqueria
ExecStartPost=/usr/bin/journalctl --rotate
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
	@echo "    make setup      Instala dependencias del sistema (nginx, certbot)"
	@echo "    make install    Crea entorno virtual e instala Python deps"
	@echo "    make services   Configura servicios systemd, SSL y watchdog"
	@echo "    make start      Arranca todos los servicios"
	@echo ""
	@echo "  OPERACIÓN DIARIA"
	@echo "    make update     Descarga cambios de código (git pull + pip)"
	@echo "    make test       Ejecuta la suite de tests (pytest)"
	@echo "    make start      Arranca o reinicia todos los servicios"
	@echo "    make status     Estado de todos los servicios"
	@echo "    make health     Comprueba /health del bot"
	@echo "    make logs       Logs del bot en tiempo real"
	@echo "    make logs-nginx     Logs de nginx en tiempo real"
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
	@echo "  ✓ Instalación completa (nginx + DuckDNS)"
	@echo "  Comprueba el estado con: make status"
	@echo "  Comprueba el bot con:    make health"
	@echo ""

# ── Comprobaciones previas ─────────────────────────────────────────────────

.PHONY: _check-env
_check-env:
	@test -f $(APP_DIR)/.env || { echo "ERROR: falta $(APP_DIR)/.env — cópialo de .env.example y rellénalo"; exit 1; }
	@test -f $(APP_DIR)/credentials.json || { echo "ERROR: falta $(APP_DIR)/credentials.json — súbelo desde tu máquina local"; exit 1; }
	@DUCKDNS_TOKEN=$$(grep -E '^DUCKDNS_TOKEN=' $(APP_DIR)/.env | cut -d= -f2); \
	test -n "$$DUCKDNS_TOKEN" || { echo "ERROR: DUCKDNS_TOKEN vacío en $(APP_DIR)/.env"; exit 1; }

# ── Dependencias del sistema ───────────────────────────────────────────────

.PHONY: setup
setup:
	@echo "→ Instalando dependencias del sistema..."
	sudo apt-get update -qq
	sudo apt-get install -y python3.11 python3.11-venv git curl nginx
	@echo "→ Instalando certbot..."
	@if ! command -v certbot >/dev/null 2>&1; then \
		sudo snap install --classic certbot; \
		sudo ln -sf /snap/bin/certbot /usr/local/bin/certbot; \
		sudo snap set certbot trust-plugin-with-root=ok; \
		sudo snap install certbot-dns-duckdns; \
		sudo snap connect certbot:plugin certbot-dns-duckdns; \
	else \
		echo "   certbot ya instalado, omitiendo"; \
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

# ── Servicios systemd ──────────────────────────────────────────────────────

.PHONY: services
services: _check-env _service-uvicorn _service-duckdns _certbot _service-nginx _service-restart _watchdog-cron
	sudo systemctl daemon-reload
	sudo systemctl enable peluqueria nginx peluqueria-restart.timer
	@echo "   ✓ servicios configurados — ejecuta 'make start' para arrancarlos"

# ── Generadores de ficheros systemd y configuración ───────────────────────

.PHONY: _service-uvicorn
_service-uvicorn:
	@echo "→ Creando peluqueria.service..."
	@printf '%s\n' "$$PELUQUERIA_SERVICE" | sudo tee /etc/systemd/system/peluqueria.service > /dev/null

.PHONY: _service-nginx
_service-nginx:
	@echo "→ Configurando nginx..."
	@printf '%s\n' "$$NGINX_CONF" | sudo tee /etc/nginx/sites-available/peluqueria > /dev/null
	@sudo ln -sf /etc/nginx/sites-available/peluqueria /etc/nginx/sites-enabled/peluqueria
	@sudo rm -f /etc/nginx/sites-enabled/default
	@sudo nginx -t
	@echo "   ✓ nginx configurado"

.PHONY: _certbot
_certbot:
	@echo "→ Emitiendo certificado SSL para $(PUBLIC_DOMAIN)..."
	@DUCKDNS_TOKEN=$$(grep -E '^DUCKDNS_TOKEN=' $(APP_DIR)/.env | cut -d= -f2); \
	sudo certbot certonly \
		--authenticator dns-duckdns \
		--dns-duckdns-token $$DUCKDNS_TOKEN \
		--dns-duckdns-propagation-seconds 60 \
		-d $(PUBLIC_DOMAIN) \
		--non-interactive \
		--agree-tos \
		--email $(ADMIN_EMAIL) \
		--keep-until-expiring
	@printf '#!/bin/sh\nsystemctl reload nginx\n' \
		| sudo tee /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh > /dev/null
	@sudo chmod +x /etc/letsencrypt/renewal-hooks/post/reload-nginx.sh
	@echo "   ✓ certificado SSL listo (renovación automática configurada)"

.PHONY: _service-duckdns
_service-duckdns:
	@echo "→ Configurando actualizador de IP DuckDNS..."
	@DUCKDNS_TOKEN=$$(grep -E '^DUCKDNS_TOKEN=' $(APP_DIR)/.env | cut -d= -f2); \
	DUCKDNS_SUBDOMAIN=$$(echo "$(PUBLIC_DOMAIN)" | cut -d. -f1); \
	if [ -n "$$DUCKDNS_TOKEN" ]; then \
		CRON_LINE="*/5 * * * * curl -s \"https://www.duckdns.org/update?domains=$$DUCKDNS_SUBDOMAIN&token=$$DUCKDNS_TOKEN&ip=\" > /dev/null"; \
		( crontab -l 2>/dev/null | grep -v "duckdns.org"; echo "$$CRON_LINE" ) | crontab -; \
		echo "   ✓ actualizador DuckDNS activo (cada 5 min)"; \
	else \
		echo "   AVISO: DUCKDNS_TOKEN no está en .env"; \
	fi

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
	@echo "── nginx ───────────────────────────────────────────────"
	@sudo systemctl status nginx --no-pager -l | head -6
	@echo ""
	@echo "── reinicio nocturno ───────────────────────────────────"
	@sudo systemctl status peluqueria-restart.timer --no-pager -l | head -5

.PHONY: health
health:
	@curl -s http://localhost:8000/health | python3 -m json.tool

.PHONY: logs
logs:
	sudo journalctl -u peluqueria -f

.PHONY: logs-nginx
logs-nginx:
	sudo journalctl -u nginx -f

.PHONY: logs-watchdog
logs-watchdog:
	tail -f $(LOG_DIR)/watchdog.log

# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: test
test:
	$(PYTEST) -q -m "not integration"

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
	@if sudo systemctl is-active --quiet nginx; then \
		sudo systemctl reload nginx; \
	else \
		sudo systemctl start nginx; \
	fi
	sudo systemctl start peluqueria-restart.timer
	@sudo systemctl is-active --quiet peluqueria \
		&& echo "   ✓ servicios arrancados" \
		|| echo "   ✗ ERROR: el bot no arrancó — ejecuta: make logs"

.PHONY: stop
stop:
	sudo systemctl stop peluqueria
	sudo systemctl stop nginx
	@echo "   ✓ servicios parados"

.PHONY: vacuum-logs
vacuum-logs:
	sudo journalctl --vacuum-time=1d
	truncate -s 0 $(LOG_DIR)/watchdog.log
	@echo "   ✓ logs vaciados"
