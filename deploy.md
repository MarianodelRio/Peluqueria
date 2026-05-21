# Guía de Despliegue y Operación en Producción
## Sistema de Citas — Peluquería

---

## 1. VISIÓN GENERAL

### Qué se está montando

Un bot de WhatsApp que permite a los clientes de la peluquería reservar, ver y cancelar citas. El peluquero gestiona su agenda en Google Calendar. No hay base de datos ni panel de administración propio.

### Arquitectura

```
Cliente WhatsApp
      │
      ▼
Meta (WhatsApp Cloud API)
      │  webhook HTTPS
      ▼
VM Linux (Ubuntu) — IP pública fija
  └── FastAPI + Uvicorn
  └── APScheduler (jobs cada 5-60 min)
      │
      ▼
Google Calendar (fuente de verdad)
```

### Flujo general

1. Cliente escribe por WhatsApp → Meta reenvía el mensaje a tu VM via webhook HTTPS
2. FastAPI procesa el mensaje y consulta Google Calendar para ver disponibilidad
3. FastAPI responde al cliente via WhatsApp Cloud API
4. Jobs en segundo plano sincronizan citas manuales y envían recordatorios

---

## 2. PREPARACIÓN

Antes de empezar necesitas tener esto listo:

### Checklist de recursos

- [ ] **SIM del negocio** — número de teléfono real que se usará como número de WhatsApp Business. Debe ser un número que no tenga ya WhatsApp instalado (o que puedas desvincularlo).
- [ ] **Tarjeta de crédito/débito** — necesaria para Google Cloud (e2-micro es gratuito pero piden tarjeta para verificar). No se cobra nada si te mantienes en el free tier.
- [ ] **Email del negocio** — recomendable tener un Gmail específico del negocio (no el personal). Se usará para Google Cloud y Meta Business.
- [ ] **Código funcionando en local** — el proyecto debe pasar `pytest` sin errores antes de desplegar.
- [ ] **Acceso SSH desde tu ordenador** — necesitarás una terminal.

### Verificar que el código funciona antes de desplegar

```bash
# En tu máquina local
cd ~/Desktop/Peluqueria
source venv/bin/activate
pytest
```

Todos los tests deben pasar. Si alguno falla, resuélvelo antes de continuar.

---

## 3. GOOGLE CLOUD — CONFIGURACIÓN COMPLETA

Todo esto se hace desde el ordenador, en el navegador.

### 3.1 Crear cuenta de Google Cloud

1. Ve a [console.cloud.google.com](https://console.cloud.google.com)
2. Inicia sesión con el **email del negocio**
3. Acepta los términos
4. Cuando pida tarjeta: introdúcela. No se cobra nada por el free tier. Es solo verificación de identidad.

### 3.2 Crear proyecto

1. Arriba a la izquierda, haz click en el selector de proyectos → **Nuevo proyecto**
2. Nombre: `peluqueria-citas`
3. Click en **Crear**
4. Asegúrate de que el proyecto `peluqueria-citas` está seleccionado en el menú superior

### 3.3 Activar la Google Calendar API

1. En el menú izquierdo: **APIs y servicios → Biblioteca**
2. Busca `Google Calendar API`
3. Click en el resultado → **Habilitar**

### 3.4 Crear Service Account (cuenta de servicio)

Esta es la "cuenta robot" que el backend usa para leer/escribir en Google Calendar.

1. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**
2. Nombre: `peluqueria-backend`
3. ID de cuenta de servicio: se rellena solo
4. Click en **Crear y continuar**
5. En "Rol": selecciona **Editor** (o déjalo vacío, no importa para Calendar)
6. Click en **Listo**

### 3.5 Descargar credentials.json

1. En la página de Credenciales, busca la cuenta de servicio que acabas de crear
2. Click en el nombre → pestaña **Claves**
3. **Añadir clave → Crear clave nueva → JSON → Crear**
4. Se descargará un fichero JSON. **Guárdalo bien — solo se puede descargar una vez.**
5. Renómbralo a `credentials.json`

> ⚠️ **CRÍTICO**: Este fichero contiene la clave privada de tu cuenta de servicio. No lo subas nunca a git. No lo compartas. Trátalo como una contraseña.

Anota el campo `client_email` que aparece dentro del JSON. Lo necesitarás en el paso 3.7. Tiene este formato:
```
peluqueria-backend@peluqueria-citas.iam.gserviceaccount.com
```

### 3.6 Crear el calendario en Google Calendar

1. Ve a [calendar.google.com](https://calendar.google.com) con el email del negocio
2. En el menú izquierdo, junto a "Otros calendarios" → click en **+**
3. **Crear nuevo calendario**
4. Nombre: `Citas Peluquería`
5. Click en **Crear calendario**

### 3.7 Compartir el calendario con la Service Account

Esto es lo que permite al backend leer y escribir citas.

1. En Google Calendar, busca el calendario recién creado en el menú izquierdo
2. Click en los tres puntos → **Configuración y uso compartido**
3. Baja hasta **Compartir con personas específicas → Añadir personas**
4. Pega el `client_email` del paso 3.5 (el que termina en `.iam.gserviceaccount.com`)
5. Permisos: **Realizar cambios en eventos**
6. Click en **Enviar**

### 3.8 Obtener el Calendar ID

1. En la misma página de configuración del calendario
2. Baja hasta **Integrar calendario**
3. Copia el **ID del calendario** — tiene este aspecto:
   ```
   c_abc123def456@group.calendar.google.com
   ```
4. Guárdalo, lo necesitarás en el `.env`

---

## 4. CREAR LA VM EN GOOGLE CLOUD

### 4.1 Crear la instancia

1. En Google Cloud Console: menú izquierdo → **Compute Engine → Instancias de VM**
2. Si es la primera vez, tardará un momento en activarse
3. Click en **Crear instancia**

Configura exactamente así para mantenerte en el free tier:

| Campo | Valor |
|---|---|
| Nombre | `peluqueria-vm` |
| Región | `us-east1` (South Carolina) |
| Zona | `us-east1-b` |
| Tipo de máquina | `e2-micro` (0.25 vCPU, 1 GB RAM) |
| Sistema operativo | Ubuntu 22.04 LTS |
| Disco de arranque | 30 GB (estándar) |

> **Por qué us-east1**: el free tier de Google Cloud incluye 1 instancia e2-micro **en us-east1, us-west1 o us-central1**. Europa no es gratuita. La latencia adicional es irrelevante para este sistema (WhatsApp ya añade latencia propia).

### 4.2 Configurar red y firewall

En la misma pantalla de creación, baja hasta **Opciones avanzadas → Redes**:

- Asegúrate de que **"Permitir tráfico HTTP"** y **"Permitir tráfico HTTPS"** están marcados

Esto abre los puertos 80 y 443. El puerto 8000 de uvicorn no debe estar expuesto directamente a internet — irá detrás de nginx.

### 4.3 Reservar IP externa estática

Por defecto la IP pública cambia al reiniciar. Para que el webhook de Meta siempre apunte al mismo sitio:

1. Menú izquierdo → **Red de VPC → Direcciones IP externas**
2. Busca la IP de tu instancia → click en **Estática**
3. Ponle nombre: `peluqueria-ip`
4. Confirma

Anota esta IP. La necesitarás para configurar el webhook de Meta.

### 4.4 Conectarte por SSH

Desde Google Cloud Console, en la lista de instancias, click en **SSH** junto a tu VM. Se abrirá una terminal en el navegador.

O desde tu ordenador (más cómodo para el día a día):

```bash
# Instala gcloud en tu máquina si no lo tienes
# https://cloud.google.com/sdk/docs/install

# Luego conecta directamente
gcloud compute ssh peluqueria-vm --zone=us-east1-b
```

---

## 5. DESPLEGAR EL BACKEND

Todo lo que sigue se ejecuta **dentro de la VM** (en la terminal SSH).

### 5.1 Actualizar el sistema e instalar dependencias base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx
```

### 5.2 Crear usuario para el servicio

```bash
sudo useradd -m -s /bin/bash peluqueria
sudo su - peluqueria
```

A partir de aquí trabajas como el usuario `peluqueria`.

### 5.3 Clonar el código

```bash
cd /home/peluqueria
git clone https://github.com/TU_USUARIO/TU_REPO.git app
cd app
```

> Si no tienes el código en GitHub, cópialo con scp desde tu máquina local:
> ```bash
> gcloud compute scp --recurse ~/Desktop/Peluqueria peluqueria@peluqueria-vm:/home/peluqueria/app --zone=us-east1-b
> ```

### 5.4 Crear entorno virtual e instalar dependencias

```bash
cd /home/peluqueria/app
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.5 Subir credentials.json

Desde tu **máquina local**:

```bash
gcloud compute scp ~/Downloads/credentials.json peluqueria@peluqueria-vm:/home/peluqueria/app/credentials.json --zone=us-east1-b
```

### 5.6 Proteger credentials.json

```bash
# En la VM
chmod 600 /home/peluqueria/app/credentials.json
```

### 5.7 Crear el fichero .env

```bash
nano /home/peluqueria/app/.env
```

Contenido completo (sustituye cada valor):

```env
# WhatsApp
WHATSAPP_PHONE_NUMBER_ID=tu_phone_number_id
WHATSAPP_ACCESS_TOKEN=tu_access_token_permanente
WHATSAPP_VERIFY_TOKEN=peluqueria_webhook_2026
WHATSAPP_APP_SECRET=tu_app_secret

# Google Calendar
GOOGLE_CREDENTIALS_PATH=/home/peluqueria/app/credentials.json
GOOGLE_CALENDAR_ID=tu_calendar_id@group.calendar.google.com

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/peluqueria/app.log
```

Guarda con `Ctrl+O`, `Enter`, `Ctrl+X`.

```bash
chmod 600 /home/peluqueria/app/.env
```

### 5.8 Crear directorio de logs

```bash
exit  # salir del usuario peluqueria
sudo mkdir -p /var/log/peluqueria
sudo chown peluqueria:peluqueria /var/log/peluqueria
```

### 5.9 Probar que arranca correctamente

```bash
sudo su - peluqueria
cd /home/peluqueria/app
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Debes ver:

```
[INFO] app.main: [APP] Scheduler started. App ready.
```

Si ves errores, resuélvelos antes de continuar. Cuando funcione, para con `Ctrl+C`.

---

## 6. SERVICIO PERSISTENTE CON SYSTEMD

### 6.1 Crear el fichero de servicio

```bash
exit  # vuelve al usuario normal
sudo nano /etc/systemd/system/peluqueria.service
```

Contenido exacto:

```ini
[Unit]
Description=Peluquería Citas — Backend FastAPI
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=peluqueria
Group=peluqueria
WorkingDirectory=/home/peluqueria/app
EnvironmentFile=/home/peluqueria/app/.env
ExecStart=/home/peluqueria/app/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# Logs
StandardOutput=journal
StandardError=journal
SyslogIdentifier=peluqueria

[Install]
WantedBy=multi-user.target
```

### 6.2 Activar e iniciar el servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable peluqueria
sudo systemctl start peluqueria
```

### 6.3 Verificar que está corriendo

```bash
sudo systemctl status peluqueria
```

Debe mostrar `active (running)` en verde.

### 6.4 Comandos de control

```bash
sudo systemctl start peluqueria      # arrancar
sudo systemctl stop peluqueria       # parar
sudo systemctl restart peluqueria    # reiniciar (tras actualizar código o .env)
sudo systemctl status peluqueria     # ver estado
```

---

## 7. NGINX COMO PROXY HTTPS

### Por qué nginx reemplaza a ngrok en producción

En desarrollo usabas ngrok porque te exponía localhost a internet de forma rápida. El problema de ngrok en producción es que:
- La URL cambia cada vez que reinicias (plan gratuito)
- Depende de un proceso externo que puedes olvidar lanzar
- Añade latencia innecesaria pasando por servidores de ngrok

En producción, **nginx hace lo mismo que ngrok pero de forma permanente**: recibe peticiones de Meta en el puerto 443 (HTTPS) y las reenvía a uvicorn en el puerto 8000 local. Una vez configurado no hay que tocarlo.

**No se necesita ningún cambio en el código.** La app no sabe ni le importa si está detrás de ngrok o nginx — ambos le hacen llegar las peticiones exactamente igual.

```
DESARROLLO:   Meta → ngrok (URL temporal) → localhost:8000
PRODUCCIÓN:   Meta → nginx (IP fija, puerto 443) → localhost:8000
```

### Por qué certificado autofirmado (sin dominio)

Let's Encrypt requiere un dominio para emitir certificados. Sin dominio, la alternativa es un certificado autofirmado. **Meta sí acepta certificados autofirmados para webhooks** — lo que exige es HTTPS, no que el certificado esté firmado por una CA pública.

### 7.1 Instalar nginx

```bash
sudo apt install -y nginx openssl
```

### 7.2 Generar certificado SSL autofirmado

```bash
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/ssl/private/peluqueria.key \
  -out /etc/ssl/certs/peluqueria.crt \
  -subj "/CN=TU_IP_PUBLICA"
```

Sustituye `TU_IP_PUBLICA` por la IP estática de la VM (ej: `/CN=34.123.45.67`).

El certificado dura 10 años (`-days 3650`). No hace falta renovarlo.

### 7.3 Configurar nginx

```bash
sudo nano /etc/nginx/sites-available/peluqueria
```

Contenido:

```nginx
server {
    listen 443 ssl;
    server_name TU_IP_PUBLICA;

    ssl_certificate     /etc/ssl/certs/peluqueria.crt;
    ssl_certificate_key /etc/ssl/private/peluqueria.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }
}

server {
    listen 80;
    server_name TU_IP_PUBLICA;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/peluqueria /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # quitar el site por defecto
sudo nginx -t                                  # verificar configuración
sudo systemctl enable nginx
sudo systemctl reload nginx
```

### 7.4 Probar que nginx funciona

```bash
# Desde la propia VM (ignorando el certificado autofirmado con -k)
curl -k https://localhost/health
# Debe responder: {"status":"ok","calendar":"ok",...}

# Desde tu máquina local
curl -k https://TU_IP_PUBLICA/health
```

El flag `-k` solo es necesario al hacer curl porque el certificado es autofirmado. Meta no necesita ese flag — acepta certificados autofirmados directamente.

---

## 8. META — CONFIGURACIÓN DE WHATSAPP

### 8.1 Crear cuenta Meta Business

1. Ve a [business.facebook.com](https://business.facebook.com)
2. Crea una cuenta con el email del negocio
3. Nombre del negocio: el nombre real de la peluquería

### 8.2 Crear App de desarrollador

1. Ve a [developers.facebook.com](https://developers.facebook.com)
2. **Mis apps → Crear app**
3. Tipo: **Business**
4. Nombre de la app: `Peluqueria Citas`
5. Vincula con tu cuenta Business

### 8.3 Añadir WhatsApp a la app

1. En el panel de la app → **Añadir productos → WhatsApp → Configurar**
2. Sigue los pasos para vincular tu cuenta Business

### 8.4 Añadir el número de teléfono

1. **WhatsApp → Gestión de API → Números de teléfono → Añadir número**
2. Introduce el número del negocio (la SIM que compraste)
3. Recibirás un SMS con un código de verificación

### 8.5 Obtener las credenciales

En **WhatsApp → Configuración de la API**:

- **Phone Number ID** → es el `WHATSAPP_PHONE_NUMBER_ID` del `.env`
- **App Secret** → en Configuración → Básica → App Secret (botón "Mostrar") → es el `WHATSAPP_APP_SECRET`

### 8.6 Crear token permanente

El token temporal de pruebas expira en 24h. Para producción necesitas uno permanente:

1. Ve a [business.facebook.com/settings](https://business.facebook.com/settings)
2. **Usuarios → Usuarios del sistema → Añadir**
3. Nombre: `peluqueria-bot`, Rol: **Administrador**
4. Click en el usuario creado → **Añadir activos**
5. Selecciona tu app → permisos: `whatsapp_business_messaging` y `whatsapp_business_management`
6. **Generar token nuevo → Sin expiración**
7. Copia el token → es el `WHATSAPP_ACCESS_TOKEN` del `.env`

### 8.7 Configurar el webhook

1. **WhatsApp → Configuración → Webhook → Editar**
2. URL del webhook: `https://TU_IP_PUBLICA/webhook`
3. Token de verificación: `peluqueria_webhook_2026`
4. Click en **Verificar y guardar**

En los logs de la VM debe aparecer:
```
[INFO] [WEBHOOK] Verification successful
```

5. En **Campos de webhook**, activa: **`messages`** → Suscribirse

---

## 9. TEMPLATES DE WHATSAPP

Los templates son mensajes pre-aprobados por Meta para contactar proactivamente al cliente. Se usan para confirmaciones de citas manuales y recordatorios 24h.

> ⚠️ Los templates tardan **entre 1 hora y 48 horas** en aprobarse. Crea los dos al mismo tiempo y espera antes de hacer pruebas completas.

Ve a: **Meta Business Suite → Cuenta de WhatsApp → Herramientas → Plantillas de mensajes → Crear plantilla**

### Template 1: Confirmación de cita

| Campo | Valor |
|---|---|
| Nombre | `confirmacion_cita` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |

**Cuerpo del mensaje:**
```
Hola {{1}}, tu cita ha sido confirmada para el {{2}} a las {{3}}.

Si necesitas cancelarla, pulsa el botón.
```

**Botón de respuesta rápida:**
- Texto del botón: `Cancelar cita`
- Payload: `reminder_cancel_{{1}}`

Parámetros:
- `{{1}}` = nombre del cliente
- `{{2}}` = fecha
- `{{3}}` = hora

### Template 2: Recordatorio de cita

| Campo | Valor |
|---|---|
| Nombre | `recordatorio_cita` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |

**Cuerpo del mensaje:**
```
Recuerda que tienes cita mañana {{1}} a las {{2}}.

¿Confirmas tu asistencia?
```

**Botones de respuesta rápida (dos botones):**
- Botón 1: texto `Confirmar` — payload `reminder_confirm_{{1}}`
- Botón 2: texto `Cancelar` — payload `reminder_cancel_{{1}}`

### Comprobar que están aprobados

Cuando el estado muestre **APPROVED** en verde puedes continuar. Mientras estén en **PENDING** los jobs de confirmación y recordatorio fallarán silenciosamente.

---

## 9B. TEMPLATE `alerta_sistema`

Este template es el que usa el watchdog para alertar al administrador del bot cuando detecta un problema.

> ⚠️ Al igual que los otros templates, puede tardar entre 1 hora y 48 horas en aprobarse.

Ve a: **Meta Business Suite → Cuenta de WhatsApp → Herramientas → Plantillas de mensajes → Crear plantilla**

| Campo | Valor |
|---|---|
| Nombre | `alerta_sistema` |
| Categoría | `UTILITY` |
| Idioma | `Español (España)` |
| Cabecera | (ninguna) |
| Pie de página | (ninguno) |
| Botones | (ninguno) |

**Cuerpo del mensaje:**
```
*[ALERTA BOT]* {{1}}
Hora: {{2}}
Detalle: {{3}}
```

Parámetros:
- `{{1}}` = etiqueta del problema (por ejemplo: `BOT CAIDO`, `RAM CRITICA 95%`)
- `{{2}}` = fecha y hora del problema (formato `DD/MM/YYYY HH:MM`)
- `{{3}}` = detalle técnico del error

---

## 9C. CONFIGURACIÓN DEL WATCHDOG

El watchdog es un script independiente (`watchdog.py`) que se lanza cada 5 minutos mediante cron y comprueba:

1. **Bot activo** — hace GET `/health` y alerta si el proceso no responde o el calendario falla
2. **RAM** — alerta si el uso supera el umbral (por defecto 90 %)
3. **Disco** — alerta si el uso supera el umbral (por defecto 90 %)
4. **Pico de errores** — compara contadores de `/metrics` respecto a la ejecución anterior y alerta si el delta supera el umbral (por defecto 3 errores nuevos)

Los cooldowns de cada alerta se persisten en un fichero JSON (por defecto `/tmp/watchdog_state.json`) para evitar spam.

### Añadir `ADMIN_PHONE` al `.env`

El watchdog lee `ADMIN_PHONE` del `.env` (o de `config.yaml → negocio.admin_phone` como fallback). Asegúrate de que está presente:

```bash
nano /home/peluqueria/app/.env
```

Añade la línea (dígitos solamente, sin `+`, sin espacios):

```env
ADMIN_PHONE=34612345678
```

### Variables opcionales del watchdog

Las siguientes variables se pueden añadir al `.env` para ajustar el comportamiento. Todas tienen valor por defecto y son opcionales:

| Variable | Por defecto | Descripción |
|---|---|---|
| `WATCHDOG_BOT_URL` | `http://localhost:8000` | URL base del bot |
| `WATCHDOG_TEMPLATE_NAME` | `alerta_sistema` | Nombre del template de alerta |
| `WATCHDOG_STATE_FILE` | `/tmp/watchdog_state.json` | Ruta del fichero de estado |
| `WATCHDOG_RAM_CRITICAL_PCT` | `90` | Umbral de RAM en % para disparar alerta |
| `WATCHDOG_DISK_CRITICAL_PCT` | `90` | Umbral de disco en % para disparar alerta |
| `WATCHDOG_ERROR_SPIKE_THRESHOLD` | `3` | Delta de errores nuevos para disparar alerta |

### Crear directorio de logs del watchdog

```bash
# Si el directorio /var/log/peluqueria no existe aún:
sudo mkdir -p /var/log/peluqueria
sudo chown peluqueria:peluqueria /var/log/peluqueria
```

### Instalar la entrada de cron

```bash
sudo su - peluqueria
crontab -e
```

Añade esta línea al final:

```
*/5 * * * * cd /home/peluqueria/app && venv/bin/python watchdog.py >> /var/log/peluqueria/watchdog.log 2>&1
```

Guarda y cierra el editor. Verifica que la entrada quedó registrada:

```bash
crontab -l
```

### Verificación manual

```bash
# Ejecutar una vez a mano para comprobar que funciona
cd /home/peluqueria/app
source venv/bin/activate
python watchdog.py
# Debe imprimir: [WATCHDOG] All checks OK
# (o la alerta correspondiente si algo falla)

# Ver el log en tiempo real tras la primera ejecución automática
tail -f /var/log/peluqueria/watchdog.log
```

---

## 10. CONEXIÓN FINAL

### 10.1 Actualizar .env con todos los valores reales

```bash
sudo su - peluqueria
nano /home/peluqueria/app/.env
```

Verifica que todos los campos tienen valores reales (ninguno dice `tu_xxx`):

```env
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxxxxx...
WHATSAPP_VERIFY_TOKEN=peluqueria_webhook_2026
WHATSAPP_APP_SECRET=abc123def456...
GOOGLE_CREDENTIALS_PATH=/home/peluqueria/app/credentials.json
GOOGLE_CALENDAR_ID=c_abc123@group.calendar.google.com
LOG_LEVEL=INFO
LOG_FILE=/var/log/peluqueria/app.log
```

### 10.2 Reiniciar el backend

```bash
exit
sudo systemctl restart peluqueria
sudo systemctl status peluqueria
```

### 10.3 Prueba completa del sistema

```bash
# Health check (desde la VM)
curl -k https://localhost/health
# Esperado: {"status":"ok","calendar":"ok",...}

# Ver logs en tiempo real mientras haces una prueba desde el móvil
sudo journalctl -u peluqueria -f
```

Desde el móvil, manda un mensaje al número de WhatsApp del negocio. En los logs debes ver:

```
[WEBHOOK] text from ****XXXX: hola
[WA] interactive(button) → ****XXXX
```

---

## 11. FLUJO DE TRABAJO: CAMBIOS LOCALES → PRODUCCIÓN

Este es el flujo completo para hacer un cambio en el código, probarlo en local y desplegarlo en la VM.

### Paso 1 — Hacer el cambio en local y probarlo

```bash
# En tu máquina (~/Desktop/Peluqueria)
source venv/bin/activate

# Ejecutar tests para verificar que no rompiste nada
pytest

# Probar manualmente con ngrok si quieres verificar el flujo completo
ngrok http 8000
uvicorn app.main:app --reload --port 8000
```

Actualiza el webhook en Meta con la URL de ngrok para la prueba manual. Cuando estés satisfecho, continúa.

### Paso 2 — Subir el cambio a git

```bash
git add app/ruta/del/fichero_modificado.py
git commit -m "descripción del cambio"
git push
```

### Paso 3 — Desplegar en la VM

Conéctate a la VM:

```bash
gcloud compute ssh peluqueria-vm --zone=us-east1-b
```

Y ejecuta el deploy:

```bash
sudo /home/peluqueria/deploy.sh
```

Listo. El script hace git pull, instala dependencias si cambiaron y reinicia el servicio.

### Script de deploy

Crea este script en la VM la primera vez. Después solo tienes que llamarlo.

```bash
sudo nano /home/peluqueria/deploy.sh
```

Contenido:

```bash
#!/bin/bash
set -e

echo "=== Desplegando actualización ==="

cd /home/peluqueria/app
sudo -u peluqueria git pull

sudo -u peluqueria /home/peluqueria/app/venv/bin/pip install -r requirements.txt --quiet

systemctl restart peluqueria
sleep 2
systemctl status peluqueria --no-pager | head -5

echo "=== Deploy completado ==="
```

```bash
sudo chmod +x /home/peluqueria/deploy.sh
```

### Resumen del flujo

```
LOCAL                          VM (PRODUCCIÓN)
──────────────────────         ──────────────────────
1. Editar código
2. pytest               →  todos los tests pasan
3. Probar con ngrok     →  flujo manual OK
4. git commit + push
                               5. sudo /home/peluqueria/deploy.sh
                               6. systemctl status peluqueria → active
```

### Cuándo reiniciar el servicio

| Situación | Acción |
|---|---|
| Cambio en código Python | `git pull` + `systemctl restart` |
| Cambio en `.env` | `systemctl restart` |
| Rotación del token de WhatsApp | Editar `.env` + `systemctl restart` |
| Cambio en `requirements.txt` | `pip install -r requirements.txt` + `systemctl restart` |
| La VM se reinicia sola | El servicio arranca automáticamente, no hace falta hacer nada |

---

## 12. SEGURIDAD BÁSICA

### 12.1 Firewall con UFW

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

El puerto 8000 de uvicorn **no se abre** — solo es accesible desde localhost via nginx.

### 12.2 Proteger ficheros sensibles

```bash
chmod 600 /home/peluqueria/app/.env
chmod 600 /home/peluqueria/app/credentials.json
chmod 700 /home/peluqueria/app
```

### 12.3 WHATSAPP_APP_SECRET — por qué es obligatorio

Sin este valor, cualquier persona que conozca la URL de tu webhook puede enviar peticiones falsas que el bot procesará como mensajes reales de WhatsApp. Con él configurado, el backend verifica que cada petición viene realmente de Meta usando una firma criptográfica.

### 12.4 Nunca hagas esto

```bash
# NUNCA
git add credentials.json    # clave privada de Google
git add .env                # tokens y secretos
```

---

## 13. MONITORIZACIÓN CON LOGS

### Ver logs en tiempo real

```bash
# Desde journald (recomendado)
sudo journalctl -u peluqueria -f

# Desde el fichero de log
tail -f /var/log/peluqueria/app.log
```

### Filtrar solo errores

```bash
sudo journalctl -u peluqueria -f | grep ERROR
grep ERROR /var/log/peluqueria/app.log | tail -20
```

### Buscar eventos concretos

```bash
# Citas creadas hoy
grep "$(date +%Y-%m-%d)" /var/log/peluqueria/app.log | grep "Created appointment"

# Errores de Calendar
grep "\[CAL\].*Error" /var/log/peluqueria/app.log | tail -20

# Errores de WhatsApp
grep "\[WA\].*error\|HTTP 4\|HTTP 5" /var/log/peluqueria/app.log -i | tail -20

# Jobs del scheduler (últimas 2 horas)
sudo journalctl -u peluqueria --since "2 hours ago" | grep "\[JOB\]"

# Actividad de un teléfono concreto (por últimos 4 dígitos)
grep "1234" /var/log/peluqueria/app.log
```

### Qué ves cuando todo funciona bien

```
# Mensaje entrante y respuesta
[INFO] [WEBHOOK] text from ****1234: hola
[INFO] [WA] interactive(button) → ****1234

# Reserva completada
[INFO] [CAL] Created appointment (confirmed): Ana García 346... 2026-03-25 10:00
[INFO] [WA] text → ****1234: ¡Tu cita está confirmada! ✅

# Jobs funcionando (cada X minutos)
[INFO] [JOB] START sync_citas_manuales
[INFO] [JOB] END sync_citas_manuales (0.4s)
[INFO] [JOB] START enviar_recordatorios
[INFO] [JOB] END enviar_recordatorios (0.3s)
```

### Diagnóstico de problemas reales

**"El bot no responde"**

```bash
# ¿El servicio está corriendo?
sudo systemctl status peluqueria

# ¿Llegan mensajes al webhook?
sudo journalctl -u peluqueria --since "30 min ago" | grep WEBHOOK
# Sin líneas WEBHOOK → problema de red o Meta, no del código
# Con líneas WEBHOOK → problema en Calendar o WhatsApp
```

**"No se crean citas en Calendar"**

```bash
grep "\[CAL\].*Error" /var/log/peluqueria/app.log | tail -10
curl http://localhost/health
# calendar: "error" → la API de Google no responde o credenciales fallaron
```

**"No llegan recordatorios"**

```bash
# ¿El job está corriendo?
grep "enviar_recordatorios" /var/log/peluqueria/app.log | tail -5

# ¿Hay errores de WhatsApp?
grep "\[WA\].*HTTP 4" /var/log/peluqueria/app.log | tail -5
# HTTP 401 → token expirado
# HTTP 400 → template no aprobado o parámetros incorrectos
```

**"WhatsApp devuelve HTTP 401"**

```bash
# 1. Genera un nuevo token en Meta Business Suite
# 2. Actualiza el .env
nano /home/peluqueria/app/.env
# Cambia WHATSAPP_ACCESS_TOKEN=nuevo_token

# 3. Reinicia
sudo systemctl restart peluqueria
```

### Health check rápido

```bash
curl http://localhost/health
```

```json
{"status": "ok", "calendar": "ok", "metrics": {...}}   ← todo bien
{"status": "degraded", "calendar": "error", ...}        ← Calendar no responde
```

### Métricas operacionales

```bash
curl http://localhost/metrics
```

```json
{
  "messages_received": 24,
  "bookings_created": 2,
  "bookings_cancelled": 0,
  "calendar_errors": 0,
  "whatsapp_errors": 0,
  "handler_dropped": 0,
  "uptime_seconds": 3600
}
```

`calendar_errors`, `whatsapp_errors` y `handler_dropped` deben estar siempre a 0.

---

## 14. OPERACIÓN DIARIA

### No hace falta hacer nada habitualmente

El sistema está diseñado para funcionar sin intervención. `Restart=always` relanza el proceso si se cae. Los jobs se recuperan solos cuando Calendar o WhatsApp vuelven a estar disponibles.

### Script de revisión rápida (opcional)

Guarda como `/home/peluqueria/check.sh`:

```bash
#!/bin/bash
echo "=== Estado del servicio ==="
sudo systemctl status peluqueria --no-pager | head -4

echo ""
echo "=== Errores últimas 24h ==="
count=$(grep "$(date +%Y-%m-%d)" /var/log/peluqueria/app.log | grep -c ERROR || true)
echo "$count errores"

echo ""
echo "=== Citas creadas hoy ==="
grep "$(date +%Y-%m-%d)" /var/log/peluqueria/app.log | grep -c "Created appointment" || echo "0"

echo ""
echo "=== Health ==="
curl -s http://localhost/health
echo ""
```

```bash
chmod +x /home/peluqueria/check.sh
sudo /home/peluqueria/check.sh
```

### Cuándo intervenir

| Señal | Acción |
|---|---|
| `systemctl status` muestra `failed` | `sudo systemctl restart peluqueria` |
| `calendar: "error"` durante más de 1 hora | Verificar Google Cloud Console |
| `HTTP 401` repetido en logs de WhatsApp | Renovar token en Meta |
| Disco lleno (`df -h` muestra >90%) | Limpiar logs viejos |

### Gestión de logs y disco

Los logs se rotan automáticamente (10 MB × 3 ficheros = 30 MB máximo). Para journald:

```bash
# Ver cuánto ocupa
sudo journalctl --disk-usage

# Limpiar logs de más de 2 semanas
sudo journalctl --vacuum-time=14d
```

---

## 15. CHECKLIST FINAL

### Infraestructura
- [ ] VM e2-micro corriendo en us-east1
- [ ] IP estática asignada
- [ ] nginx instalado y funcionando
- [ ] `curl -k https://TU_IP_PUBLICA/health` responde `{"status":"ok","calendar":"ok"}`

### Código y configuración
- [ ] Código subido a la VM
- [ ] `credentials.json` en la VM con `chmod 600`
- [ ] `.env` completo con todos los valores reales, con `chmod 600`
- [ ] `pip install -r requirements.txt` ejecutado sin errores
- [ ] Servicio systemd activo: `systemctl status peluqueria` muestra `active (running)`
- [ ] El servicio arranca al reiniciar: `sudo reboot` + verificar

### Google Calendar
- [ ] Service Account creada con `credentials.json` descargado
- [ ] Calendar creado y compartido con la Service Account (permisos de edición)
- [ ] `GOOGLE_CALENDAR_ID` en `.env` es el correcto
- [ ] El health check muestra `calendar: "ok"`

### Meta / WhatsApp
- [ ] App creada en Meta for Developers
- [ ] Número de teléfono añadido y verificado
- [ ] Token permanente generado (sin expiración)
- [ ] `WHATSAPP_APP_SECRET` configurado en `.env`
- [ ] Webhook URL apunta a `https://TU_IP_PUBLICA/webhook`
- [ ] Webhook verificado (tick verde en Meta)
- [ ] Suscripción al evento `messages` activa
- [ ] Template `confirmacion_cita` en estado **APPROVED**
- [ ] Template `recordatorio_cita` en estado **APPROVED**
- [ ] Template `alerta_sistema` en estado **APPROVED**
- [ ] Entrada de cron del watchdog visible en `crontab -l`
- [ ] `/var/log/peluqueria/watchdog.log` se actualiza cada 5 minutos

### Prueba funcional completa
- [ ] Enviar mensaje → bot muestra menú
- [ ] Completar reserva completa → cita aparece en Google Calendar
- [ ] Cancelar cita → desaparece de Calendar
- [ ] Crear cita manual en Calendar con `Estado: pendiente` → llega confirmación WhatsApp en menos de 5 minutos
- [ ] Logs sin errores después de las pruebas: `grep ERROR /var/log/peluqueria/app.log`
- [ ] Métricas coherentes: `curl http://localhost/metrics`

### Seguridad
- [ ] Firewall UFW activo con solo puertos 22, 80 y 443 abiertos
- [ ] Puerto 8000 NO accesible desde internet
- [ ] `.env` y `credentials.json` no están en git

---

**Con todos los puntos marcados, el sistema está listo para uso real.**
