# Legacy — Apuntes para Migración a la Nueva Plataforma

> **Propósito.** Este documento captura todo lo importante del código en `legacy/` para que, cuando se borre, no se pierda conocimiento: patrones de arquitectura, decisiones de negocio, gotchas de APIs externas, bugs ya resueltos, y mapeo concreto a la nueva plataforma. Es exhaustivo a propósito — vale más una sección de sobra que una omisión.

---

## Tabla de contenidos

1. [Inventario del código legacy](#1-inventario-del-código-legacy)
2. [Qué hace el bot legacy (visión funcional)](#2-qué-hace-el-bot-legacy-visión-funcional)
3. [Decisiones de negocio capturadas en el código](#3-decisiones-de-negocio-capturadas-en-el-código)
4. [Modelo de datos del legacy](#4-modelo-de-datos-del-legacy)
5. [Patrones de arquitectura que merecen sobrevivir](#5-patrones-de-arquitectura-que-merecen-sobrevivir)
6. [Gotchas y aprendizajes específicos](#6-gotchas-y-aprendizajes-específicos)
7. [WhatsApp Cloud API — apuntes técnicos](#7-whatsapp-cloud-api--apuntes-técnicos)
8. [Google Calendar API — apuntes técnicos](#8-google-calendar-api--apuntes-técnicos)
9. [La conversación del bot (state machine completa)](#9-la-conversación-del-bot-state-machine-completa)
10. [Bugs ya resueltos (no repetirlos)](#10-bugs-ya-resueltos-no-repetirlos)
11. [Tests como documentación de edge cases](#11-tests-como-documentación-de-edge-cases)
12. [Operaciones y despliegue — qué vale como referencia](#12-operaciones-y-despliegue--qué-vale-como-referencia)
13. [Mapping: legacy → nueva arquitectura](#13-mapping-legacy--nueva-arquitectura)
14. [Lo que NO se porta y por qué](#14-lo-que-no-se-porta-y-por-qué)
15. [Criterio para borrar `legacy/`](#15-criterio-para-borrar-legacy)

---

## 1. Inventario del código legacy

```
legacy/
├── app/
│   ├── main.py                  · FastAPI app + lifespan (scheduler start/stop) + /health + /metrics
│   ├── config.py                · Carga + valida config.yaml; constantes; validate_config()
│   ├── handlers/
│   │   ├── webhook.py           · GET/POST /webhook — HMAC, dedup, rate limit, semáforo
│   │   └── conversation.py      · State machine MENU → BOOK_* → CANCEL_*; handle_message()
│   ├── services/
│   │   ├── whatsapp.py          · send_text_message(), send_interactive(), send_template() + retries
│   │   ├── scheduler.py         · 3 jobs: sync manual, recordatorios, limpieza estados
│   │   └── calendar/            · Paquete Google Calendar
│   │       ├── __init__.py      · Re-exports + shims legacy
│   │       ├── client.py        · CalendarClient con service por-thread + health check
│   │       ├── repository.py    · EventsRepository: list_for_day, list_for_range (paginación)
│   │       ├── engine.py        · compute_slots() — función PURA (oro)
│   │       ├── service.py       · get_slots_disponibles, reservar_cita (booking atómico)
│   │       ├── mutations.py     · crear_cita, cancelar_cita, confirmar_cita, marcar_*
│   │       ├── queries.py       · get_eventos_manuales_sin_confirmar, get_citas_para_recordatorio, get_citas_futuras, get_event_by_id
│   │       ├── caches.py        · TTLCache: slot_cache (30s), citas_cache (60s)
│   │       └── locks.py         · SlotLockRegistry: lock por (date, hora)
│   └── utils/
│       ├── parser.py            · parse_tel/nombre/estado/reminder/cfg, set_field, remove_field
│       ├── slots.py             · generate_slots, get_base_slots_for_day, filter_available_slots, format_date_es
│       ├── interactive.py       · Builders WhatsApp (botones + listas) con límites aplicados
│       ├── messages.py          · Strings residuales en español
│       ├── metrics.py           · Counter dict thread-safe + uptime
│       ├── security.py          · mask_phone (last 4 digits)
│       ├── admin.py             · build_status_report() para el comando /estado
│       ├── dedup.py             · MessageDeduplicator (TTL en memoria)
│       └── rate_limiter.py      · RateLimiter sliding-window por key
├── tests/                       · 14 ficheros pytest, mocks completos (no necesita credenciales)
│   ├── conftest.py              · Fixtures mock_wa, mock_cal + helpers de events
│   ├── test_calendar.py
│   ├── test_calendar_unified_flow.py · integración del API unificado (mode=normal/evento)
│   ├── test_conversation.py
│   ├── test_admin.py
│   ├── test_config.py
│   ├── test_interactive.py
│   ├── test_message_deduplicator.py
│   ├── test_parser.py
│   ├── test_rate_limiter.py
│   ├── test_regression.py       · ★ documenta 6 bugs hist­óricos
│   ├── test_scheduler.py
│   ├── test_slots.py
│   ├── test_ttl_cache.py
│   ├── test_webhook.py
│   └── test_whatsapp.py
├── watchdog.py                  · Script standalone — corre cada 5 min via cron
├── generar_qr.py                · Script trivial para generar QR a wa.me
├── config.yaml                  · Config del negocio (rastreable en git)
├── .env.example                 · Plantilla de variables sensibles
├── requirements.txt             · Dependencias prod + dev (fastapi, googleapi, httpx, apscheduler, pytz, yaml, pytest, psutil)
├── pytest.ini                   · pythonpath=. + testpaths=tests
├── Makefile                     · Despliegue/operación completos (systemd + nginx/ngrok + cron + watchdog)
├── deploy.md                    · ★ Guía exhaustiva de despliegue (17 secciones)
├── README.md                    · Documentación de usuario del bot legacy
└── CLAUDE.md                    · Instrucciones para Claude del bot legacy
```

**Total ~3000 líneas de Python** (sin contar tests), arquitectura limpia, 100% testeado con APIs mockeadas.

---

## 2. Qué hace el bot legacy (visión funcional)

### Para el cliente final (vía WhatsApp)

1. Escribe cualquier mensaje → recibe el menú principal con 3 botones: _Pedir cita / Mis citas / Cancelar cita_.
2. **Pedir cita**: elige servicio → elige día (lista) → si el día tiene mañana Y tarde, elige turno → elige hora (lista) → escribe nombre → confirmación.
3. **Mis citas**: lista de citas futuras suyas, no interactiva.
4. **Cancelar cita**: lista de sus citas, elige una, se cancela inmediatamente.
5. **Recordatorio** ~24h antes de la cita: template con botones _Confirmar / Cancelar_.
6. **Manual del peluquero**: cuando el peluquero crea una cita en Calendar con `Telefono:` y `Estado: pendiente`, el bot envía template de confirmación al cliente.
7. **Admin** (solo desde el número del admin): comando `/estado` devuelve informe de sistema (CPU, RAM, Calendar OK, métricas).

### Para el peluquero (vía Google Calendar)

- **Crear cita manual** con `Telefono: +34XXX` en la descripción → bot envía confirmación al cliente.
- **Crear evento sin teléfono** → bloquea el slot pero no envía nada.
- **Eventos de configuración** con prefijo `[CFG]`:
  - `[CFG] CERRADO` → ese día completo cerrado.
  - `[CFG] VACACIONES` → rango entero cerrado.
  - `[CFG] HORARIO HH:MM-HH:MM` → sobreescribe el horario base ese día.

### Procesos automáticos en segundo plano

| Job | Frecuencia | Qué hace | Idempotencia |
|-----|-----------|---------|--------------|
| `job_sync_citas_manuales` | 60 min | Busca eventos con `Telefono:` y `Estado: pendiente`, manda confirmación y marca `Estado: confirmada` | Salta si `Estado: confirmada` |
| `job_enviar_recordatorios` | 60 min | Busca citas en ventana 23-25h con `Recordatorio: no`, manda recordatorio y marca `Recordatorio: sí` | Salta si `Recordatorio: sí` |
| `job_limpiar_estados_conversacion` | 10 min | Borra estados inactivos > 30 min + caché de citas expirada | — |
| `watchdog.py` (cron, no scheduler) | 5 min | `/health`, RAM, disco, error spike → manda alerta WhatsApp con cooldown | Cooldown 30 min standard / 2h errores |

---

## 3. Decisiones de negocio capturadas en el código

### 3.1 Servicios y sus propiedades

Definidos en `config.yaml` (legacy/config.yaml), tres tipos cuidadosamente diferenciados:

| Key | Display | Precio | `duracion_min` | `presencia_cliente_min` |
|-----|---------|--------|----------------|-------------------------|
| `corte` | Corte de pelo | 10 € | 30 | 30 |
| `corte_barba` | Corte de pelo + barba | 12 € | 30 | 30 |
| `mechas` | Mechas | 30 € | 60 | 180 |

**La distinción `duracion_min` vs `presencia_cliente_min` es la decisión de negocio más sutil del sistema:**

- `duracion_min` = tiempo durante el cual el peluquero está ocupado con esta cita. Es la duración del evento en Calendar y la ventana de colisión con otros eventos.
- `presencia_cliente_min` = tiempo total que el cliente permanece físicamente en la peluquería (incluye esperas, secados, etc.). Controla cuándo se ofrece la última hora del día: el cliente debe poder _terminar_ antes del cierre.

Para mechas: el peluquero solo está activo 1h, pero el cliente está 3h en local (tinte+espera). Por eso solo se ofrece reserva de mechas cuando quedan ≥3h hasta el cierre. Si el cliente reserva una mecha a las 19:00 y la peluquería cierra a las 21:00, no entra (necesita hasta las 22:00).

**Esta distinción se usa de forma asimétrica:**
- Para calcular si un slot está libre (colisiones): se usa `duracion_min` (la ventana real ocupada del peluquero).
- Para decidir qué slots ofrecer (slot inicial): se usa `presencia_cliente_min` (que la jornada del cliente quepa).
- El cache key del slot incluye ambos, porque ofrecer mechas y ofrecer cortes en el mismo día devuelve listas diferentes.

### 3.2 Horario y ventanas temporales (legacy/config.yaml)

- **Horario base**: Lunes-Viernes `10:00-14:00` + `17:00-21:00`; Sábado solo `10:00-14:00`. Domingo cerrado por ausencia de entrada.
- **Ventana de búsqueda de cliente**: 14 días hacia delante (lo que se ofrece en el day-picker).
- **Lookaheads para citas**: 30 días citas cliente, 60 días citas manuales (las del peluquero).
- **Recordatorios**: entre 23h y 25h antes (ventana de 2h, el job corre cada hora).
- **Expiración de conversación**: 30 min inactiva → se borra.
- **Granularidad de slots**: cada 30 min (`CITA_DURACION_MIN`).

### 3.3 Modo "evento especial" (legacy/config.yaml `evento:`)

Cuarta opción del menú activable solo en fechas concretas (Navidad, San Valentín, etc.). Define fechas ISO y rangos horarios independientes del horario base. Útil cuando el negocio abre días raros para una campaña.

---

## 4. Modelo de datos del legacy

### 4.1 Formato del campo `description` de eventos Calendar

**Este es el "schema" sobre Calendar:**

```
Nombre: Juan García
Telefono: +34612345678
Servicio: corte | corte_barba | mechas
Estado: pendiente | confirmada
Recordatorio: no | sí
```

- Es el "interfaz de BD". Todo lo que el bot sabe de una cita vive aquí.
- Se parsea con regex tolerantes a espacios, mayúsculas, acentos, HTML inyectado por Calendar.
- Compatibilidad hacia atrás: `Tel:` se acepta como alias de `Telefono:`; `Reminder24h:` como alias de `Recordatorio:`.
- `Estado` y `Recordatorio` son **flags de idempotencia** que evitan reenvíos: los jobs marcan estos campos al ejecutar la acción.

### 4.2 Eventos `[CFG]` como overrides in-band

El title del evento es el mecanismo de configuración:

- `[CFG] CERRADO` → cualquier evento all-day cierra ese día.
- `[CFG] VACACIONES` → un evento all-day multi-día cierra todo el rango.
- `[CFG] HORARIO HH:MM-HH:MM` → ese día usa este rango como base, ignorando el horario semanal.

**Prioridad** (alta → baja):
1. `[CFG] CERRADO` / `[CFG] VACACIONES` → día completamente cerrado.
2. `[CFG] HORARIO` → sobreescribe el horario base.
3. `event_horario` (de `EVENTO_DIAS`) → modo evento especial.
4. `HORARIO_BASE` del día de la semana → fallback normal.

Implementado en `compute_slots()` ([engine.py](legacy/app/services/calendar/engine.py)).

### 4.3 El cache key

`slot_cache_key(d, mode, duracion_min, presencia_cliente_min)`:
- modo normal: `"YYYY-MM-DD_30_30"`
- modo evento: `"evt_YYYY-MM-DD_30_30"`

El prefijo `evt_` evita colisiones cuando un mismo día tiene horario distinto entre los dos modos. La invalidación selectiva usa `invalidate_matching(lambda k: k.startswith(date_str) or k.startswith(f"evt_{date_str}"))`.

---

## 5. Patrones de arquitectura que merecen sobrevivir

Cada uno tiene: **(a)** dónde vive en legacy, **(b)** qué problema resuelve, **(c)** cómo encaja en la nueva arquitectura.

### 5.1 `compute_slots()` como función PURA — el patrón más importante

- **Vive en**: [legacy/app/services/calendar/engine.py](legacy/app/services/calendar/engine.py)
- **Qué resuelve**: separar la lógica de "qué slots están libres" del "cómo se obtienen los eventos del calendario".
- **Por qué importa**: la función recibe `(d, events, duracion_min, presencia_cliente_min, event_horario)` y devuelve `List[str]`. Es testeable sin tocar APIs. Es 100% portable.
- **Nueva arquitectura**: este código se queda casi tal cual en `platform/data_plane/<connectors>/calendar/engine.py` o como helper del `CalendarConnector`. Es oro.

### 5.2 Repository (raw fetch) + Service (orquestación) — split del paquete `calendar/`

- **Vive en**: el paquete entero `legacy/app/services/calendar/` está dividido por responsabilidad:
  - `client.py` — auth, thread-local service, health check.
  - `repository.py` — fetches crudos de Calendar (list_for_day, list_for_range con paginación).
  - `engine.py` — funciones puras.
  - `service.py` — orquestación de booking (lock → re-check → create → invalidate).
  - `mutations.py` — escrituras (crear/cancelar/confirmar/marcar).
  - `queries.py` — lecturas de alto nivel para scheduler y cliente.
  - `caches.py` — TTLCache.
  - `locks.py` — SlotLockRegistry.
- **Qué resuelve**: separación clara de _IO_, _lógica pura_, y _orquestación_. Cada pieza testeable aislada.
- **Nueva arquitectura**: este es exactamente el shape que debería tener cualquier conector de calendario. Reproducir.

### 5.3 Booking atómico (anti-doble-reserva)

- **Vive en**: [legacy/app/services/calendar/service.py](legacy/app/services/calendar/service.py) → `reservar_cita()`.
- **Patrón**:
  ```
  acquire per-slot lock
    re-check slot_sigue_libre (con bypass_cache, fetch fresco)
    if libre:
      crear_cita
      invalidate_slot_cache(d)
      return (event_id, None)
    else:
      return (None, 'slot_taken')
  release lock
  ```
- **Qué resuelve**: race condition cuando dos clientes intentan reservar el mismo slot a la vez. La caché podría decir "libre" para ambos; el lock + re-check fresco mata la carrera.
- **Nueva arquitectura**: el patrón es genérico — cualquier operación de "reserva exclusiva" lo necesita (cita, asiento, mesa, plaza de gym). Conviene generalizar como helper en `platform/shared/`.

### 5.4 Per-phone lock — serialización por usuario

- **Vive en**: [legacy/app/handlers/conversation.py](legacy/app/handlers/conversation.py) → `_get_phone_lock()` + `_phone_locks` dict.
- **Qué resuelve**: WhatsApp puede entregar dos mensajes del mismo número en milisegundos (especialmente en retries). Sin lock, los handlers se pisan el `ConversationState`.
- **Nueva arquitectura**: necesario igual. En un container por tenant, el lock es por contacto. En la nueva arq probablemente `lock_by(tenant_id, contact_id)`.

### 5.5 Per-slot booking lock — anti-race global

- **Vive en**: [legacy/app/services/calendar/locks.py](legacy/app/services/calendar/locks.py).
- **Qué resuelve**: lo mismo que 5.3, granularidad (date, hora) en vez de phone.
- **Nota**: en la nueva arquitectura con un container por tenant, este lock vive **dentro** del container y solo cubre conversaciones del mismo tenant. Suficiente porque no hay clientes que compitan entre tenants por el mismo slot.

### 5.6 TTLCache thread-safe — patrón reutilizable

- **Vive en**: [legacy/app/services/calendar/caches.py](legacy/app/services/calendar/caches.py).
- **Características**: get/set/invalidate, invalidate_matching(predicate), purge_expired, contains, `raw_data` para shims.
- **Lo clave**: `invalidate_matching(predicate)` permite borrar todas las entradas de un día sin saber las combinaciones de duración/presencia.
- **Nueva arquitectura**: la clase se queda tal cual. Útil en cualquier componente que cache datos externos (Calendar slots, definiciones de flow, listas de contactos del CRM, etc.).

### 5.7 RateLimiter sliding-window

- **Vive en**: [legacy/app/utils/rate_limiter.py](legacy/app/utils/rate_limiter.py).
- **Implementación**: dict `key → list[timestamps]`, en cada `check()` filtra los timestamps fuera de la ventana y compara con `limit`.
- **Uso**: una instancia por IP (60 req/60s) y otra por phone (20 req/60s).
- **Nueva arquitectura**: idéntico patrón aplicable. Por tenant, por contacto, por conector — distintos rate limiters con distintos límites.

### 5.8 MessageDeduplicator

- **Vive en**: [legacy/app/utils/dedup.py](legacy/app/utils/dedup.py).
- **Qué resuelve**: WhatsApp reentrega webhooks en errores transitorios; sin dedup procesarías el mensaje dos veces.
- **Implementación**: dict `message_id → timestamp` con TTL, limpieza al consultar.
- **Nueva arquitectura**: necesario igual. En multi-tenant la key sería `(tenant_id, message_id)` o simplemente `message_id` global si los IDs de WhatsApp son únicos cross-tenant.

### 5.9 Semáforo de capacidad de handlers

- **Vive en**: [legacy/app/handlers/webhook.py](legacy/app/handlers/webhook.py) → `_handler_semaphore = threading.Semaphore(40)`.
- **Qué resuelve**: si el bot está sobrecargado y FastAPI `BackgroundTasks` crece sin control, se quedaría sin threads. El semáforo limita y dropea con métrica.
- **Nueva arquitectura**: aplica por container. Más sofisticado: cola asíncrona en lugar de semáforo.

### 5.10 HMAC verification del webhook

- **Vive en**: [legacy/app/handlers/webhook.py](legacy/app/handlers/webhook.py) → `_verify_signature()`.
- **Qué resuelve**: sin esto, cualquiera con la URL del webhook puede mandar mensajes falsos. Con HMAC, solo Meta puede llamar.
- **Detalles**:
  - Header: `X-Hub-Signature-256`.
  - Algoritmo: SHA-256 HMAC con `WHATSAPP_APP_SECRET`.
  - Comparación: `hmac.compare_digest()` (anti-timing-attack).
  - Si `APP_SECRET` no está configurado, se loggea warning y se permite (modo dev).
- **Nueva arquitectura**: imprescindible. Cada Channel Adapter debe verificar la firma de su proveedor.

### 5.11 Phone normalization

- **Vive en**: [legacy/app/utils/parser.py](legacy/app/utils/parser.py) → `parse_tel()`.
- **Reglas aplicadas**:
  1. Strip de `\s` y `\-` en el número.
  2. Strip del `+` inicial (WhatsApp envía sin `+`, el peluquero a veces lo escribe con).
  3. Si el resultado tiene **9 dígitos**, se prefija `34` (España sin código de país).
  4. Validación de rango: 7-15 dígitos (E.164).
- **Por qué importa**: sin esta normalización los `Telefono: +34...` escritos por el peluquero NO matchean los `34...` que envía WhatsApp en el `from`. **Bug histórico ya resuelto** — ver §10 Bug 3.
- **Nueva arquitectura**: cada Channel Adapter debe normalizar el identificador del usuario a un formato canónico que el resto del sistema use. Heredamos esta lógica para España y la generalizamos.

### 5.12 Snapshot-before-iteration

- **Vive en**: múltiples sitios. Ejemplo crítico: [legacy/app/handlers/conversation.py](legacy/app/handlers/conversation.py) `clean_expired_states()`.
- **Patrón**: `snapshot = list(d.items())` antes de iterar un dict compartido.
- **Qué resuelve**: si otro thread modifica el dict durante la iteración, CPython lanza `RuntimeError: dictionary changed size during iteration`. **Bug histórico** — §10 Bug 4.
- **Nueva arquitectura**: aplicable a cualquier estructura compartida. En la nueva arq con state persistente esto importa menos, pero el patrón vale para cualquier in-memory dict que se itere.

### 5.13 Thread-local API client

- **Vive en**: [legacy/app/services/calendar/client.py](legacy/app/services/calendar/client.py).
- **Patrón**: `threading.local()` con un service por thread, lazy-built.
- **Qué resuelve**: el cliente de googleapiclient no es thread-safe; construirlo por request es caro. Por thread es el balance: barato y seguro.
- **Nueva arquitectura**: aplicable a cualquier SDK no-thread-safe. Si nos vamos a async, este patrón se sustituye por un client async compartido.

### 5.14 Day-picker batched fetch

- **Vive en**: [legacy/app/handlers/conversation.py](legacy/app/handlers/conversation.py) → `_handle_book_select_service()`.
- **Patrón**: al entrar al day-picker, se hace **una** llamada a Calendar pidiendo el rango entero `[today, today+14]`. La función puebla el cache por día. Cuando el usuario elige un día concreto, ya es cache hit.
- **Qué resuelve**: 14 llamadas individuales serían 14× la latencia + cuota. Una llamada de rango es ~igual de cara pero amortizada.
- **Nueva arquitectura**: cualquier conector que ofrezca opciones múltiples al usuario debería aplicar este patrón "fetch en batch al entrar al picker, sirve del cache después".

### 5.15 Idempotency via Calendar event fields

- **Patrón**: el job de recordatorios solo manda si `Recordatorio: no` o ausente; el job de sync solo procesa si `Estado: pendiente`. Después de actuar, el job actualiza el campo. Si el job se ejecuta dos veces, la segunda no hace nada.
- **Implicación general**: en sistemas sin BD, el _estado_ del side-effect vive en el dato sobre el que actúas. Es elegante y robusto cuando funciona.
- **Nueva arquitectura**: en la nueva tendremos BD propia, pero el principio vale: las tareas automáticas deben tener un **idempotency key** que les permita auto-detectar si ya se ejecutaron.

### 5.16 Lifespan startup validation

- **Vive en**: [legacy/app/main.py](legacy/app/main.py) → `lifespan()` llama a `validate_config()` antes de aceptar requests.
- **Patrón**: fail-fast. Si falta una env var crítica, el proceso ni siquiera arranca — mejor que crashearse a medio servir un request.
- **Nueva arquitectura**: cada container debe hacer lo mismo al arrancar (validar config + health check de dependencias).

### 5.17 Health endpoint con estado degradado

- **Vive en**: [legacy/app/main.py](legacy/app/main.py) → `/health`.
- **Patrón**: 200 si todo OK, **503 si Calendar API no responde**. El cuerpo incluye `status: ok|degraded`. El watchdog usa esto.
- **Nueva arquitectura**: cada container debería exponerlo, y el Observability Aggregator del Control Plane lo consume.

### 5.18 Métricas en proceso (counters thread-safe)

- **Vive en**: [legacy/app/utils/metrics.py](legacy/app/utils/metrics.py).
- **API**: `metrics.inc('counter_name')` desde cualquier sitio del código.
- **Exposición**: `/metrics` endpoint sirve `get_all()` + uptime.
- **Counters reales del legacy**: `messages_received`, `bookings_created`, `bookings_cancelled`, `calendar_errors`, `whatsapp_errors`, `handler_dropped`, `scheduler_*_runs`.
- **Nueva arquitectura**: cada container emite métricas que el Observability Aggregator consume. El patrón `counters.inc(name)` se queda. La elección de backend (Prometheus, OTLP, etc.) es independiente de esta API.

### 5.19 Period split para el límite de 10 rows de WhatsApp

- **Vive en**: [legacy/app/handlers/conversation.py](legacy/app/handlers/conversation.py) → `_go_to_hour_select()`.
- **Patrón**: si hay >9 slots un día (típico: 16 cuando hay mañana + tarde), insertamos un paso intermedio "¿mañana o tarde?". Cada periodo entra holgadamente dentro del límite.
- **Importante**: NUNCA pasar `slots` directamente a `build_hours_list()` desde el handler — siempre vía `_go_to_hour_select()`. **Bug histórico** — §10 Bug 2.
- **Nueva arquitectura**: cualquier flow que ofrezca >9 opciones al usuario necesita un mecanismo similar de partición. La generalización vale como pattern del Bot Engine: "si el list-builder excede el límite del canal, insertar nodo intermedio de partición".

### 5.20 Watchdog como proceso separado

- **Vive en**: [legacy/watchdog.py](legacy/watchdog.py).
- **Patrón**: script standalone que corre desde cron cada 5 min. Lee `/health` y `/metrics` del bot. Mantiene `state.json` para cooldowns. Manda alertas WhatsApp via template `alerta_sistema`.
- **Lo clave**: NO importa nada de `app/`. Fully standalone. Si la app entera está rota, el watchdog sigue funcionando.
- **Nueva arquitectura**: el Observability Aggregator del Control Plane absorbe esta función, pero el principio de "monitor desacoplado del sistema que monitorea" vale.

### 5.21 Tests con mocks completos

- **Vive en**: [legacy/tests/conftest.py](legacy/tests/conftest.py) + 14 ficheros.
- **Patrón**: todas las APIs externas (Calendar, WhatsApp, httpx) están mockeadas. Los tests corren sin credenciales y sin red.
- **Fixtures clave**: `mock_wa` (parchea las 3 funciones de send_*), `mock_cal` (parchea las funciones de cal usadas por conversation), `make_event()` y `make_cita_description()` helpers.
- **Nueva arquitectura**: misma estrategia. Los ports tienen fakes; los tests usan fakes.

---

## 6. Gotchas y aprendizajes específicos

### 6.1 WhatsApp Cloud API

- **Webhook debe ACK en ≤5 segundos.** Por eso `/webhook` POST devuelve 200 inmediatamente y delega a `BackgroundTasks`. Si tardamos más, Meta reentrega.
- **Interactive button**: máximo **3 botones**, título **20 chars**, id **256 chars**.
- **Interactive list**: máximo **10 rows totales** (sumando todas las sections), título de row **24 chars**, descripción **72 chars**, button label **20 chars**.
- **Text message**: máximo **4096 chars**.
- **Templates** (mensajes proactivos fuera de 24h): hay que crearlos en Meta Business Suite y esperar aprobación (1-48h). Categorías `UTILITY` para nuestros casos.
- **Components** de template: `header`, `body`, `button` (con `sub_type: quick_reply`, `index`, payload).
- **Token permanente** vs **temporal de 24h**: el temporal es trampa, en producción _siempre_ permanente.
- **HTTP 401** = token caducado/revocado → manda nuevo, actualiza `.env`, reinicia.
- **HTTP 4xx** en sends = bad payload o template no aprobado — NO reintentar.
- **HTTP 5xx** = transitorio — reintentar con backoff exponencial (1s, 2s).
- **No loggear el cuerpo de las respuestas 4xx** — pueden contener tokens.

### 6.2 Google Calendar API

- **Scope mínimo**: `calendar.events` (no necesitamos metadata del calendario).
- **Service Account** auth — más cómoda que OAuth para apps backend.
- **All-day events**: el campo `end.date` es **EXCLUSIVO** (Google convention). Si un evento es del 20 al 22, `end.date` es `2026-12-23`. Iterar con `while d < end_d`.
- **Paginación** via `nextPageToken`. El legacy capea en 5 páginas para evitar runaway loops.
- **`num_retries=2`** en cada `.execute()` — la library lo gestiona internamente.
- **`fields=`** en queries para limitar payload (ej: `items(id,summary,description,start,end)`).
- **HTML inyectado en descriptions** — Google Calendar puede meter `<br>`, `<p>`, etc. cuando se edita desde la UI. El parser hace `_strip_html()` antes de regex.
- **`singleEvents=true`** expande eventos recurrentes en instancias individuales — fundamental.
- **`orderBy='startTime'`** requiere `singleEvents=true`.
- **Calendar como DB tiene un coste**: cada decisión de booking = ~2 llamadas API. Para 100 reservas/día está bien; para 10k/día sería un problema.

### 6.3 Datetime y timezone

- **TODO el sistema usa `Europe/Madrid` aware datetimes.** Nunca naïve.
- `TZ.localize(datetime(...))` para crear aware desde naïve.
- `.astimezone(TZ)` cuando llega un datetime de Calendar (puede venir en cualquier offset).
- **DST**: pytz lo maneja transparentemente — no asumir 1h fija de offset.

### 6.4 Concurrencia

- `_states` dict compartido entre `handle_message` (read-write) y `clean_expired_states` (delete) → snapshot-then-iterate.
- `_phone_locks` dict tiene su propio guard lock (`_phone_locks_guard`) para inicialización thread-safe.
- `metrics._lock` protege el dict de counters.
- Cada uso de un dict compartido entre threads en este código tiene su lock — buscar todos los `threading.Lock()` para inventariarlos.

### 6.5 Parseo de texto del usuario

- **Acentos**: `parse_*` aplica `_norm()` que strippea acentos vía `unicodedata.normalize('NFD')` + filtrado de combining marks. Así `sí`, `si`, `Sí`, `SÍ` se comparan iguales.
- **HTML entities**: `html.unescape()` (`&amp;` → `&`, `&nbsp;` → ` `).
- **Em-dash vs hyphen**: en títulos `'Corte - Juan'` el separador puede ser `-`, `–`, `—`. Se normaliza.

### 6.6 ngrok / nginx

- **ngrok**: gratis con dominio estático reservado. URL fija → Meta no se entera de reinicios.
- **nginx**: certificado autofirmado (10 años) basta — Meta solo exige HTTPS, no CA pública.
- **Puerto 8000 de uvicorn nunca se expone** — siempre detrás de túnel.

---

## 7. WhatsApp Cloud API — apuntes técnicos

### 7.1 Verificación del webhook (GET handshake)

Meta llama con query params al configurar el webhook:
```
GET /webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>
```
Si `hub.mode == "subscribe"` y `hub.verify_token == WHATSAPP_VERIFY_TOKEN`, responder con `challenge` en plain text.

### 7.2 HMAC del POST

Header: `X-Hub-Signature-256: sha256=<hex>`.
```python
expected = hmac.new(APP_SECRET, body_bytes, hashlib.sha256).hexdigest()
received = signature_header.removeprefix("sha256=")
hmac.compare_digest(expected, received)
```

### 7.3 Estructura del payload entrante

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{
          "id": "<message_id>",
          "from": "<phone_E164_sin_+>",
          "type": "text" | "interactive" | "audio" | ...,
          "text": {"body": "..."},
          "interactive": {
            "type": "button_reply" | "list_reply",
            "button_reply": {"id": "...", "title": "..."},
            "list_reply": {"id": "...", "title": "..."}
          }
        }]
      }
    }]
  }]
}
```

### 7.4 Estructura de envío

```python
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": phone,
  "type": "text" | "interactive" | "template",
  "text": {"body": text, "preview_url": False},
  "interactive": {...},
  "template": {"name": "...", "language": {"code": "es"}, "components": [...]}
}
```

POST a `https://graph.facebook.com/v19.0/{phone_number_id}/messages`.

### 7.5 Templates: components

```python
[
  {"type": "body", "parameters": [{"type": "text", "text": "valor1"}, ...]},
  {"type": "button", "sub_type": "quick_reply", "index": "0",
   "parameters": [{"type": "payload", "payload": "reminder_confirm_<id>"}]},
  ...
]
```

### 7.6 Connection pooling

`httpx.Client(timeout=10)` reutiliza conexiones TCP entre requests. Más eficiente que crear cliente por llamada.

---

## 8. Google Calendar API — apuntes técnicos

### 8.1 Auth (service account)

```python
creds = service_account.Credentials.from_service_account_file(path, scopes=['.../calendar.events'])
http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
service = build('calendar', 'v3', http=http, cache_discovery=False)
```

`cache_discovery=False` desactiva el cache local de discovery (evita warning y problemas en lecturas concurrentes).

### 8.2 Listar eventos de un día

```python
service.events().list(
    calendarId=GOOGLE_CALENDAR_ID,
    timeMin=day_start.isoformat(),
    timeMax=day_end.isoformat(),
    singleEvents=True,
    orderBy='startTime',
    fields='items(id,summary,description,start,end)',
).execute(num_retries=2)
```

### 8.3 Listar en rango con paginación

```python
while pages_fetched < max_pages:
    kwargs = {...}
    if page_token: kwargs['pageToken'] = page_token
    result = service.events().list(**kwargs).execute(num_retries=2)
    pages_fetched += 1
    # ... procesar items ...
    page_token = result.get('nextPageToken')
    if not page_token: break
```

### 8.4 Crear evento

```python
event = {
    'summary': f"{servicio['nombre']} - {nombre}",
    'description': description_with_fields,
    'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Madrid'},
    'end':   {'dateTime': end_dt.isoformat(),   'timeZone': 'Europe/Madrid'},
}
created = service.events().insert(calendarId=..., body=event).execute(num_retries=2)
event_id = created['id']
```

### 8.5 Update / patch / delete

```python
# Update: lee evento, modifica, escribe entero
event = service.events().get(...).execute()
event['description'] = set_field(event['description'], 'Estado', 'confirmada')
service.events().update(calendarId=..., eventId=..., body=event).execute()

# Delete
service.events().delete(calendarId=..., eventId=...).execute()
```

### 8.6 Manejo de all-day vs timed

```python
if 'date' in event['start']:    # all-day
    start_d = date.fromisoformat(event['start']['date'])
    end_d = date.fromisoformat(event['end']['date'])  # EXCLUSIVO
    # iterar: d = start_d; while d < end_d: ...
else:                            # timed
    start_dt = datetime.fromisoformat(event['start']['dateTime']).astimezone(TZ)
    end_dt   = datetime.fromisoformat(event['end']['dateTime']).astimezone(TZ)
```

---

## 9. La conversación del bot (state machine completa)

> Esta sección documenta el flow concreto del bot de peluquería como **referencia de qué se siente un flow completo**. En la nueva arquitectura este flow se vuelve datos (YAML/JSON), no código.

### 9.1 Estados

| Estado | Qué espera | Botones / inputs válidos |
|--------|-----------|--------------------------|
| `MENU` | Botón del menú principal | `menu_book` / `menu_view` / `menu_cancel` / `menu_book_event` (si EVENTO_ACTIVO) |
| `BOOK_SELECT_SERVICE` | Botón de servicio | `service_<key>` / `back_to_menu` |
| `BOOK_SELECT_DAY` | Botón de día | `day_<YYYY-MM-DD>` / `back_to_menu` |
| `BOOK_SELECT_PERIOD` | Mañana/tarde | `period_morning` / `period_afternoon` / `back_to_day` |
| `BOOK_SELECT_HOUR` | Botón de hora | `hour_<YYYY-MM-DD>_<HHMM>` / `back_to_day` / `back_to_period` |
| `BOOK_ENTER_NAME` | **Texto** (nombre) | Texto 2-100 chars |
| `VIEW_APPOINTMENTS` | Cualquier botón | `back_to_menu` o cualquier otro → menú |
| `CANCEL_SELECT` | Botón de cita | `cancel_appt_<event_id>` / `back_to_menu` |

### 9.2 Reglas globales

- **`back_to_menu` desde cualquier estado** → reset + menú.
- **Botones de respuesta a recordatorio** se procesan independiente del estado:
  - `reminder_confirm_<event_id>` → `confirmar_cita`
  - `reminder_cancel_<event_id>` → `cancelar_cita`
- **Texto fuera de MENU y BOOK_ENTER_NAME** → reset a menú.
- **Botón en BOOK_ENTER_NAME** (que esperaba texto) → reset a menú.
- **Tipo no soportado** (audio, imagen) → texto sintético `"__unknown__"` → reset a menú.
- **Comando `/estado`** del `ADMIN_PHONE` → informe de sistema (intercept antes de routing).

### 9.3 Path principal — "Pedir cita"

```
MENU
  → click "Pedir cita" (menu_book)
  → BOOK_SELECT_SERVICE
    → click servicio (service_corte | service_corte_barba | service_mechas)
    → batch-fetch slots de [today, today+14d]
    → si no hay días disponibles → mensaje + menú
    → BOOK_SELECT_DAY (lista de días)
      → click día
      → si día tiene SOLO mañana o SOLO tarde → BOOK_SELECT_HOUR directo
      → si día tiene ambos → BOOK_SELECT_PERIOD
        → click mañana/tarde
        → BOOK_SELECT_HOUR
          → click hora
          → BOOK_ENTER_NAME (espera texto)
            → escribe nombre (2-100 chars)
            → reservar_cita(lock → re-check → crear)
              → si OK → mensaje confirmación + menú
              → si slot_taken → re-pick hora (con period-split si aplica)
              → si error API → mensaje error + menú
```

### 9.4 Path "Mis citas"

```
MENU → menu_view → fetch get_citas_futuras(phone) → mostrar lista no-interactiva → cualquier botón = back to menu
```

### 9.5 Path "Cancelar cita"

```
MENU → menu_cancel → fetch get_citas_futuras(phone)
  → si no tiene citas → mensaje + menú
  → CANCEL_SELECT (lista de citas)
    → click cita
    → cancelar_cita(event_id) (delete en Calendar)
    → mensaje OK + menú
```

### 9.6 Path manual del peluquero

```
Peluquero crea evento en Calendar con:
  Telefono: +34XXX
  Estado: pendiente (o ausente, se asume pendiente)

Job sync_citas_manuales (cada 60 min):
  → get_eventos_manuales_sin_confirmar()  ← filtra por Telefono + Estado: pendiente
  → para cada evento:
    → send_template('confirmacion_cita', ...) con quick_reply button
    → marcar_manual_confirmado(event_id) → set Estado: confirmada + Recordatorio: no

Cliente recibe template y puede pulsar "Cancelar cita":
  → reminder_cancel_<event_id> → cancelar_cita
```

### 9.7 Path recordatorio

```
Job enviar_recordatorios (cada 60 min):
  → get_citas_para_recordatorio()  ← filtra por Telefono + Recordatorio: no/ausente + Estado: pendiente/confirmada
  → ventana de tiempo: now+23h ≤ start ≤ now+25h
  → para cada cita:
    → send_template('recordatorio_cita', ...) con 2 quick_reply buttons (Confirmar / Cancelar)
    → marcar_recordatorio_enviado(event_id) → set Recordatorio: sí

Cliente pulsa:
  → reminder_confirm_<id> → confirmar_cita (set Estado: confirmada)
  → reminder_cancel_<id> → cancelar_cita (delete)
```

---

## 10. Bugs ya resueltos (no repetirlos)

Documentados en [legacy/tests/test_regression.py](legacy/tests/test_regression.py). Cada uno ya tiene su test — pero el conocimiento debe sobrevivir aunque el código no.

### Bug 1 — `confirmar_cita` return value ignorado

**Síntoma**: cliente pulsa "Confirmar" en recordatorio → recibe mensaje "Confirmada ✅" aunque la actualización de Calendar haya fallado.

**Causa**: handler no checkeaba el `bool` que devuelve `confirmar_cita`.

**Fix**: siempre verificar return value de mutations y devolver mensaje de error si False.

**Lección general**: cuando una operación pueda fallar silenciosamente, su API debe devolver éxito/fallo y el caller debe diferenciar UX según el resultado.

### Bug 2 — Recovery de `slot_taken` enviaba TODOS los slots del día a `build_hours_list`

**Síntoma**: cliente llega a confirmar, el slot ya está cogido, el bot le ofrece otra hora — pero si el día tiene >9 slots (mañana+tarde), WhatsApp rechaza el mensaje por exceder 10 rows.

**Causa**: el código de recovery pasaba `slots` directo a `build_hours_list()` saltándose el period-split.

**Fix**: usar `_go_to_hour_select()` que aplica el split automáticamente.

**Lección general**: helpers que enforcen los límites del canal deben ser obligatorios, no opcionales. Una API que se puede saltar acabará saltándose.

### Bug 3 — Phone con `+` no matcheaba

**Síntoma**: el peluquero escribe `Telefono: +34600000001` en Calendar; el cliente con número `34600000001` (WhatsApp envía sin `+`) no encuentra su cita.

**Causa**: comparación string directa.

**Fix**: `parse_tel()` strippea el `+` y normaliza a 9-digit → prefijo `34`.

**Lección general**: cualquier identificador que pueda venir en distintos formatos necesita una función canónica de normalización aplicada en ambos lados de la comparación.

### Bug 4 — `clean_expired_states` raceaba con `handle_message`

**Síntoma**: `RuntimeError: dictionary changed size during iteration` esporádico.

**Causa**: iterar `_states.items()` mientras otro thread añadía/eliminaba claves.

**Fix**: `snapshot = list(d.items())` antes de iterar.

**Lección general**: cualquier dict compartido entre threads que se itere debe snapshotearse primero. Vale incluso con GIL.

### Bug 5 — Sin max length en el nombre

**Síntoma**: usuario malicioso o accidental podía mandar 100kb como "nombre", explotaba en el campo summary de Calendar.

**Fix**: `_NOMBRE_MAX_LEN = 100`, validación antes de aceptar.

**Lección general**: TODO input de usuario tiene que tener max length explícito. Calendar summary admite 1024 bytes pero 100 chars es suficiente para nombres reales y deja margen.

### Bug 6 — Confirm sin selected_date crasheaba

**Síntoma**: si por alguna razón el estado llega corrupto (`selected_date is None` o `selected_slot is None`), el handler crasheaba con AttributeError al construir el evento.

**Fix**: guard explícito al inicio de `_handle_book_enter_name` — si state incompleto, log + reset a menú.

**Lección general**: estados in-memory pueden corromperse por race conditions, restarts a medias, bugs corregidos donde queda estado viejo. Defensa en handlers críticos.

---

## 11. Tests como documentación de edge cases

Algunos tests merecen sobrevivir como **especificación** del comportamiento esperado, aunque el código se reescriba.

### Tests imprescindibles de portar

| Test file legacy | Qué documenta |
|------------------|---------------|
| [test_regression.py](legacy/tests/test_regression.py) | Los 6 bugs históricos — su NO-repetición es contractual |
| [test_calendar_unified_flow.py](legacy/tests/test_calendar_unified_flow.py) | Cache keys separados por modo (normal vs evento) + last-slot must finish before closing |
| [test_parser.py](legacy/tests/test_parser.py) | Tolerancia a acentos, HTML, formato del teléfono, `[CFG]` con en-dash/em-dash |
| [test_slots.py](legacy/tests/test_slots.py) | OVERLAP_TOLERANCE_SECONDS = 60 (eventos justo en boundary no bloquean) |
| [test_ttl_cache.py](legacy/tests/test_ttl_cache.py) | invalidate_matching, purge_expired, concurrencia |
| [test_rate_limiter.py](legacy/tests/test_rate_limiter.py) | Sliding window correcto, reset() |
| [test_message_deduplicator.py](legacy/tests/test_message_deduplicator.py) | TTL, idempotencia |
| [test_interactive.py](legacy/tests/test_interactive.py) | Que ningún builder exceda 10 rows / 3 buttons / max chars |
| [test_webhook.py](legacy/tests/test_webhook.py) | HMAC verification, validación de phone, rate limiting, dedup |

### Patterns de fixtures que merecen sobrevivir

- `aware_dt(year, month, day, hour, minute)` — datetime aware de Madrid.
- `make_event(...)` — factory de eventos Calendar mockeados con todos los campos.
- `make_cita_description(...)` — factory de descripciones con los 4-5 campos.
- `mock_wa` / `mock_cal` — fixtures que patchean las funciones de envío en bulk.
- `clear_states` autouse fixture — limpia `_states` y `_phone_locks` entre tests.

---

## 12. Operaciones y despliegue — qué vale como referencia

### 12.1 Stack de despliegue del legacy

```
Google Cloud VM (e2-micro, Ubuntu 22.04, us-east1)
  ├── systemd: peluqueria.service     ← uvicorn 127.0.0.1:8000
  ├── systemd: ngrok.service          ← túnel HTTPS (Opción A)
  │   OR
  ├── systemd: nginx.service          ← proxy 443 → 8000 (Opción B)
  ├── systemd: peluqueria-restart.timer  ← reinicio nocturno 04:00
  ├── cron:    watchdog.py            ← cada 5 min
  └── ufw firewall                    ← solo 22, 80, 443
```

### 12.2 Lo que vale como inspiración para la nueva plataforma

| Patrón legacy | Aplicación en la nueva arquitectura |
|---------------|-------------------------------------|
| **systemd service** con `Restart=always` | El proceso del Control Plane se gestiona así en la VM |
| **Reinicio nocturno (04:00 daily)** | Aplica también a containers del Data Plane — limpia leaks, refresca creds |
| **`EnvironmentFile=.env` en systemd** | Patrón de inyección de secretos para el Control Plane |
| **`StandardOutput=journal`** | Logs estructurados → journald → Observability Aggregator |
| **Watchdog separado del proceso monitoreado** | El Observability del Control Plane es independiente del Data Plane |
| **`/health` que devuelve 503 cuando degraded** | Cada container del Data Plane lo expone, Aggregator lo consume |
| **`make update` = git pull + pip install + restart** | El Tenant Orchestrator hace el equivalente: pull imagen + redeploy |
| **HMAC obligatorio en producción** | Cada Channel Adapter de cada container lo aplica |
| **UFW: solo 22, 80, 443** | El container expone solo el puerto del webhook, nada más |
| **Certificado autofirmado nginx** | Si se elige ese path; mejor un proxy frontal del provider |
| **ngrok como opción de desarrollo** | Patrón válido para desarrollo local del Data Plane |

### 12.3 Recursos externos necesarios (Google Cloud + Meta)

Documentado paso a paso en [legacy/deploy.md](legacy/deploy.md). Lo que el cliente final debe traer al onboarding:

**Google Cloud (para conector Calendar):**
1. Cuenta Google Cloud + proyecto
2. Google Calendar API activada
3. Service Account con JSON key
4. Calendario compartido con el client_email de la Service Account (permisos de edición)
5. Calendar ID

**Meta WhatsApp Business (para canal WhatsApp):**
1. Cuenta Meta Business
2. App de tipo Business
3. Producto WhatsApp añadido
4. Número de teléfono verificado
5. Phone Number ID + Access Token PERMANENTE
6. App Secret
7. Templates aprobados (`confirmacion_cita`, `recordatorio_cita`, `alerta_sistema`)

**Importante**: los templates tardan 1-48h en aprobarse. Onboarding debe contemplar este lead time.

### 12.4 Templates de WhatsApp definidos en producción

| Template | Categoría | Parámetros | Botones |
|----------|-----------|------------|---------|
| `confirmacion_cita` | UTILITY | nombre, fecha, hora | `Cancelar cita` (payload: `reminder_cancel_{id}`) |
| `recordatorio_cita` | UTILITY | fecha, hora | `Confirmar` + `Cancelar` (payloads: `reminder_confirm_{id}` / `reminder_cancel_{id}`) |
| `alerta_sistema` | UTILITY | label, timestamp, detail | (sin botones) |

---

## 13. Mapping: legacy → nueva arquitectura

### 13.1 Por componente de la nueva arquitectura

| Componente nuevo | De qué legacy se nutre |
|------------------|------------------------|
| **Channel Adapter — WhatsApp** | `legacy/app/services/whatsapp.py` (impl), `legacy/app/handlers/webhook.py` (HMAC + validación), `legacy/app/utils/dedup.py`, `legacy/app/utils/rate_limiter.py`, `legacy/app/utils/interactive.py` (builders) |
| **Connector — Calendar (Google adapter)** | `legacy/app/services/calendar/` (todo el paquete: client, repository, engine, mutations, queries, caches, locks, service) |
| **Engine de slots (helper del calendar connector)** | `legacy/app/services/calendar/engine.py` + `legacy/app/utils/slots.py` |
| **Parsing helpers del calendar connector** | `legacy/app/utils/parser.py` |
| **Bot Engine — concurrency** | Patrón de per-phone lock de `legacy/app/handlers/conversation.py` |
| **Bot Engine — flow ejecutor** | La _estructura_ (state + dispatch + transitions) de `legacy/app/handlers/conversation.py`. El _contenido_ (estados concretos) NO se porta. |
| **Bot Engine — state model** | El dataclass `ConversationState` como referencia |
| **Task Scheduler (Control Plane)** | Lógica de los 3 jobs de `legacy/app/services/scheduler.py` como ejemplos de qué tipo de task definitions debe soportar el scheduler genérico |
| **Observability Aggregator** | `legacy/app/utils/metrics.py` (interfaz), `legacy/watchdog.py` (qué monitorizar) |
| **Health check pattern** | `legacy/app/main.py` `/health` |
| **Admin Panel — comando /estado** | `legacy/app/utils/admin.py` como ejemplo |
| **Config loading + validation** | `legacy/app/config.py` `_load_and_validate_yaml()` — patrón aplicable a config de tenant |
| **Logging setup** | `legacy/app/main.py` `_setup_logging()` |
| **Tests del Data Plane** | Patrón de mocking en `legacy/tests/conftest.py` |

### 13.2 Por dependencia externa del legacy

| Paquete pip | Probable uso futuro |
|-------------|---------------------|
| `fastapi==0.111.0` | Sigue siendo elección razonable para el Data Plane |
| `uvicorn==0.30.1` | Idem |
| `python-dotenv==1.0.1` | Local dev solo; en runtime las creds vienen del Control Plane |
| `google-api-python-client==2.131.0` | Sigue valiendo para GoogleCalendarAdapter |
| `google-auth==2.29.0` | Idem |
| `httpx==0.27.0` | Sigue valiendo (probablemente con `AsyncClient` en la nueva) |
| `apscheduler==3.10.4` | Probablemente sustituido — Task Scheduler genérico necesita más capacidades |
| `pytz==2024.1` | Considerar reemplazar por `zoneinfo` (stdlib desde Python 3.9) |
| `pyyaml==6.0.2` | Sigue valiendo para parsing de configs |
| `psutil>=5.9.0` | Para system metrics; vale tal cual |

---

## 14. Lo que NO se porta y por qué

| Pieza del legacy | Por qué no se porta |
|------------------|---------------------|
| **Las constantes de estado** (`MENU`, `BOOK_SELECT_SERVICE`, etc.) en `conversation.py` | Es el flow específico de peluquería. En la nueva arquitectura los flows son datos importados. Esto se convierte en el primer ejemplo de flow declarativo en `platform/control_plane/`. |
| **Los textos en español** de `utils/messages.py` y `utils/interactive.py` | Hardcoded al dominio. En la nueva arquitectura los textos viven en la config del tenant. |
| **`config.py` como mecanismo de "una sola fuente YAML global"** | Single-tenant. La nueva carga config del Control Plane. |
| **`_states: dict` in-memory** | El estado en la nueva es durable. La interfaz puede ser similar (`StateStore.get/set/delete`) pero la implementación cambia. |
| **`/estado` admin command bypass** | El admin se gestiona desde el Admin Panel, no desde dentro del bot. |
| **`watchdog.py` como cron separado** | Su función la absorbe el Observability Aggregator del Control Plane. El patrón "monitor desacoplado" se preserva como principio. |
| **`generar_qr.py`** | Tool de marketing, no parte de la plataforma. Puede vivir como tool del Admin Panel o desaparecer. |
| **El `Makefile` entero** | El Tenant Orchestrator del Control Plane reemplaza todo lo de provisioning. Los snippets de systemd valen como inspiración. |
| **`deploy.md`** completo | Su equivalente para la nueva plataforma será diferente — single VM Control Plane + provider-managed Data Plane. Los pasos de "alta en Google Cloud" y "alta en Meta" se vuelven UI en el Admin Panel para el cliente. |
| **`SERVICIOS` hardcoded** | Es config de tenant. Cada cliente define sus servicios. |
| **`HORARIO_BASE` hardcoded** | Idem. |
| **`EVENTO_DIAS` hardcoded** | Idem — pero el concepto de "días especiales con horario distinto" es generalizable y puede vivir en la definición del flow. |
| **El concepto "Calendar como única fuente de verdad" para estado de cita** | En la nueva, la cita vive en el conector calendar (Calendar/Cal.com/lo que sea); el estado operativo (Estado/Recordatorio flags) vive en BD propia del tenant. El conector solo guarda lo que aplica al sistema externo. |

---

## 15. Criterio para borrar `legacy/`

Borrar el directorio `legacy/` solo cuando se cumplan **todos** estos puntos:

### Funcionalidad portada

- [ ] Channel Adapter WhatsApp implementado con HMAC, dedup, rate limit y interactive builders.
- [ ] `CalendarConnector` (categoría) implementado, con `GoogleCalendarAdapter` como primera implementación.
- [ ] Bot Engine puede ejecutar un flow declarativo que cubra todos los paths del bot legacy (book / view / cancel / event-mode / reminder responses).
- [ ] Task Scheduler genérico ejecuta las 3 tareas equivalentes: sync manual + recordatorios + cleanup.
- [ ] Health endpoint + métricas básicas implementados en cada container.
- [ ] Observability Aggregator recibe logs/metrics/audit.
- [ ] Admin Panel permite dar de alta un tenant con su flow + sus credenciales.

### Tests portados

- [ ] Los 6 tests de [test_regression.py](legacy/tests/test_regression.py) reescritos contra la nueva arquitectura y pasando.
- [ ] Tests de cache, rate limiter, dedup, parser portados.
- [ ] Test end-to-end de un booking completo en la nueva plataforma pasa.

### Validación funcional

- [ ] Un tenant real (puede ser el de la peluquería original) corre en la nueva plataforma sin regresiones funcionales respecto al legacy.
- [ ] El cliente final hace una reserva por WhatsApp y aparece en Calendar (mismo formato de descripción con `Nombre/Telefono/Servicio/Estado/Recordatorio`).
- [ ] El peluquero crea una cita manual en Calendar y el cliente recibe la confirmación por WhatsApp.
- [ ] Un recordatorio se envía 24h antes correctamente.
- [ ] El admin recibe una alerta cuando se simula una caída del Calendar.

### Conocimiento preservado

- [ ] `legacy.md` (este documento) está actualizado con todo lo aprendido durante la migración.
- [ ] Los 6 bugs históricos de `test_regression.py` están documentados como tests en la nueva suite (no solo en este doc).
- [ ] Las decisiones de negocio (servicios, horarios, distinción `duracion_min` vs `presencia_cliente_min`, eventos `[CFG]`) están reflejadas en la config del tenant migrado.

### Backup

- [ ] Se ha creado un tag git `legacy-final` apuntando al último commit antes de borrar `legacy/`.
- [ ] El `legacy.md` está commiteado en `main`.

---

## Apuntes finales

### Lo más valioso del legacy

Si tuviera que destacar **tres** cosas que el legacy hace mejor que muchos sistemas con 10× su complejidad:

1. **`compute_slots()` como función pura**. La separación entre fetching y compute hace todo testeable sin red.
2. **El paquete `calendar/` bien descompuesto**. Repository / engine / mutations / queries / service / caches / locks es un blueprint a copiar tal cual.
3. **El patrón booking atómico (lock → re-check → create → invalidate)**. Cualquier sistema con "reservas exclusivas" lo necesita y este lo resuelve limpio.

### Lo más doloroso del legacy

1. **Calendar como BD**. Funciona para una peluquería; no escala a 100. El parsing de `description` para sacar `Estado: confirmada` no es BD — es schema-on-read sobre texto libre.
2. **Estado in-memory**. Un restart = todos los clientes pierden su conversación a medias.
3. **Multi-tenant imposible sin refactor**. Cada `os.getenv()` en `config.py` es un acoplamiento a "una instalación = un negocio".

### Filosofía

El legacy es un **producto terminado y battle-tested** para un caso de uso (una peluquería). La nueva arquitectura es una **plataforma** para N casos de uso. La distancia entre ambos no es de _más código_ — es de _otro tipo de código_: genérico, configurable, multi-tenant, escalable horizontalmente.

Mirar legacy mientras se escribe la nueva plataforma es mirar **la implementación de referencia de una instancia**. Ese marco mental lo hace más útil que tratarlo como "código viejo a refactorizar".

---

> **Mantenimiento de este documento.** Mientras `legacy/` exista, este documento es la _guía de la guarida_. Cada vez que se porta algo, actualizar las secciones correspondientes. Cuando se borre `legacy/`, este documento se queda como reliquia útil para el debugging futuro de "¿cómo se hacía esto antes?".
