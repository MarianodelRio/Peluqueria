# Peluquería Citas — Bot de WhatsApp

Bot de WhatsApp para gestión de citas de peluquería, integrado con Google Calendar.
Los clientes reservan, mueven y cancelan citas por WhatsApp. El peluquero gestiona todo desde Google Calendar.

No hay base de datos — Google Calendar es la única fuente de verdad.

---

## Cómo funciona

### El cliente (por WhatsApp)

1. Escribe cualquier mensaje → el bot muestra el menú principal
2. **Pedir cita** → elige servicio → elige día → elige hora → escribe nombre → cita confirmada
3. **Mover cita** → elige qué cita mover → elige nuevo servicio, día y hora → la cita anterior se cancela y se crea la nueva
4. **Cancelar cita** → elige qué cita cancelar → cancelada al momento
5. Recibe un recordatorio automático ~24h antes con botones de confirmar o cancelar

### El peluquero (desde Google Calendar)

- **Cita manual**: crea un evento con `Telefono: +34XXXXXXXXX` en la descripción → el sistema envía confirmación automática al cliente por WhatsApp
- **Bloquear horario**: crea un evento sin teléfono → bloquea esas horas sin notificar a nadie
- **Cerrar un día puntual**: evento de título `[CFG] CERRADO`
- **Cerrar un rango (vacaciones)**: evento de título `[CFG] VACACIONES`
- **Cambiar horario un día**: evento de título `[CFG] HORARIO 10:00-13:00`

### Procesos automáticos

| Job | Frecuencia | Qué hace |
|-----|-----------|---------|
| Sync citas manuales | Cada 60 min | Detecta citas del peluquero y envía confirmación al cliente |
| Recordatorios 24h | Cada 60 min | Envía recordatorio con botones confirmar/cancelar |
| Limpiar estados | Cada 10 min | Elimina conversaciones inactivas (> 30 min) |

---

## Arquitectura

```
Cliente WhatsApp
      │
      ▼
Meta (WhatsApp Cloud API)
      │  webhook HTTPS → peluqueriabot.duckdns.org
      ▼
VM Linux (Ubuntu 22.04) — Google Cloud (104.196.210.121)
  ├── nginx              (TLS :443 → localhost:8000)
  ├── FastAPI + Uvicorn  (puerto 8000, solo localhost)
  ├── APScheduler        (jobs automáticos)
  └── Watchdog cron      (comprobaciones cada 60 min)
      │
      ▼
Google Calendar (fuente de verdad)

DNS: peluqueriabot.duckdns.org → IP de la VM (DuckDNS, actualizado cada 5 min)
SSL: certificado Let's Encrypt, renovación automática cada 90 días
```

---

## Checklist de recursos previos

- [ ] **SIM del negocio** — número de teléfono real para WhatsApp Business (sin WhatsApp instalado, o que puedas desvincularlo)
- [ ] **Gmail del negocio** — cuenta Gmail específica del negocio, no la personal. Se usa para Google Cloud y Meta Business
- [ ] **Tarjeta de crédito/débito** — Google Cloud la pide para verificar identidad. El plan gratuito no cobra nada
- [ ] **Tests pasando** — ejecuta `pytest` en local antes de desplegar

---

## 1. Servicios externos

### 1.1 Google Cloud

Todo con el **Gmail del negocio**.

**Crear cuenta y proyecto**
1. Ve a [console.cloud.google.com](https://console.cloud.google.com) → inicia sesión → acepta términos → introduce tarjeta (solo verificación, no se cobra)
2. Selector de proyectos (arriba izquierda) → **Nuevo proyecto** → nombre: `peluqueria-citas` → Crear

**Activar Google Calendar API**
1. Menú izquierdo → **APIs y servicios → Biblioteca**
2. Busca `Google Calendar API` → click → **Habilitar**

**Crear Service Account**
1. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**
2. Nombre: `peluqueria-backend` → Crear y continuar → Listo
3. Click en la cuenta creada → pestaña **Claves** → **Añadir clave → JSON → Crear**
4. Se descarga un JSON. Renómbralo `credentials.json` y guárdalo — **solo se puede descargar una vez**

> ⚠️ `credentials.json` es la clave privada del bot. Nunca lo subas a git.

Anota el campo `client_email` del JSON (ej: `peluqueria-backend@peluqueria-citas.iam.gserviceaccount.com`).

**Crear el calendario y compartirlo**
1. [calendar.google.com](https://calendar.google.com) → menú izquierdo → junto a "Otros calendarios" → **+** → **Crear nuevo calendario** → nombre: `Citas Peluquería`
2. En el calendario creado → tres puntos → **Configuración y uso compartido**
3. **Compartir con personas específicas → Añadir personas** → pega el `client_email` → permisos: **Realizar cambios en eventos** → Enviar
4. En la misma página → **Integrar calendario** → copia el **ID del calendario** (ej: `c_abc123@group.calendar.google.com`)

---

### 1.2 Meta / WhatsApp Business

Todo con el **Gmail del negocio**.

**Crear Meta Business Account**
1. Ve a [business.facebook.com](https://business.facebook.com) → Crear cuenta → nombre del negocio → email

**Crear app de desarrollador**
1. Ve a [developers.facebook.com](https://developers.facebook.com) → **Mis apps → Crear app**
2. Tipo: **Business** → nombre: `Peluqueria Citas` → vincula con tu Meta Business Account

**Añadir WhatsApp y registrar el número**
1. En la app → **Añadir productos → WhatsApp → Configurar**
2. **Gestión de API → Números de teléfono → Añadir número** → introduce la SIM del negocio → introduce el código SMS

**Obtener credenciales**
En **WhatsApp → Configuración de la API**:
- **Phone Number ID** → `WHATSAPP_PHONE_NUMBER_ID` en el `.env`
- En Configuración → Básica → **App Secret** → `WHATSAPP_APP_SECRET` en el `.env`

**Crear token permanente** (el token de pruebas expira en 24h)
1. Ve a [business.facebook.com/settings](https://business.facebook.com/settings)
2. **Usuarios → Usuarios del sistema → Añadir** → nombre: `peluqueria-bot`, rol: **Administrador**
3. Click en el usuario → **Añadir activos** → selecciona tu app → permisos: `whatsapp_business_messaging` y `whatsapp_business_management`
4. **Generar token → Sin expiración** → copia el token → `WHATSAPP_ACCESS_TOKEN` en el `.env`

---

### 1.3 DuckDNS

1. Entra en [duckdns.org](https://www.duckdns.org) con Google o GitHub
2. Crea un subdominio (ej: `peluqueriabot`) → queda fijo como `peluqueriabot.duckdns.org`
3. Copia el **token** que aparece en la página principal → `DUCKDNS_TOKEN` en el `.env`
4. Apunta el dominio a la IP de tu VM ejecutando desde la VM: `curl "https://www.duckdns.org/update?domains=peluqueriabot&token=TU_TOKEN&ip="`

> DuckDNS es gratuito y permanente. El subdominio no caduca. El bot actualiza la IP automáticamente cada 5 minutos vía cron.

---

## 2. config.yaml — configuración del negocio

El fichero `config.yaml` en la raíz contiene toda la configuración del negocio. Se edita directamente en texto y el bot lo lee al arrancar. Cualquier cambio requiere reiniciar el bot (`make start`).

```yaml
negocio:
  nombre: "Mi Peluquería"
  telefono_contacto: "+34 600 000 000"  # número del negocio (para el QR)
  admin_phone: "34600000000"             # recibe alertas del watchdog y puede usar /estado

horario:
  lunes:
    - ["10:00", "14:00"]
    - ["17:00", "21:00"]
  martes:
    - ["10:00", "14:00"]
    - ["17:00", "21:00"]
  # días no listados = cerrado (ej: domingo)

ventana_busqueda_dias: 14  # días hacia adelante que se ofrecen al cliente

servicios:
  corte:
    nombre: "Corte de pelo"
    precio: 10
    duracion_min: 30           # tiempo activo del peluquero (duración del evento en Calendar)
    presencia_cliente_min: 30  # tiempo total del cliente en el local
  # máximo 9 servicios (límite de WhatsApp)

envios:
  recordatorios: false    # recordatorios automáticos 24h antes
  confirmaciones: false   # confirmaciones de citas manuales del peluquero

recordatorio_horas_antes:
  desde: 23
  hasta: 25  # envía si la cita es entre 23h y 25h desde ahora

# Evento especial — añade una opción extra "Cita [nombre]" en el menú principal
evento:
  activo: false
  nombre: "Navidad 2026"
  dias:
    "2026-12-20": [["10:00", "14:00"]]
```

---

## 3. Templates de WhatsApp

Los templates son mensajes pre-aprobados por Meta para contactar al cliente fuera de la ventana de 24h. Son necesarios para que funcionen los recordatorios y las confirmaciones de citas manuales.

**Dónde crearlos**: Meta Business Suite → Cuenta de WhatsApp → Herramientas → Plantillas de mensajes → Crear plantilla

> ⚠️ Los templates tardan entre 1h y 48h en aprobarse. Créalos todos a la vez antes de necesitarlos.

---

### Template 1 — `confirmacion_cita`

| Campo | Valor |
|---|---|
| Nombre | `confirmacion_cita` |
| Categoría | `Utility` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
Hola {{1}}, tu cita ha sido confirmada para el {{2}} a las {{3}}.

Si necesitas cancelarla, pulsa el botón.
```
**Botón de respuesta rápida:** `Cancelar cita`

---

### Template 2 — `recordatorio_cita`

| Campo | Valor |
|---|---|
| Nombre | `recordatorio_cita` |
| Categoría | `Utility` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
Recuerda que tienes cita el {{1}} a las {{2}}. ¿Confirmas tu asistencia?
```
**Botón 1 respuesta rápida:** `Confirmar`
**Botón 2 respuesta rápida:** `Cancelar`

---

### Template 3 — `alerta_sistema`

| Campo | Valor |
|---|---|
| Nombre | `alerta_sistema` |
| Categoría | `Utility` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
⚠️ Alerta del sistema: {{1}}
Fecha: {{2}}
Detalle: {{3}}
```
Sin botones.

---

## 4. Desarrollo local

Flujo para desarrollar y testear en tu máquina, sin usar el Makefile.

### 4.1 Preparar el entorno

```bash
git clone <repo-url>
cd Peluqueria

python3.11 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 4.2 Configurar el .env

```bash
cp .env.example .env
# edita .env con tus credenciales reales
```

Variables obligatorias:
```ini
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxxxxx
WHATSAPP_VERIFY_TOKEN=cualquier_string_secreto
WHATSAPP_APP_SECRET=abc123def456
GOOGLE_CALENDAR_ID=c_abc123@group.calendar.google.com
GOOGLE_CREDENTIALS_PATH=./credentials.json
ADMIN_PHONE=34612345678
PUBLIC_DOMAIN=peluqueriabot.duckdns.org
DUCKDNS_TOKEN=tu_token_de_duckdns
```

Coloca `credentials.json` en la raíz del proyecto.

### 4.3 Arrancar

```bash
# Terminal 1 — bot en modo desarrollo
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

> En desarrollo local no hay nginx. Para probar webhooks de Meta, puedes usar cualquier túnel temporal (ngrok free tier, cloudflare quick tunnel) y actualizar la URL en Meta Developer Console. En producción el túnel lo gestiona nginx en la VM de GCP.

### 4.4 Configurar el webhook en Meta (primera vez)

1. Meta for Developers → tu app → WhatsApp → Configuración → Webhook → **Editar**
2. **URL del webhook**: `https://peluqueriabot.duckdns.org/webhook` (producción) o tu túnel temporal (desarrollo)
3. **Token de verificación**: el valor de `WHATSAPP_VERIFY_TOKEN` en el `.env`
4. **Verificar y guardar** → en **Campos de webhook** activa `messages` → Suscribirse

Comprueba que funciona:
```bash
curl http://localhost:8000/health
# {"status":"ok","calendar":"ok",...}
```

### 4.5 Tests

Los tests no requieren credenciales reales — todas las APIs externas están mockeadas.

```bash
pytest                                    # todos los tests
pytest --cov=app --cov-report=term-missing  # con cobertura
pytest tests/test_conversation.py -v      # un módulo concreto
```

---

## 5. Despliegue en VM (producción)

### 5.1 Crear la VM en Google Cloud

En **Compute Engine → Instancias de VM → Crear instancia**:

| Campo | Valor |
|---|---|
| Nombre | `peluqueria-vm` |
| Región | `us-east1` (free tier perpetuo) |
| Tipo de máquina | `e2-micro` (0.25 vCPU, 1 GB RAM) |
| Sistema operativo | Ubuntu 22.04 LTS |
| Disco | 30 GB estándar |

En **Opciones avanzadas → Redes**: marca **Permitir tráfico HTTP** y **Permitir tráfico HTTPS**.

> No es necesario reservar IP estática — DuckDNS actualiza automáticamente el dominio si la IP cambia. La IP solo cambia si apagas y reenciendes la VM.

### 5.2 Preparar la VM

Conecta por SSH (botón SSH en la consola de Google Cloud).

```bash
sudo apt install -y make
git clone https://github.com/TU_USUARIO/TU_REPO.git ~/app
cd ~/app
```

Sube los ficheros sensibles desde tu máquina local:
```bash
gcloud compute scp .env credentials.json NOMBRE_VM:~/app/ --zone=us-east1-b --project=NOMBRE_PROYECTO
```

En la VM:
```bash
chmod 600 .env credentials.json
```

### 5.3 Instalar y arrancar

```bash
make setup      # instala Python 3.11, git, curl, nginx, certbot y crea /var/log/peluqueria
make install    # crea el entorno virtual e instala dependencias Python
make services   # configura systemd, emite certificado SSL, activa DuckDNS y watchdog
make start      # arranca el bot y nginx
```

Verifica:
```bash
make status   # todos los servicios deben mostrar "active (running)"
make health   # {"status":"ok","calendar":"ok",...}
```

### 5.4 Conectar con Meta

Con el bot corriendo y nginx activo:
1. Meta for Developers → tu app → WhatsApp → Configuración → Webhook → **Editar**
2. **URL**: `https://peluqueriabot.duckdns.org/webhook`
3. **Token de verificación**: valor de `WHATSAPP_VERIFY_TOKEN` en el `.env`
4. **Verificar y guardar** → activa `messages` → Suscribirse

---

## 6. Operación diaria

```bash
make update          # git pull + pip install (descarga cambios)
make test            # ejecuta los tests
make start           # arranca o reinicia todos los servicios
make status          # estado de todos los servicios
make health          # comprueba conectividad
make logs            # logs del bot en tiempo real
make logs-nginx      # logs de nginx en tiempo real
make logs-watchdog   # logs del watchdog
make stop            # para todos los servicios
make qr              # genera qr_cita.png con el enlace de WhatsApp del negocio
```

**Flujo de despliegue de cambios:**
```bash
make update   # descarga los cambios
make test     # verifica que todo sigue funcionando
make start    # reinicia el bot con el nuevo código
```

**Watchdog automático** — corre cada 60 min vía cron y comprueba:
- `/health` del bot — caídas y fallos de Calendar
- Dominio público (`PUBLIC_DOMAIN`) — accesible desde el exterior vía nginx
- RAM > 90% y disco > 90%
- Spike de errores en `/metrics`

Si detecta un problema envía un WhatsApp al `ADMIN_PHONE` usando el template `alerta_sistema` (cooldown de 30 min entre alertas del mismo tipo).

**Reinicio nocturno** — `peluqueria-restart.timer` reinicia el bot cada noche a las 4:00 AM. Limpia memoria, conexiones colgadas y estados de conversación.

---

## 7. Estructura del proyecto

```
Peluqueria/
├── app/
│   ├── config.py               # Carga y valida config.yaml + variables de entorno
│   ├── main.py                 # FastAPI app + lifespan (scheduler) + /health + /metrics
│   ├── handlers/
│   │   ├── webhook.py          # GET/POST /webhook — HMAC, rate limiting, dedup
│   │   └── conversation.py     # Máquina de estados: reserva, mover, cancelar
│   ├── services/
│   │   ├── calendar/           # Todas las operaciones con Google Calendar
│   │   │   ├── service.py      # API pública: reservar, cancelar, mover, slots
│   │   │   ├── queries.py      # Lecturas de Calendar
│   │   │   ├── mutations.py    # Escrituras de Calendar
│   │   │   ├── engine.py       # Lógica de slots y disponibilidad
│   │   │   ├── caches.py       # Caché de slots (TTL 30s)
│   │   │   ├── locks.py        # Locks por slot (evita doble reserva)
│   │   │   ├── client.py       # Cliente HTTP de Google Calendar API
│   │   │   └── repository.py   # Acceso directo a eventos
│   │   ├── whatsapp.py         # send_text_message, send_interactive, send_template
│   │   └── scheduler.py        # Jobs APScheduler: sync, recordatorios, limpieza
│   └── utils/
│       ├── interactive.py      # Builders de mensajes interactivos WhatsApp
│       ├── messages.py         # Textos en español
│       ├── parser.py           # Parseo de descripciones de eventos de Calendar
│       ├── slots.py            # Generación y filtrado de slots horarios
│       ├── admin.py            # Informe de estado para el comando /estado
│       ├── metrics.py          # Contadores en memoria
│       ├── dedup.py            # Deduplicación de mensajes entrantes
│       ├── rate_limiter.py     # Rate limiting por IP y por teléfono
│       └── security.py         # Enmascarado de teléfonos en logs
│
├── tests/                      # Suite de tests — todas las APIs mockeadas
│
├── config.yaml                 # Configuración del negocio (horario, servicios, etc.)
├── watchdog.py                 # Monitorización (cron cada 60 min, configurable)
├── generar_qr.py               # Genera qr_cita.png con el enlace de WhatsApp
├── Makefile                    # Automatización de instalación y operación
├── .env.example                # Plantilla de variables de entorno
├── requirements.txt            # Dependencias Python
└── pytest.ini                  # Configuración de pytest
```

---

## 8. Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| `{"status":"degraded"}` en /health | Calendar API inaccesible | Verificar `credentials.json` y permisos del Service Account |
| Bot no responde mensajes | nginx caído o webhook no suscrito | `make status` → `make start` → verificar URL en Meta |
| Webhook no verifica (403) | Token incorrecto o URL mal configurada | Comprobar `WHATSAPP_VERIFY_TOKEN` en `.env` y en Meta |
| HTTP 401 en logs de WhatsApp | Token de acceso expirado | Generar nuevo token en Meta → actualizar `.env` → `make start` |
| No llegan recordatorios | Templates no aprobados o `envios.recordatorios: false` | Verificar estado en Meta Business Suite y activar en `config.yaml` |
| `ModuleNotFoundError: app` en pytest | pytest no encuentra el paquete | Verificar que existe `pytest.ini` con `pythonpath = .` |
| Certificado SSL expirado | Renovación automática fallida | `sudo certbot renew --dry-run`; revisar hook en `/etc/letsencrypt/renewal-hooks/post/` |
