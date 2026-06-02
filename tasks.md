# Tasks — Peluquería Citas Bot

Estado actual: bot funcional en producción (VM Google Cloud).
Objetivo: puesta en producción completa, panel de administración y notificaciones por email.

---

## 1. Infraestructura — Migración ngrok → DuckDNS + nginx

El sistema actual usa ngrok como túnel HTTPS. Para producción real se reemplaza por DuckDNS (dominio gratuito) + Let's Encrypt (certificado real) + nginx (proxy directo, sin intermediarios).

### 1.1 DuckDNS — paso manual previo (5 min, una sola vez)
- [ ] Entrar en duckdns.org con cuenta Google
- [ ] Crear subdominio (ej: `dmbarber`) → queda `dmbarber.duckdns.org`
- [ ] Pegar la IP estática de la VM en el campo IP → Update IP
- [ ] Anotar el token de DuckDNS (lo necesita Certbot para la validación DNS)

### 1.2 Makefile — nuevos targets
- [ ] Añadir target `certbot`: instala Certbot, genera certificado Let's Encrypt para el dominio DuckDNS
- [ ] Añadir target `_nginx-config-prod`: genera config nginx con rutas para webhook, admin API y frontend estático, usando certificado real
- [ ] Actualizar `make all` para que use DuckDNS + Certbot en vez de ngrok
- [ ] Mantener `make all-dev` con ngrok para desarrollo local
- [ ] Añadir variable `DUCKDNS_DOMAIN` al Makefile (ej: `dmbarber.duckdns.org`)
- [ ] Añadir cron de renovación automática de certificado Let's Encrypt (Certbot lo configura, verificar que queda activo)

### 1.3 nginx — config actualizada
El nginx actual solo proxea todo a FastAPI. Hay que añadir las rutas del panel admin.

Config objetivo:
```
443 HTTPS
├── /webhook          → proxy 127.0.0.1:8000  (bot WhatsApp, ya existe)
├── /admin/api/*      → proxy 127.0.0.1:8000  (nuevos endpoints admin)
└── /admin/*          → archivos estáticos     (build React)
```

- [ ] Actualizar template nginx en Makefile con las tres rutas
- [ ] Verificar que `/webhook` sigue funcionando tras el cambio
- [ ] Verificar que puerto 8000 sigue sin estar expuesto directamente

### 1.4 Documentación — actualizar deploy.md
- [ ] Reemplazar toda la sección de ngrok con DuckDNS + Certbot
- [ ] Añadir los pasos manuales de DuckDNS al checklist previo
- [ ] Eliminar referencias a `NGROK_DOMAIN` y `NGROK_TOKEN` del .env.example
- [ ] Actualizar la tabla "Opciones de túnel" (ya no hay opción A/B: DuckDNS es la opción única de producción)
- [ ] Actualizar checklist final (sección 17)

---

## 2. Email — Notificaciones al peluquero

Cuando un cliente reserva o cancela por WhatsApp, el peluquero recibe un email con formato propio. Google Calendar ya envía notificaciones pero con formato genérico; estos emails son personalizados.

### 2.1 Servicio de email — `app/services/email.py`
- [ ] Crear `app/services/email.py` con función `send_email(subject, body)` usando `smtplib` (built-in, sin dependencias nuevas)
- [ ] Usar Gmail SMTP (`smtp.gmail.com:587`) con TLS
- [ ] Leer credenciales de variables de entorno: `EMAIL_FROM`, `EMAIL_TO`, `EMAIL_APP_PASSWORD`
- [ ] Si las variables no están configuradas, loggear warning y no fallar (email es opcional)
- [ ] Envío asíncrono (en un thread, para no bloquear la respuesta al cliente)

### 2.2 Trigger — nueva reserva
Punto de integración: `_handle_book_enter_name()` en `app/handlers/conversation.py`, justo después de la llamada a `cal.crear_cita()` (línea ~489).

Email al peluquero:
```
Asunto: Nueva cita — [Nombre cliente]
Cuerpo:
  Servicio:  Corte de pelo
  Día:       martes 3 de junio
  Hora:      11:00
  Cliente:   Juan García
  Teléfono:  +34 612 345 678
```

- [ ] Añadir llamada a `email.send_email()` tras `cal.crear_cita()` exitoso
- [ ] Formatear fecha en español (sin librerías extra)

### 2.3 Trigger — cancelación por cliente
Dos puntos de integración en `conversation.py`:
- `_handle_cancel_select()` línea ~520 (cancelación desde el menú)
- Bloque `reminder_cancel_` línea ~556 (cancelación desde el recordatorio)

Email al peluquero:
```
Asunto: Cita cancelada — [Nombre cliente]
Cuerpo:
  Servicio:  Corte de pelo
  Día:       martes 3 de junio
  Hora:      11:00
  Cliente:   Juan García
  Teléfono:  +34 612 345 678
```

- [ ] Recuperar datos de la cita antes de cancelarla (el event_id ya está disponible, hay que hacer una llamada a Calendar para obtener los detalles)
- [ ] Añadir llamada a `email.send_email()` tras `cal.cancelar_cita()` exitoso en ambos puntos

### 2.4 Variables de entorno
- [ ] Añadir al `.env.example`:
  ```ini
  EMAIL_FROM=peluqueria@gmail.com
  EMAIL_TO=peluqueria@gmail.com
  EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ```
- [ ] Añadir instrucciones en deploy.md: cómo activar "Contraseñas de aplicación" en Gmail (Cuenta Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicación)

### 2.5 Tests
- [ ] Test unitario para `send_email()` con SMTP mockeado
- [ ] Test de integración: simular cancelación → verificar que se llama al email service

---

## 3. Backend — Endpoints de administración

Nuevos endpoints en FastAPI para que el panel React pueda leer y modificar la configuración.

### 3.1 Autenticación
- [ ] Añadir `ADMIN_TOKEN` al `.env` y `.env.example` (string largo aleatorio)
- [ ] Crear dependencia FastAPI `verify_admin_token` que lee la cabecera `Authorization: Bearer <token>` y devuelve 401 si no coincide
- [ ] Aplicar la dependencia a todos los endpoints `/admin/*`

### 3.2 Endpoints
- [ ] `GET /admin/config` — lee `config.yaml` y lo devuelve como JSON
- [ ] `PUT /admin/config` — recibe JSON, lo valida con `_load_and_validate_yaml()` existente, lo guarda en `config.yaml` y envía `SIGTERM` al proceso para que systemd lo reinicie con la nueva config
- [ ] Crear router `app/handlers/admin.py` e incluirlo en `main.py`

### 3.3 Tests
- [ ] Test para `GET /admin/config` sin token → 401
- [ ] Test para `GET /admin/config` con token → 200 + estructura correcta
- [ ] Test para `PUT /admin/config` con config válida → guarda y responde 200
- [ ] Test para `PUT /admin/config` con config inválida → 422 sin tocar el fichero

---

## 4. Frontend — Panel de administración React

Web mobile-first accesible en `https://dmbarber.duckdns.org/admin`.
El peluquero recibe la URL con el token incluido y entra directamente.

### 4.1 Setup del proyecto
- [ ] Crear `frontend/` en la raíz del repo con Vite + React + Tailwind
- [ ] Añadir `frontend/` al `.gitignore` excepto el código fuente (ignorar `node_modules/` y `dist/`)
- [ ] Configurar Vite para que el build salga en `frontend/dist/` y use `/admin/` como base path
- [ ] Añadir `frontend/` al Makefile: `make build-frontend` hace `npm install && npm run build`
- [ ] `make update` también ejecuta `make build-frontend` si hay cambios en `frontend/`

### 4.2 Autenticación por token
- [ ] Al cargar la app, leer el token de `?token=` en la URL
- [ ] Guardarlo en `localStorage` para no tener que pasarlo en la URL en cada recarga
- [ ] Incluirlo en todas las peticiones al backend como cabecera `Authorization: Bearer <token>`
- [ ] Si el backend responde 401, mostrar pantalla de "Acceso denegado" con instrucciones de contacto

### 4.3 Sección — Horario semanal
- [ ] Mostrar los 7 días de la semana
- [ ] Cada día muestra sus rangos horarios actuales (ej: 10:00–14:00 y 17:00–21:00)
- [ ] Toggle para marcar un día como cerrado (quita el día del config)
- [ ] Añadir/eliminar rangos dentro de un día
- [ ] Validación visual: fin > inicio, sin solapamientos
- [ ] Botón "Guardar horario"

### 4.4 Sección — Servicios
- [ ] Listar los servicios actuales con nombre, precio y duración
- [ ] Editar nombre, precio, duración de cada servicio
- [ ] Añadir nuevo servicio (con key automática desde el nombre)
- [ ] Eliminar servicio (con confirmación)
- [ ] Límite visible de 9 servicios (límite de WhatsApp)
- [ ] Botón "Guardar servicios"

### 4.5 Sección — Evento especial
- [ ] Toggle activo/inactivo
- [ ] Campo nombre del evento (ej: "Navidad 2026")
- [ ] Añadir fechas: date picker + rangos horarios por fecha
- [ ] Eliminar fechas individuales
- [ ] Botón "Guardar evento"

### 4.6 Sección — Ajustes generales
- [ ] Toggle recordatorios automáticos (on/off)
- [ ] Toggle confirmaciones automáticas (on/off)
- [ ] Campo numérico: ventana de búsqueda de días (días que se ofrecen al cliente)
- [ ] Botón "Guardar ajustes"

### 4.7 UX general
- [ ] Tras guardar: mensaje "Guardado. El bot se reiniciará en unos segundos" (porque el SIGTERM tarda ~5s en que systemd relance)
- [ ] Indicador de carga mientras se guarda
- [ ] Manejo de error si el backend no responde (el bot está reiniciándose)
- [ ] Diseño mobile-first: una columna, secciones colapsables, botones grandes

---

## 5. Templates de WhatsApp

Los templates son mensajes pre-aprobados por Meta. Hay que crearlos en el panel de Meta y esperan aprobación (1-48h). Sin ellos no funcionan recordatorios ni confirmaciones manuales.

- [ ] Crear template `confirmacion_cita` (UTILITY, Español España):
  ```
  Hola {{1}}, tu cita ha sido confirmada para el {{2}} a las {{3}}.
  Si necesitas cancelarla, pulsa el botón.
  [Botón: Cancelar cita | payload: reminder_cancel_{{1}}]
  ```
- [ ] Crear template `recordatorio_cita` (UTILITY, Español España):
  ```
  Recuerda que tienes cita mañana {{1}} a las {{2}}. ¿Confirmas tu asistencia?
  [Botón: Confirmar | payload: reminder_confirm_{{1}}]
  [Botón: Cancelar  | payload: reminder_cancel_{{1}}]
  ```
- [ ] Crear template `alerta_sistema` (UTILITY, Español España):
  ```
  ⚠️ Alerta del sistema: {{1}}
  Fecha: {{2}}
  Detalle: {{3}}
  ```
- [ ] Verificar que los tres están en estado APPROVED antes de activar recordatorios y confirmaciones en el config

---

## 6. Documentación — deploy.md actualizado

El deploy.md actual cubre todo el proceso pero basado en ngrok. Hay que actualizarlo para que alguien sin experiencia pueda seguirlo de principio a fin.

- [ ] **Sección DuckDNS**: pasos para crear el subdominio y apuntarlo a la IP
- [ ] **Sección email**: cómo activar App Password en Gmail y qué poner en el `.env`
- [ ] **Sección panel admin**: cómo generar el ADMIN_TOKEN, cómo pasar la URL al peluquero
- [ ] **Sección templates**: los tres templates con su contenido exacto listo para copiar-pegar
- [ ] **Actualizar checklist final** (sección 17) con los nuevos puntos: DuckDNS apuntado, certificado Let's Encrypt activo, email configurado, templates aprobados, panel admin accesible
- [ ] **Eliminar** toda referencia a ngrok del flujo principal (moverlo a una sección "Desarrollo local" si se quiere mantener)

---

## 7. Makefile — targets finales

Resumen de los cambios al Makefile para que `make all` instale todo de una vez en una VM limpia.

- [ ] `make all` (producción): apt deps + Python venv + Node + build frontend + systemd + DuckDNS/Certbot + nginx + watchdog cron
- [ ] `make all-dev` (desarrollo): solo Python venv + ngrok (para trabajar en local)
- [ ] `make build-frontend`: `npm ci && npm run build` en `frontend/`
- [ ] `make update`: git pull + pip install + build frontend + systemctl restart
- [ ] Verificar que `_check-env` valida también `ADMIN_TOKEN` y `EMAIL_APP_PASSWORD` (o los marca como opcionales con warning)

---

## Orden de implementación recomendado

```
1. Email service              ← pequeño, independiente, alto valor
2. Admin API endpoints        ← base necesaria para el frontend
3. Frontend React             ← depende de los endpoints
4. Migración DuckDNS/nginx    ← puede hacerse en paralelo con el frontend
5. Makefile actualizado       ← integra todo al final
6. Documentación              ← última, cuando todo está funcionando
7. Templates WhatsApp         ← proceso manual en paralelo (tardan en aprobarse)
```
