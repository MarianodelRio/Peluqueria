# Guía de Despliegue — Peluquería Citas Bot

## ¿Qué es esto?

Un bot de WhatsApp que permite a los clientes de una peluquería reservar, consultar y cancelar citas directamente desde WhatsApp. El peluquero gestiona su agenda en Google Calendar: cada cita que hace el bot aparece ahí, y las que crea manualmente el peluquero se confirman automáticamente al cliente por WhatsApp.

No hay base de datos ni panel de administración. Google Calendar es la única fuente de verdad.

### Arquitectura

```
Cliente WhatsApp
      │
      ▼
Meta (WhatsApp Cloud API)
      │  webhook HTTPS
      ▼
VM Linux (Ubuntu 22.04) — Google Cloud
  ├── FastAPI + Uvicorn  (puerto 8000, solo localhost)
  ├── APScheduler        (jobs cada 5-60 min)
  ├── Túnel HTTPS        (ngrok o nginx → ver opciones)
  └── Watchdog cron      (comprobaciones cada 5 min)
      │
      ▼
Google Calendar (fuente de verdad)
```

### Dos opciones de túnel HTTPS

Meta exige HTTPS para el webhook. Tienes dos opciones:

| | Opción A — ngrok | Opción B — nginx |
|---|---|---|
| **Cuándo usarla** | Inicio rápido, pruebas, cuenta Meta bloqueada | Producción estable con IP fija |
| **Requisito extra** | Cuenta ngrok gratis con dominio estático | IP estática en la VM |
| **URL fija** | Sí (dominio estático) | Sí (IP fija) |
| **Comando de instalación** | `make all` | `make all-nginx` |

Puedes empezar con ngrok y migrar a nginx en un comando cuando quieras (`make switch-nginx`).

---

## Checklist de recursos previos

Antes de empezar necesitas tener esto listo:

- [ ] **SIM del negocio** — número de teléfono real para WhatsApp Business (que no tenga ya WhatsApp instalado, o que puedas desvincularlo)
- [ ] **Email del negocio** — un Gmail específico del negocio, no el personal. Se usará para Google Cloud y Meta Business
- [ ] **Tarjeta de crédito/débito** — Google Cloud la pide para verificar identidad. El plan free no cobra nada
- [ ] **Código funcionando en local** — `pytest` debe pasar sin errores antes de desplegar

---

## PARTE 1 — Servicios externos

---

## 1. Google Cloud

Todo desde el navegador con el **email del negocio**.

### 1.1 Crear cuenta

1. Ve a [console.cloud.google.com](https://console.cloud.google.com)
2. Inicia sesión con el email del negocio
3. Acepta los términos
4. Cuando pida tarjeta: introdúcela. No se cobra nada por el free tier. Es solo verificación de identidad

### 1.2 Crear proyecto

1. Arriba a la izquierda, click en el selector de proyectos → **Nuevo proyecto**
2. Nombre: `peluqueria-citas`
3. Click en **Crear**
4. Asegúrate de que el proyecto `peluqueria-citas` está seleccionado en el menú superior

### 1.3 Activar la Google Calendar API

1. Menú izquierdo → **APIs y servicios → Biblioteca**
2. Busca `Google Calendar API`
3. Click en el resultado → **Habilitar**

### 1.4 Crear Service Account (cuenta de servicio)

Es la "cuenta robot" que el backend usa para leer y escribir en Google Calendar.

1. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**
2. Nombre: `peluqueria-backend`
3. ID de cuenta de servicio: se rellena solo
4. Click en **Crear y continuar**
5. En "Rol": selecciona **Editor** (o déjalo vacío, no es necesario para Calendar)
6. Click en **Listo**

### 1.5 Descargar credentials.json

1. En la página de Credenciales, busca la cuenta de servicio recién creada
2. Click en el nombre → pestaña **Claves**
3. **Añadir clave → Crear clave nueva → JSON → Crear**
4. Se descarga un fichero JSON. **Guárdalo bien — solo se puede descargar una vez**
5. Renómbralo a `credentials.json`

> ⚠️ **CRÍTICO**: Este fichero contiene la clave privada de tu cuenta de servicio. No lo subas nunca a git. No lo compartas. Trátalo como una contraseña.

Anota el campo `client_email` del JSON. Lo necesitarás en el paso 1.7:
```
peluqueria-backend@peluqueria-citas.iam.gserviceaccount.com
```

### 1.6 Crear el calendario en Google Calendar

1. Ve a [calendar.google.com](https://calendar.google.com) con el email del negocio
2. Menú izquierdo → junto a "Otros calendarios" → click en **+**
3. **Crear nuevo calendario**
4. Nombre: `Citas Peluquería`
5. Click en **Crear calendario**

### 1.7 Compartir el calendario con la Service Account

Esto es lo que permite al backend leer y escribir citas.

1. En Google Calendar, busca el calendario recién creado en el menú izquierdo
2. Click en los tres puntos → **Configuración y uso compartido**
3. Baja hasta **Compartir con personas específicas → Añadir personas**
4. Pega el `client_email` del paso 1.5
5. Permisos: **Realizar cambios en eventos**
6. Click en **Enviar**

### 1.8 Obtener el Calendar ID

1. En la misma página de configuración del calendario
2. Baja hasta **Integrar calendario**
3. Copia el **ID del calendario**:
   ```
   c_abc123def456@group.calendar.google.com
   ```
4. Guárdalo para el `.env`

---

## 2. Meta / WhatsApp Business

Todo desde el navegador con el **email del negocio**.

### 2.1 Crear cuenta Meta Business

1. Ve a [business.facebook.com](https://business.facebook.com)
2. Crea una cuenta con el email del negocio
3. Nombre del negocio: el nombre real de la peluquería

### 2.2 Crear app de desarrollador

1. Ve a [developers.facebook.com](https://developers.facebook.com)
2. **Mis apps → Crear app**
3. Tipo: **Business**
4. Nombre de la app: `Peluqueria Citas`
5. Vincula con tu cuenta Business

### 2.3 Añadir WhatsApp a la app

1. En el panel de la app → **Añadir productos → WhatsApp → Configurar**
2. Sigue los pasos para vincular con tu cuenta Business

### 2.4 Añadir el número de teléfono

1. **WhatsApp → Gestión de API → Números de teléfono → Añadir número**
2. Introduce el número de la SIM del negocio
3. Recibirás un SMS con un código de verificación — introdúcelo

### 2.5 Obtener las credenciales

En **WhatsApp → Configuración de la API**:

- **Phone Number ID** → es el `WHATSAPP_PHONE_NUMBER_ID` del `.env`
- **App Secret** → en Configuración → Básica → App Secret (botón "Mostrar") → es el `WHATSAPP_APP_SECRET`

### 2.6 Crear token permanente

El token temporal de pruebas expira en 24h. Para producción necesitas uno sin expiración:

1. Ve a [business.facebook.com/settings](https://business.facebook.com/settings)
2. **Usuarios → Usuarios del sistema → Añadir**
3. Nombre: `peluqueria-bot`, Rol: **Administrador**
4. Click en el usuario creado → **Añadir activos**
5. Selecciona tu app → permisos: `whatsapp_business_messaging` y `whatsapp_business_management`
6. **Generar token nuevo → Sin expiración**
7. Copia el token → es el `WHATSAPP_ACCESS_TOKEN` del `.env`

---

## 3. ngrok (solo si usas Opción A)

### 3.1 Crear cuenta y reclamar dominio estático

1. Crea cuenta en [ngrok.com](https://ngrok.com) (plan gratuito)
2. En el dashboard: **Domains → New Domain**
3. Reclama un dominio estático gratuito (ej: `mi-peluqueria.ngrok-free.app`)
4. Este dominio no cambiará nunca — es el que irá en el webhook de Meta

> ⚠️ Es importante reclamar el dominio estático **antes** de configurar el webhook en Meta, porque si usas una URL temporal y ngrok se reinicia, la URL cambia y el bot deja de funcionar.

### 3.2 Copiar el auth token

En el dashboard de ngrok: **Your Authtoken** → cópialo. Lo necesitarás en el `.env`.

---

## PARTE 2 — Infraestructura

---

## 4. Crear la VM en Google Cloud

### 4.1 Crear la instancia

En Google Cloud Console → **Compute Engine → Instancias de VM → Crear instancia**:

| Campo | Valor |
|---|---|
| Nombre | `peluqueria-vm` |
| Región | `us-east1` (South Carolina) |
| Zona | `us-east1-b` |
| Tipo de máquina | `e2-micro` (0.25 vCPU, 1 GB RAM) |
| Sistema operativo | Ubuntu 22.04 LTS |
| Disco de arranque | 30 GB estándar |

> **Por qué us-east1**: es la única región del free tier perpetuo de Google Cloud. Europa no es gratuita. La latencia adicional es irrelevante para este sistema.

### 4.2 Configurar red y firewall

En la misma pantalla → **Opciones avanzadas → Redes**:

- Marca **"Permitir tráfico HTTP"**
- Marca **"Permitir tráfico HTTPS"**

Esto abre los puertos 80 y 443. El puerto 8000 de uvicorn **no se abre directamente** — solo es accesible desde localhost a través del túnel.

### 4.3 Reservar IP externa estática

Sin esto la IP pública cambia al reiniciar la VM:

1. Menú izquierdo → **Red de VPC → Direcciones IP externas**
2. Busca la IP de tu instancia → click en **Estática**
3. Ponle nombre: `peluqueria-ip`
4. Confirma

Anota esta IP. La necesitarás para el webhook de Meta (modo nginx) y para conectarte por SSH.

### 4.4 Conectarte por SSH

Desde Google Cloud Console: click en **SSH** junto a tu VM.

O desde tu ordenador (más cómodo para el día a día):
```bash
gcloud compute ssh peluqueria-vm --zone=us-east1-b
```

---

## 5. Preparar la VM

Dentro de la VM, actualiza el sistema e instala `make` (necesario para el Makefile):

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y make
```

El Makefile instalará el resto de dependencias automáticamente.

---

## PARTE 3 — Despliegue del código

---

## 6. Clonar y configurar

### 6.1 Clonar el repositorio

```bash
git clone https://github.com/TU_USUARIO/TU_REPO.git ~/app
cd ~/app
```

### 6.2 Configurar el Makefile

Abre el Makefile y edita las dos variables al principio según tu caso:

```bash
nano ~/app/Makefile
```

```makefile
NGROK_DOMAIN := tu-dominio.ngrok-free.app   # tu dominio estático de ngrok
SERVER_IP    := 34.xxx.xxx.xxx              # tu IP estática (para modo nginx)
```

### 6.3 Crear el fichero .env

```bash
cp ~/app/.env.example ~/app/.env
nano ~/app/.env
chmod 600 ~/app/.env
```

Rellena todos los valores. Los obligatorios:

```ini
# WhatsApp
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxxxxx...
WHATSAPP_VERIFY_TOKEN=peluqueria_webhook_2026
WHATSAPP_APP_SECRET=abc123def456...

# Google Calendar
GOOGLE_CALENDAR_ID=c_abc123@group.calendar.google.com
GOOGLE_CREDENTIALS_PATH=/home/TU_USUARIO/app/credentials.json

# Admin (recibe alertas del watchdog)
ADMIN_PHONE=34612345678

# Logs
LOG_LEVEL=INFO
LOG_FILE=/var/log/peluqueria/app.log
```

Si usas ngrok (Opción A), añade también:
```ini
NGROK_DOMAIN=tu-dominio.ngrok-free.app
NGROK_TOKEN=tu_auth_token_de_ngrok
```

> `WHATSAPP_VERIFY_TOKEN` puede ser cualquier cadena que tú elijas. La usarás en el siguiente paso al configurar el webhook en Meta.

### 6.4 Subir credentials.json

Desde tu **máquina local**:

```bash
gcloud compute scp ~/Downloads/credentials.json \
  TU_USUARIO@peluqueria-vm:~/app/credentials.json \
  --zone=us-east1-b
```

En la VM:
```bash
chmod 600 ~/app/credentials.json
```

---

## 7. Instalar

Desde `~/app`, elige una opción según tu túnel:

```bash
# Opción A — ngrok (recomendado para empezar)
make all

# Opción B — nginx (producción con IP estática)
make all-nginx
```

`make all` ejecuta en orden:
1. `apt install` Python 3.11, git, ngrok
2. Crea el directorio de logs `/var/log/peluqueria/`
3. Crea el entorno virtual e instala dependencias Python
4. Genera e instala los servicios systemd (`peluqueria.service`, `ngrok.service`, `peluqueria-restart.timer`)
5. Arranca los servicios
6. Configura el watchdog en cron (cada 5 minutos)

Al terminar, verifica que todo arrancó:

```bash
make status
```

Debes ver `active (running)` en verde para el bot y el túnel.

---

## 8. Verificar el bot

```bash
# Comprueba que el bot responde y Calendar está conectado
make health
# → {"status":"ok","calendar":"ok",...}

# Logs en tiempo real
make logs
```

Manda un WhatsApp al número del negocio desde tu móvil. En los logs debe aparecer:
```
[WEBHOOK] text from ****1234: hola
[WA] interactive(button) → ****1234
```

Si no aparece nada en los logs, el webhook aún no está configurado en Meta (paso siguiente).

---

## PARTE 4 — Conectar con Meta

---

## 9. Configurar el webhook en Meta

Con el bot corriendo y el túnel activo:

1. Ve a **Meta for Developers → tu app → WhatsApp → Configuración → Webhook → Editar**
2. Introduce:

| Campo | Valor |
|---|---|
| URL del webhook | `https://TU_DOMINIO_NGROK/webhook` (Opción A) o `https://TU_IP/webhook` (Opción B) |
| Token de verificación | El valor de `WHATSAPP_VERIFY_TOKEN` en tu `.env` |

3. Click en **Verificar y guardar**

En los logs de la VM debe aparecer:
```
[WEBHOOK] Verification successful
```

4. En **Campos de webhook** → activa **`messages`** → Suscribirse

---

## 10. Templates de WhatsApp

Los templates son mensajes pre-aprobados por Meta para contactar al cliente de forma proactiva. Se necesitan para confirmaciones de citas manuales, recordatorios y alertas del watchdog.

Ve a: **Meta Business Suite → Cuenta de WhatsApp → Herramientas → Plantillas de mensajes → Crear plantilla**

> ⚠️ Los templates tardan entre 1 hora y 48 horas en aprobarse. Créalos todos a la vez.

### Template 1 — `confirmacion_cita`

| Campo | Valor |
|---|---|
| Nombre | `confirmacion_cita` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
Hola {{1}}, tu cita ha sido confirmada para el {{2}} a las {{3}}.

Si necesitas cancelarla, pulsa el botón.
```

**Botón de respuesta rápida:**
- Texto del botón: `Cancelar cita`
- Payload: `reminder_cancel_{{1}}`

Donde `{{1}}` = nombre del cliente, `{{2}}` = fecha, `{{3}}` = hora.

### Template 2 — `recordatorio_cita`

| Campo | Valor |
|---|---|
| Nombre | `recordatorio_cita` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
Recuerda que tienes cita mañana {{1}} a las {{2}}.

¿Confirmas tu asistencia?
```

**Dos botones de respuesta rápida:**
- Botón 1: texto `Confirmar` — payload `reminder_confirm_{{1}}`
- Botón 2: texto `Cancelar` — payload `reminder_cancel_{{1}}`

Donde `{{1}}` = fecha, `{{2}}` = hora.

### Template 3 — `alerta_sistema`

Usado por el watchdog para avisar al administrador de problemas en el servidor.

| Campo | Valor |
|---|---|
| Nombre | `alerta_sistema` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |

**Cuerpo:**
```
⚠️ Alerta del sistema: {{1}}
Fecha: {{2}}
Detalle: {{3}}
```

Sin botones. Donde `{{1}}` = tipo de alerta, `{{2}}` = timestamp, `{{3}}` = descripción.

### Comprobar que están aprobados

Cuando el estado muestre **APPROVED** en verde puedes continuar. Mientras estén en **PENDING** los jobs de confirmación y recordatorio no funcionarán.

---

## PARTE 5 — Operación

---

## 11. Desplegar cambios de código

Flujo estándar para modificar el bot:

```bash
# 1. En local — hacer el cambio, ejecutar tests, subir a git
pytest
git add ...
git commit -m "descripción del cambio"
git push

# 2. En la VM — desplegar
cd ~/app && make update
```

`make update` hace: `git pull` → `pip install` → `systemctl restart`.

---

## 12. Monitorización y logs

### Ver logs en tiempo real

```bash
make logs            # logs del bot (uvicorn + APScheduler)
make logs-ngrok      # logs del túnel ngrok
make logs-watchdog   # logs del watchdog (comprobaciones de salud)
```

### Filtrar eventos concretos

```bash
# Solo errores
sudo journalctl -u peluqueria -f | grep ERROR
grep ERROR /var/log/peluqueria/app.log | tail -20

# Citas creadas hoy
grep "$(date +%Y-%m-%d)" /var/log/peluqueria/app.log | grep "Created appointment"

# Actividad de un número (por últimos 4 dígitos)
grep "1234" /var/log/peluqueria/app.log

# Jobs del scheduler
sudo journalctl -u peluqueria --since "2 hours ago" | grep "\[JOB\]"
```

### Qué ves cuando todo funciona bien

```
# Mensaje entrante y respuesta
[INFO] [WEBHOOK] text from ****1234: hola
[INFO] [WA] interactive(button) → ****1234

# Reserva completada
[INFO] [CAL] Created appointment (confirmed): Ana García 346... 2026-03-25 10:00
[INFO] [WA] text → ****1234: Tu cita está confirmada

# Jobs funcionando (cada X minutos)
[INFO] [JOB] START sync_citas_manuales
[INFO] [JOB] END sync_citas_manuales (0.4s)
```

### Health check y métricas

```bash
make health
# → {"status":"ok","calendar":"ok","metrics":{...}}

curl -s http://localhost:8000/metrics | python3 -m json.tool
```

`calendar_errors`, `whatsapp_errors` y `handler_dropped` deben estar siempre a 0.

---

## 13. Operación diaria

### Comandos de control

```bash
make status    # estado de todos los servicios
make start     # arranca todo
make stop      # para todo
make restart   # reinicia todo
make health    # comprueba conectividad
```

### Reinicio nocturno automático

El timer `peluqueria-restart.timer` reinicia el bot a las **4:00 AM** cada noche. Limpia memoria, conexiones TCP colgadas y estados de conversación expirados. No requiere intervención manual.

### Watchdog automático

El script `watchdog.py` corre cada 5 minutos via cron y comprueba:
1. `/health` del bot — detecta caídas y fallos de Calendar
2. RAM > 90% — alerta de memoria crítica
3. Disco > 90% — alerta de disco crítico
4. Spike de errores en `/metrics` — 3+ errores nuevos en 5 minutos

Si detecta un problema, manda un WhatsApp al `ADMIN_PHONE` usando el template `alerta_sistema` (cooldown de 30 minutos entre alertas del mismo tipo).

### Cuándo intervenir manualmente

| Señal | Acción |
|---|---|
| `make status` muestra `failed` | `make restart` |
| `make health` devuelve `calendar: "error"` más de 1h | Verificar Google Cloud Console y `credentials.json` |
| Logs con `HTTP 401` de WhatsApp | Token expirado — genera uno nuevo en Meta, actualiza `.env`, `make restart` |
| Alerta del watchdog por RAM | `free -h` — considera aumentar swap o tipo de VM |
| Alerta del watchdog por disco | `df -h` — limpia logs viejos con `sudo journalctl --vacuum-time=14d` |

### Gestión de logs y disco

Los logs del bot se rotan automáticamente: 10 MB × 3 ficheros = 30 MB máximo.

```bash
# Ver cuánto ocupa journald
sudo journalctl --disk-usage

# Limpiar logs de más de 2 semanas
sudo journalctl --vacuum-time=14d
```

---

## 14. Migrar de ngrok a nginx

Cuando tengas acceso a Meta para cambiar la URL del webhook:

### 14.1 Preparar

Asegúrate de que `SERVER_IP` está configurado en el Makefile con tu IP estática:
```bash
nano ~/app/Makefile
# SERVER_IP := 34.xxx.xxx.xxx
```

### 14.2 Ejecutar la migración

```bash
make switch-nginx
```

`make switch-nginx` instala nginx, genera un certificado SSL autofirmado (válido 10 años), configura el proxy a uvicorn, para ngrok y arranca nginx.

> Meta acepta certificados autofirmados para webhooks — solo exige HTTPS, no que el certificado esté firmado por una CA pública.

### 14.3 Actualizar el webhook en Meta

En **Meta for Developers → WhatsApp → Configuración → Webhook → Editar**:
- Nueva URL: `https://TU_IP_PUBLICA/webhook`
- El token de verificación no cambia

### 14.4 Verificar

```bash
curl -k https://localhost/health
# → {"status":"ok","calendar":"ok",...}

curl -k https://TU_IP_PUBLICA/health
```

El flag `-k` es necesario en curl porque el certificado es autofirmado. Meta no necesita ese flag.

---

## 15. Seguridad

### 15.1 Firewall con UFW

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

El puerto 8000 de uvicorn **no se abre** — solo es accesible desde localhost.

### 15.2 Proteger ficheros sensibles

```bash
chmod 600 ~/app/.env
chmod 600 ~/app/credentials.json
```

### 15.3 WHATSAPP_APP_SECRET — por qué es importante

Sin este valor, cualquier persona que conozca la URL de tu webhook puede enviar peticiones falsas que el bot procesará como mensajes reales. Con él configurado, el backend verifica con HMAC que cada petición viene realmente de Meta.

### 15.4 Nunca hagas esto

```bash
# NUNCA
git add credentials.json    # clave privada de Google
git add .env                # tokens y secretos
```

Verifica que están en `.gitignore`:
```bash
grep -E "credentials|\.env" .gitignore
```

---

## 16. Troubleshooting

### El bot no responde

```bash
# ¿Los servicios están corriendo?
make status

# ¿Llegan mensajes al webhook?
make logs
# Sin líneas [WEBHOOK] → problema de red o Meta (no llegan peticiones)
# Con líneas [WEBHOOK] → problema interno (Calendar o WhatsApp)
```

### No se crean citas en Calendar

```bash
make health
# "calendar": "error" → credenciales inválidas o API de Google caída

grep "\[CAL\].*Error" /var/log/peluqueria/app.log | tail -10
```

### WhatsApp devuelve HTTP 401

El token expiró o fue revocado:

```bash
# 1. Genera un nuevo token en Meta Business Suite
# 2. Actualiza el .env
nano ~/app/.env
# Cambia WHATSAPP_ACCESS_TOKEN=nuevo_token

# 3. Reinicia
make restart
```

### No llegan recordatorios ni confirmaciones

```bash
# ¿El job está corriendo?
make logs | grep "\[JOB\]"

# ¿Hay errores de WhatsApp?
grep "\[WA\].*HTTP 4" /var/log/peluqueria/app.log | tail -5
# HTTP 400 → template no aprobado o parámetros incorrectos
# HTTP 401 → token expirado
```

Verifica en Meta Business Suite que los templates están en estado **APPROVED**.

### ngrok se desconecta

```bash
make status    # ver si ngrok.service está failed
make restart   # reiniciar
```

Si se desconecta frecuentemente, revisa los logs:
```bash
make logs-ngrok
```

---

## 17. Checklist final

### Infraestructura
- [ ] VM e2-micro corriendo en us-east1
- [ ] IP estática asignada
- [ ] `make health` responde `{"status":"ok","calendar":"ok"}`
- [ ] `make status` muestra todos los servicios `active (running)`
- [ ] Firewall UFW activo con solo puertos 22, 80 y 443
- [ ] Puerto 8000 NO accesible desde internet

### Código y configuración
- [ ] `.env` completo con todos los valores reales, `chmod 600`
- [ ] `credentials.json` en la VM con `chmod 600`
- [ ] `.env` y `credentials.json` NO están en git (`git status` no los muestra)
- [ ] Servicio systemd activo y habilitado al arranque
- [ ] Reinicio nocturno activo: `systemctl status peluqueria-restart.timer` muestra `active (waiting)`
- [ ] Watchdog en cron: `crontab -l` muestra la línea de `watchdog.py`

### Google Calendar
- [ ] Service Account creada con `credentials.json` descargado
- [ ] Calendario creado y compartido con la Service Account (permisos de edición)
- [ ] `GOOGLE_CALENDAR_ID` en `.env` es el correcto
- [ ] `make health` muestra `calendar: "ok"`

### Meta / WhatsApp
- [ ] App creada en Meta for Developers
- [ ] Número de teléfono añadido y verificado
- [ ] Token permanente (sin expiración) en `.env`
- [ ] `WHATSAPP_APP_SECRET` configurado en `.env`
- [ ] Webhook URL apunta al bot y está verificado (tick verde en Meta)
- [ ] Suscripción al evento `messages` activa
- [ ] Template `confirmacion_cita` en estado **APPROVED**
- [ ] Template `recordatorio_cita` en estado **APPROVED**
- [ ] Template `alerta_sistema` en estado **APPROVED**

### Prueba funcional completa
- [ ] Enviar mensaje → bot muestra menú principal
- [ ] Completar reserva completa → cita aparece en Google Calendar
- [ ] Cancelar cita → desaparece de Calendar
- [ ] Crear cita manual en Calendar con `Estado: pendiente` → llega confirmación WhatsApp
- [ ] Logs sin errores: `grep ERROR /var/log/peluqueria/app.log` sin resultados
- [ ] Métricas coherentes: `make health` muestra `calendar_errors: 0` y `whatsapp_errors: 0`

---

**Con todos los puntos marcados, el sistema está listo para uso real.**
