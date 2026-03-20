# Sistema de Citas — Peluquería

Bot de WhatsApp para gestión de citas integrado con Google Calendar.
Los clientes reservan, consultan y cancelan citas por WhatsApp. El peluquero gestiona todo desde Google Calendar.

---

## Cómo funciona

### El cliente (por WhatsApp)
1. Escribe cualquier mensaje → el bot muestra el menú principal
2. Elige **Pedir cita** → selecciona día y hora
3. Escribe su nombre → la cita queda registrada en Calendar
4. Puede consultar sus citas o cancelarlas en cualquier momento
5. Recibe un recordatorio automático ~24h antes con botones de confirmar/cancelar

### El peluquero (desde Google Calendar)
- Crea eventos con `Telefono: +34XXXXXXXXX` en la descripción → el sistema envía confirmación automática por WhatsApp
- Crea cualquier evento sin teléfono para bloquear un horario
- Usa eventos de configuración para cerrar días o cambiar horarios:

```
[CFG] CERRADO              → cierra ese día
[CFG] VACACIONES           → cierra el rango del evento
[CFG] HORARIO 10:00-13:00  → cambia el horario de ese día
```

### Procesos automáticos (scheduler en segundo plano)
| Job | Frecuencia | Descripción |
|-----|-----------|-------------|
| Sync citas manuales | Cada 5 min | Detecta citas nuevas del peluquero y envía confirmación |
| Recordatorios 24h | Cada hora | Envía recordatorio con botones confirmar/cancelar |
| Limpiar estados | Cada 10 min | Elimina conversaciones inactivas (> 30 min) |

---

## Estructura del proyecto

```
Peluqueria/
├── app/                         # Código fuente de la aplicación
│   ├── config.py                # Toda la configuración centralizada
│   ├── main.py                  # Punto de entrada FastAPI + lifespan
│   ├── handlers/
│   │   ├── webhook.py           # Endpoints GET/POST /webhook
│   │   └── conversation.py      # Máquina de estados de conversación
│   ├── services/
│   │   ├── calendar.py          # Operaciones Google Calendar API
│   │   ├── whatsapp.py          # Envío de mensajes WhatsApp Cloud API
│   │   └── scheduler.py         # Jobs automáticos (APScheduler)
│   └── utils/
│       ├── parser.py            # Parseo robusto de descripciones de eventos
│       ├── slots.py             # Generación de slots y disponibilidad
│       ├── interactive.py       # Builders de mensajes interactivos WhatsApp
│       └── messages.py          # Textos en español
│
├── tests/                       # Suite de tests (pytest)
│   ├── conftest.py              # Fixtures compartidos
│   ├── test_calendar.py
│   ├── test_conversation.py
│   ├── test_interactive.py
│   ├── test_parser.py
│   ├── test_regression.py
│   ├── test_slots.py
│   ├── test_webhook.py
│   └── test_whatsapp.py
│
├── .env.example                 # Plantilla de variables de entorno
├── .gitignore
├── pytest.ini
├── requirements.txt             # Dependencias de producción
├── requirements-dev.txt         # Dependencias de desarrollo y tests
└── README.md
```

---

## Requisitos previos

- Python 3.10+
- Cuenta en Google Cloud con **Calendar API** activada y un Service Account
- Cuenta en **Meta for Developers** con WhatsApp Cloud API configurada
- [`ngrok`](https://ngrok.com/) para exponer el servidor en desarrollo

---

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd app_peluqueria

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows

# Instalar dependencias de producción
pip install -r requirements.txt

# O instalar también las de desarrollo (tests)
pip install -r requirements-dev.txt
```

---

## Configuración

### 1. Variables de entorno

Copiar la plantilla y rellenar los valores:

```bash
cp .env.example .env
```

```ini
# .env
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxxxxx
WHATSAPP_VERIFY_TOKEN=mi_token_secreto_123
GOOGLE_CREDENTIALS_PATH=/ruta/absoluta/credentials.json
GOOGLE_CALENDAR_ID=xxxxxxxxxx@group.calendar.google.com
```

> **Importante:** `.env` y `credentials.json` están en `.gitignore`. Nunca los subas al repositorio.

### 2. Credenciales Google Calendar

1. [Google Cloud Console](https://console.cloud.google.com/) → crear proyecto → activar **Google Calendar API**
2. Crear **Service Account** → descargar JSON → guardarlo fuera del repo (ej: `~/secrets/credentials.json`)
3. En Google Calendar: crear un calendario → compartirlo con el email del Service Account (permisos de edición)
4. Copiar el **Calendar ID** desde Configuración del calendario → Integrar calendario

### 3. Credenciales WhatsApp

1. [Meta for Developers](https://developers.facebook.com/) → crear app de tipo **Business**
2. Añadir producto **WhatsApp** → configurar número de teléfono
3. Obtener **Phone Number ID** y **Access Token** permanente
4. Definir un **Verify Token** (cualquier string, ej: `mi_token_secreto_123`)

### 4. Horario base

En `app/config.py`, modificar `HORARIO_BASE` (días 0=Lunes … 6=Domingo):

```python
HORARIO_BASE = {
    0: [("10:00", "14:00"), ("16:00", "20:00")],  # Lunes
    1: [("10:00", "14:00"), ("16:00", "20:00")],  # Martes
    2: [("10:00", "14:00"), ("16:00", "20:00")],  # Miércoles
    3: [("10:00", "14:00"), ("16:00", "20:00")],  # Jueves
    4: [("10:00", "14:00"), ("16:00", "20:00")],  # Viernes
    5: [("10:00", "14:00")],                       # Sábado (solo mañana)
    # Días sin entrada = cerrado (ej: domingo)
}
```

Para cambios puntuales sin reiniciar el servidor, usa eventos `[CFG]` en Google Calendar.

---

## Arrancar el servidor

### Desarrollo (con ngrok)

```bash
# Terminal 1 — servidor
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — túnel público
ngrok http 8000
```

ngrok mostrará una URL como `https://abc123.ngrok-free.app`.

**Configurar webhook en Meta:**
1. Meta for Developers → tu app → WhatsApp → Configuración
2. **Webhook URL:** `https://abc123.ngrok-free.app/webhook`
3. **Verify Token:** el mismo valor que en `.env`
4. Suscribirse a: `messages`, `message_status`
5. Pulsar **Verificar y guardar**

### Verificar que funciona

```bash
curl http://localhost:8000/health
# {"status":"ok","calendar":"ok"}   ← todo correcto
# {"status":"degraded","calendar":"error"}  ← problema con Calendar API
```

### Producción (servidor Linux)

```bash
# Con nohup
source venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs.txt 2>&1 &
tail -f logs.txt
```

Con **systemd** — crear `/etc/systemd/system/peluqueria.service`:

```ini
[Unit]
Description=Peluqueria Citas Bot
After=network.target

[Service]
User=tu_usuario
WorkingDirectory=/ruta/a/app_peluqueria
EnvironmentFile=/ruta/a/app_peluqueria/.env
ExecStart=/ruta/a/app_peluqueria/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable peluqueria
sudo systemctl start peluqueria
sudo systemctl status peluqueria
```

---

## Tests

```bash
# Activar entorno virtual
source venv/bin/activate

# Ejecutar todos los tests
pytest

# Con cobertura
pytest --cov=app --cov-report=term-missing

# Un módulo concreto
pytest tests/test_conversation.py -v
```

Los tests no requieren credenciales reales — todas las APIs externas están mockeadas.

---

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| `{"status":"degraded"}` en /health | Calendar API inaccesible | Verificar `credentials.json` y permisos del Service Account |
| Webhook no verifica (403) | Token incorrecto o URL mal configurada | Comprobar `WHATSAPP_VERIFY_TOKEN` en `.env` y en Meta |
| Bot no responde mensajes | ngrok caído o webhook no suscrito | Reiniciar ngrok y actualizar URL en Meta |
| No llegan recordatorios | `Recordatorio: sí` ya en el evento | Normal si ya se envió; verificar que el teléfono está en la descripción |
| `ModuleNotFoundError: app` | pytest no encuentra el paquete | Asegurarse de que existe `pytest.ini` con `pythonpath = .` |
