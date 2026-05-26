# Plan de Implementación — Plataforma de Bots

> **Documento operativo.** Acompaña a `arquitectura.md`. Mientras aquel describe el _qué_ y el _por qué_, este describe el _cómo_ y el _cuándo_. Se ejecuta de arriba a abajo, una fase a la vez. Solo se avanza cuando la fase actual cumple su _definición de hecho_.

---

## 0. Filosofía del plan
 
1. **Vertical slices, no capas.** Antes que tener "todos los componentes a medias", se busca tener pocas funcionalidades end-to-end y completas. Esto da feedback real desde el día 1.
2. **Cada fase termina en algo demostrable.** Hay una _Definición de hecho_ verificable. Sin ella, la fase no está cerrada.
3. **Decisiones se toman en la fase donde aplican**, no antes. El doc de arquitectura tiene marcadas las _"A investigar"_ — esta guía indica en qué fase se cierra cada una.
4. **No se reescribe la arquitectura mientras se implementa.** Si surge una restricción real que invalida una decisión, se vuelve al doc, se actualiza, y _entonces_ se sigue. El código no diverge del doc.
5. **El bot actual de peluquería es referencia, no destino.** Su código vive en `legacy/` como prueba de concepto. La plataforma se construye limpia.
6. **Muy poco a poco.** Cada fase es pequeña, ejecutable en sesiones cortas. Si una fase parece grande, se subdivide.

---

## 1. Roadmap general

| Hito | Fases | Outcome al cerrar |
|------|-------|-------------------|
| **M1 — Foundation** | F0 | Repo listo, stack decidido, scaffolding mínimo arrancando |
| **M2 — Bot mono-tenant end-to-end** | F1, F2, F3, F4, F5 | Un bot funcional (estilo peluquería) corriendo sobre la nueva arquitectura, con config hardcoded |
| **M3 — Multi-tenant con Control Plane** | F6, F7, F8 | Dos tenants distintos sirviendo desde la misma imagen, configurados desde el Control Plane |
| **M4 — Task Scheduler** | F9 | Recordatorios y tareas programadas funcionan vía push, con cancelación |
| **M5 — Observabilidad y Orchestrator** | F10, F11 | Trazas end-to-end + alta de tenant 100% automatizada |
| **M6 — Admin Panel y Hardening** | F12, F13 | Gestión humana de la plataforma vía UI + sistema preparado para producción real |

---

## 2. Hitos y Fases

---

### Hito M1 — Foundation

#### Fase 0 — Scaffolding y stack tecnológico

**Objetivo.** Decidir el stack mínimo viable, dejar el repo arrancable, instalar tooling de desarrollo.

**Decisiones a tomar en esta fase.**
- Lenguaje y versión (asumido: Python 3.11+).
- Framework web del Control Plane y de los containers (FastAPI vs litestar vs otro).
- Base de datos del Control Plane (Postgres por defecto).
- Gestor de dependencias (poetry, pdm, uv).
- Formato preliminar del flow (YAML por defecto, sin compromiso firme).
- Layout final del monorepo dentro de `platform/`.

**Tareas.**
1. Confirmar layout: `platform/control_plane/`, `platform/data_plane/`, `platform/shared/`, `platform/tests/`.
2. Dentro de `shared/`: ubicación para tipos compartidos, ports/interfaces, utilidades comunes.
3. `pyproject.toml` (o equivalente) con dependencias mínimas y comandos básicos (lint, format, test).
4. Hook de pre-commit con linter + formateador.
5. CI mínimo (lint + tests vacíos) que pase desde el primer commit.
6. `Makefile` (o equivalente) con comandos canónicos: `run`, `test`, `lint`, `format`.
7. Endpoint trivial en `control_plane/` y en `data_plane/` que devuelva `{"status":"ok"}` — solo para validar que ambos arrancan.

**Definición de hecho.**
- `make run-control-plane` arranca un servicio que responde `200` en `/health`.
- `make run-data-plane` arranca un servicio que responde `200` en `/health`.
- `make test` pasa (aunque solo haya 1 test trivial).
- `make lint` pasa.

**Fuera de alcance.**
- Cualquier lógica de dominio.
- Cualquier conexión entre planos.
- Cualquier base de datos real.

---

### Hito M2 — Bot mono-tenant end-to-end

> Objetivo del hito: tener un bot funcional sobre la nueva arquitectura **sin Control Plane**. Toda la config está hardcoded en el container. Sirve como prueba de que el diseño hexagonal y las abstracciones funcionan.

#### Fase 1 — Bot Engine standalone

**Objetivo.** Construir el motor genérico que ejecuta flows. Sin canales reales, sin conectores reales — solo el corazón.

**Decisiones a tomar en esta fase.**
- Formato definitivo del flow (estructura del YAML/JSON, vocabulario de estados/transiciones/acciones).
- Motor de FSM: propio interpretado vs librería existente (`transitions`, `statemachine`, XState-py, etc.).
- Modelo del `ConversationState`: qué campos siempre, qué campos dinámicos por flow.
- Mecanismo de persistencia del estado (in-memory primero; persistente después).

**Tareas.**
1. Definir el formato del flow con 2-3 ejemplos de juguete (menú → opción → final).
2. Implementar el motor: `Bot.handle_message(message, state) → (new_state, outputs)`.
3. Implementar `StateStorePort` y un adapter `InMemoryStateStore`.
4. Definir `InternalMessage` mínimo (campos esenciales: tenant_id, contact_id, text/payload, timestamp).
5. Definir `ConnectorPort` (interfaz) y un `MockConnector` para testing.
6. Tests unitarios: flow de juguete + transiciones + estado.

**Definición de hecho.**
- Existe un test end-to-end que: carga un flow YAML, simula 3-4 mensajes, verifica el estado final y los outputs.
- El core no importa de FastAPI, ni de Postgres, ni de WhatsApp. Pure logic.

**Fuera de alcance.**
- Canales reales.
- Conectores reales.
- Persistencia real del estado.
- Multi-tenancy.

---

#### Fase 2 — Connector Execution framework

**Objetivo.** Construir el framework de ejecución de conectores con todos los cross-cutting concerns. **Sin conectores concretos todavía** — solo el framework y un mock.

**Decisiones a tomar en esta fase.**
- Categorías iniciales y la forma exacta de cada interfaz (al menos `CalendarConnector`).
- Mecanismo de configuración: cómo se le dice al container _"para categoría X usa adapter Y con credenciales Z"_.
- Política de retries por defecto (backoff exponencial, max attempts).
- Mecanismo de circuit breaker (librería vs propio).
- Cómo se inyectan credenciales sin exponerlas en logs.

**Tareas.**
1. Definir la interfaz abstracta `ConnectorCategory` y `CalendarConnector` concreta.
2. Implementar `ConnectorRegistry`: resuelve _categoría → implementación_ a partir de config.
3. Implementar middleware del framework: retries, timeout, circuit breaker, métricas, logging.
4. `MockCalendarAdapter` que implementa la categoría — usado para tests.
5. Integrar registry en el Bot Engine: las acciones del flow pueden invocar conectores.

**Definición de hecho.**
- Un flow puede declarar _"acción: invoca conector calendar.list_slots"_, y el Bot Engine lo ejecuta vía el registry con el mock.
- Un test fuerza fallos del conector y verifica que retries + circuit breaker se aplican.

**Fuera de alcance.**
- Conectores reales contra APIs externas.
- Otras categorías (Payment, Notification, etc.) — se irán añadiendo en fases posteriores cuando se necesiten.

---

#### Fase 3 — Channel Adapter framework + WhatsApp

**Objetivo.** El container puede recibir webhooks reales de WhatsApp y responder.

**Decisiones a tomar en esta fase.**
- Forma definitiva del `InternalMessage` para cubrir texto + botones + listas interactivas + media.
- Política de degradación: qué hace el Bot Engine si pide al canal algo que el canal no soporta.
- Cómo se declaran los _capabilities_ del adapter.

**Tareas.**
1. Definir interfaz abstracta `ChannelAdapter` con `receive(payload)` y `send(message)`.
2. Implementar `WhatsAppAdapter`: parseo de webhook, validación HMAC, envío vía Cloud API.
3. Endpoint HTTP `POST /webhook/whatsapp` en el container que delega al adapter.
4. Tests con payloads de WhatsApp reales (capturados, no live).
5. Integración mínima: webhook → adapter → Bot Engine (flow trivial) → adapter → respuesta.

**Definición de hecho.**
- Un mensaje real desde WhatsApp llega al container y obtiene una respuesta del bot.
- HMAC se valida correctamente; webhooks con firma mala se rechazan.

**Fuera de alcance.**
- Otros canales (Telegram, web chat) — se añadirán cuando haga falta.
- Multi-tenancy en el routing (el container solo atiende un tenant).

---

#### Fase 3b — HTTP Dev Channel + configuración de tenant

**Objetivo.** Añadir un segundo canal de pleno derecho (`HttpDevChannelAdapter`) que permite probar el bot localmente vía HTTP sin depender de ningún proveedor externo, y formalizar el mecanismo de configuración del container para que el canal (y en el futuro los conectores) se seleccione desde un YAML de tenant en lugar de variables de entorno sueltas.

**Decisiones tomadas en esta fase.**
- La configuración del container vive en un YAML de tenant (`TENANT_CONFIG_PATH`). Contiene `tenant_id`, `flow_path`, `channel` (tipo + credenciales) y `connectors`. El lifespan carga este YAML al arrancar, igual que hará en F6 con el payload del Control Plane.
- Cada canal expone una función `make_router(adapter) → APIRouter` con sus endpoints propios. `main.py` no conoce los endpoints de ningún canal — solo incluye el router devuelto por el factory.
- El `ChannelAdapter` ABC añade `close()` con implementación no-op por defecto.
- `POST /inbound` procesa síncronamente y devuelve `{"status": "ok"}`. Los outputs del bot se acumulan en una cola interna (`deque(maxlen=200)`). `GET /messages` drena y devuelve la cola — modelo pull, sin SSE.
- `HttpDevChannelAdapter` declara capabilities sin restricciones artificiales (`max_buttons=10`, `max_list_rows=20`) para que el debugging sea limpio.
- Sin autenticación en los endpoints del dev channel — canal de uso local.

**Tareas.**
1. Añadir `close() → None` (no-op) al `ChannelAdapter` ABC.
2. `TenantConfig` en `data_plane/config.py`: dataclass que parsea el YAML y valida la estructura mínima (`tenant_id`, `flow_path`, `channel.type`).
3. Factory de canal en `adapters/channel/factory.py`: `build_channel(config) → tuple[ChannelAdapter, APIRouter]`.
4. `make_router(adapter)` en `whatsapp.py`: extrae los endpoints WhatsApp de `main.py` a su propio router.
5. `HttpDevChannelAdapter` + `make_router()` en `adapters/channel/http_dev.py`: `receive`, `send` (encola), `drain`, `verify_signature` (siempre True), `capabilities`, `close`.
6. Reescribir el lifespan de `main.py` para usar `TenantConfig` + factory de canal.
7. Tests unitarios de `HttpDevChannelAdapter` (`test_http_dev_adapter.py`): receive texto/button/list/malformado, send encola, drain vacía, verify_signature.
8. Tests de integración de endpoints (`test_dev_channel_endpoint.py`): turno único, multi-turno, drain doble vacía la segunda vez.
9. Actualizar `test_webhook_endpoint.py` para usar YAML de tenant en lugar de env vars sueltas.
10. Añadir configs de tenant de prueba en `tests/configs/`.

**Definición de hecho.**
- `POST /inbound {"contact_id": "test", "text": "hola"}` sobre `toy_flow` → `GET /messages` devuelve los outputs del estado `MENU`.
- Tres mensajes consecutivos del mismo `contact_id` avanzan el estado hasta `CONFIRM`.
- `GET /messages` por segunda vez devuelve lista vacía.
- `test_webhook_endpoint.py` sigue pasando con la nueva estructura de config.
- `make test` pasa. `make lint` pasa.

**Fuera de alcance.**
- SSE / WebSocket (pull con GET es suficiente).
- Otros canales (Telegram, web chat).
- Configuración de conectores reales desde el YAML (los conectores siguen siendo mock en M2).

---

#### Fase 4 — Primer conector real: GoogleCalendarAdapter

**Objetivo.** Sustituir el mock connector por un conector real contra Google Calendar.

**Decisiones a tomar en esta fase.**
- Manejo concreto de credenciales (service account JSON en disco/env vs vault).
- Granularidad de las operaciones de `CalendarConnector` (debe cubrir lo que el bot peluquería necesitaba: list_slots, create_event, cancel_event, get_event, mark_reminder_sent…).

**Tareas.**
1. Implementar `GoogleCalendarAdapter`: list_slots, create_event, cancel_event, get_event, list_for_range.
2. Migrar las primitivas correctas del código `legacy/` adaptándolas a la nueva interfaz.
3. Tests de integración (mock de la API de Google, no live).
4. Smoke test manual contra un Calendar real para validar end-to-end.

**Definición de hecho.**
- El conector real, invocado por el registry, lista slots y crea eventos en un Calendar de prueba.

**Fuera de alcance.**
- Otros calendarios (Cal.com, Outlook).
- Refresh token automation (si aplica).

---

#### Fase 5 — Vertical slice: bot peluquería sobre nueva arquitectura

**Objetivo.** Cablear M2 completo: un container con flow peluquería hardcoded, WhatsApp real, Google Calendar real, estado persistente local.

**Decisiones a tomar en esta fase.**
- Persistencia del estado: SQLite local en el container, archivo plano, o externo. (Recomendación inicial: SQLite local en volumen del container, simple y suficiente.)
- Ventana de despliegue y reinicio (cuándo reiniciar el container).

**Tareas.**
1. Escribir el flow de la peluquería en el formato YAML decidido.
2. Hardcodear la config del tenant (qué flow, qué calendar_id, qué credenciales) en el container.
3. Implementar `SQLiteStateStore` como adapter de `StateStorePort`.
4. Dockerfile del data plane.
5. Pruebas end-to-end con números de WhatsApp reales: reservar, consultar, cancelar.

**Definición de hecho.**
- Un cliente real puede mandar un mensaje al WhatsApp del tenant y completar una reserva.
- El estado de conversación sobrevive a reinicios del container (gracias a SQLite).
- La experiencia es equivalente a la del bot actual de peluquería.

**Fuera de alcance.**
- Más de un tenant.
- Control Plane.
- Recordatorios automáticos (se añaden en F9).

---

### Hito M3 — Multi-tenant con Control Plane

#### Fase 6 — Tenant & Identity Service (Control Plane mínimo)

**Objetivo.** Extraer la config del container y servirla desde un Control Plane real. La config deja de estar hardcoded.

**Decisiones a tomar en esta fase.**
- Schema concreto de la BD del Control Plane (tablas, índices, relaciones).
- Modelo de credenciales: vault externo vs cifrado en BD con KMS propio.
- Mecanismo de autenticación container ↔ Control Plane (parte de la decisión 2.2 "trust boundaries").

**Tareas.**
1. Postgres del Control Plane (docker-compose para dev).
2. Migrations: `tenants`, `channel_bindings`, `contacts`, `tenant_credentials`, `connector_bindings`.
3. API REST: `GET /tenant/{id}/config` (con auth) devuelve el blob de boot-time.
4. Capa de acceso a datos con `TenantContext` obligatorio.
5. Cifrado de credenciales en reposo.
6. Container: al arrancar, hace pull de la config desde el Control Plane (mismo flow peluquería, pero ahora viene de BD).

**Definición de hecho.**
- El container ya no contiene credenciales ni IDs hardcoded.
- Crear un tenant nuevo en BD (manualmente con SQL) + reiniciar un container apuntando a ese tenant = bot funciona con la nueva config.

**Fuera de alcance.**
- Editor de tenants (UI).
- Provisioning automático del container (todavía manual).
- Rotación de credenciales.

---

#### Fase 7 — Flow Authoring Service

**Objetivo.** El flow del bot también vive en el Control Plane, no en la imagen.

**Decisiones a tomar en esta fase.**
- Estrategia de versionado (semver, monotonic, timestamps).
- Validación del flow: qué se valida al publicar.
- Estrategia de invalidación de caché en containers cuando hay versión nueva (notificación push vs polling).

**Tareas.**
1. Migrations: `flows`, `flow_versions`, `flow_templates`.
2. API: `GET /flow/{tenant_id}/active` devuelve el flow YAML activo.
3. Validador de flow: chequea estructura, transiciones, referencias a conectores existentes.
4. Container: al arrancar, hace pull del flow y lo cachea en memoria.
5. Mecanismo de recarga (`POST /reload-flow` en el container, o polling).

**Definición de hecho.**
- Cambiar el flow del tenant = actualizar una row en BD + recarga (manual o automática) en el container, sin redeploy de imagen.
- Un flow inválido es rechazado al intentar guardarlo.

**Fuera de alcance.**
- Editor UI de flows.
- Migración de estado entre versiones de flow.

---

#### Fase 8 — Multi-tenancy real

**Objetivo.** Dos tenants distintos sirviendo en paralelo desde la misma imagen.

**Tareas.**
1. Dar de alta un segundo tenant en BD (por ej: otra peluquería ficticia o un negocio diferente).
2. Provisionar manualmente un segundo container con la URL pública correspondiente.
3. Configurar webhooks de WhatsApp para apuntar al container correcto.
4. Pruebas de aislamiento: confirmar que un tenant no puede leer datos del otro ni accidentalmente.

**Definición de hecho.**
- Dos números de WhatsApp distintos atienden a dos negocios distintos, con flows distintos, desde la misma imagen.

**Fuera de alcance.**
- Orchestrator automático (todavía manual).

---

### Hito M4 — Task Scheduler

#### Fase 9 — Task Scheduler con modelo push

**Objetivo.** Implementar el Scheduler completo según la sección 5.4 actualizada del doc: push, idempotency_key, cancelación.

**Decisiones a tomar en esta fase.**
- Backend del scheduler (APScheduler embebido en el Control Plane, RQ + Redis, Arq, Temporal, propio).
- Política de reintentos y dead-letter cuando un container no responde.
- Modelo exacto de ejecución (sync HTTP del Scheduler al container vs bus).

**Tareas.**
1. Migrations: `task_definitions`, `task_instances` con `idempotency_key` indexado.
2. API: `schedule`, `schedule_recurring`, `cancel`.
3. Loop del Scheduler: cada N segundos busca tareas con `execute_at <= now`, las dispara.
4. Endpoint en el container: `POST /execute-task` recibe `(action, payload, scope)` y lo ejecuta.
5. Implementar caso de uso recordatorio:
   - Al crear cita → `schedule(idempotency_key="reminder:evt_id", execute_at=...)`.
   - Al cancelar cita → `cancel(idempotency_key="reminder:evt_id")`.
   - Al disparar → container ejecuta `send_reminder(event_id)`, verifica cita válida, manda WhatsApp.
6. Tests: cancelación, reprogramación, race conditions, reintentos.

**Definición de hecho.**
- Se reserva una cita → el Scheduler la tiene registrada.
- Cancelas la cita → la tarea desaparece.
- Reprogramas la cita → la tarea se ajusta.
- Cuando toca → se ejecuta y el cliente recibe el WhatsApp.

**Fuera de alcance.**
- Dashboard del Scheduler (parte de Observabilidad).
- Tareas definidas por el cliente vía UI (parte del Admin Panel).

---

### Hito M5 — Observabilidad y Orchestrator

#### Fase 10 — Observabilidad básica

**Objetivo.** Visibilidad suficiente para debuggear un incidente real en producción.

**Decisiones a tomar en esta fase.**
- Stack concreto (OpenTelemetry + Prometheus + Grafana + Loki, gestionado, etc.).
- Esquema del audit trail.
- Política de retención.

**Tareas.**
1. Logging estructurado en todos los componentes con `trace_id` propagado desde el webhook.
2. Métricas básicas: mensajes recibidos/enviados, latencias, errores por conector.
3. Audit trail: decisiones del bot y llamadas a conectores se persisten en append-only.
4. Dashboards mínimos: vista global del sistema, vista por tenant.
5. Alertas básicas: tenant caído, error rate alto, API externa caída.

**Definición de hecho.**
- Dado un reporte _"el bot no me reservó la cita el martes a las 10"_, se puede trazar la conversación entera en logs en < 5 minutos.

**Fuera de alcance.**
- UI self-service para clientes (parte del Admin Panel).

---

#### Fase 11 — Tenant Orchestrator

**Objetivo.** Dar de alta un tenant nuevo es un comando, no una operación manual.

**Decisiones a tomar en esta fase.**
- Provider de hosting concreto (Fly.io Machines vs Cloudflare Containers vs ECS vs K8s).
- Estrategia de rollout (rolling, canary, por tier).
- Política de rollback global y por tenant.

**Tareas.**
1. Adapter del provider elegido: crear/destruir/actualizar/reiniciar container.
2. API del Orchestrator: `create_tenant_container`, `update`, `destroy`, `restart`, `rollout_new_image`.
3. Mapeo `tenant_id → container_id + URL pública` persistido.
4. Rolling deploy de la imagen a todos los containers.
5. Health checks y manejo de fallos.

**Definición de hecho.**
- Un comando da de alta un tenant nuevo de principio a fin (BD + container + URL).
- Una nueva versión de imagen se propaga progresivamente sin downtime visible.

**Fuera de alcance.**
- UI de gestión (parte del Admin Panel).

---

### Hito M6 — Admin Panel y Hardening

#### Fase 12 — Admin Panel

**Objetivo.** Gestión humana de la plataforma sin tocar BD ni CLI.

**Decisiones a tomar en esta fase.**
- Stack frontend.
- Modelo de Auth + RBAC (Auth0, Clerk, Keycloak, propio).
- Editor de flows (YAML, visual, ambos).

**Tareas.**
1. API web (REST o GraphQL) que consume Identity + Flow Authoring + Observability + Orchestrator.
2. Frontend con dos roles: admin de plataforma vs cliente.
3. Pantallas: alta de tenant, edición de credenciales, editor de flow (mínimo YAML con validación), dashboards self-service, gestión de cuotas.
4. Auth y enforcement de scope por tenant.

**Definición de hecho.**
- Un operador da de alta un tenant nuevo end-to-end vía UI.
- Un cliente loguea, ve sus dashboards y edita su flow.

**Fuera de alcance.**
- Marketplace de plantillas de flow.
- Sandbox / staging por tenant.

---

#### Fase 13 — Hardening para producción real

**Objetivo.** El sistema soporta operación 24/7 con clientes de pago.

**Decisiones a tomar en esta fase.**
- Modelo definitivo de trust boundaries (mTLS, JWTs, etc.).
- Política de backups y DR.
- Estrategia de cuotas y abuse protection.
- Plan de respuesta a incidentes.

**Tareas.**
1. Autenticación entre Control Plane y containers (más allá de lo mínimo de F6).
2. Backups automáticos de la BD del Control Plane.
3. Test de disaster recovery: restaurar la plataforma desde cero con datos de backup.
4. Cuotas y rate limits por tenant.
5. Pruebas de carga: N tenants × M mensajes/min.
6. Pruebas de chaos: caída de Control Plane, caída de containers, caída de API externa.
7. Documentación operacional: runbooks, alertas, procedimientos.

**Definición de hecho.**
- El sistema pasa una review de seguridad básica.
- Existe un runbook para los 5 incidentes más probables.
- Test de carga sostenible al objetivo de escala definido (decisión 2.1).

**Fuera de alcance.**
- Optimizaciones de rendimiento prematuras.
- Features nuevas.

---

## 3. Principios de secuencia

- **Una fase a la vez.** No se trabaja en F2 hasta que F1 esté cerrada con su _definición de hecho_.
- **Excepciones controladas.** Se puede empezar trabajo de la fase siguiente _solo_ si está bloqueado por una decisión que se está investigando y no hay nada más que hacer en la actual.
- **Si una fase no se puede cerrar, se subdivide.** No se "casi cierra" una fase. O se cierra, o se divide en sub-fases más pequeñas.
- **Las decisiones pendientes (`A investigar` en `arquitectura.md`) se cierran en la fase que las requiere**, no antes. Si surge una decisión cross-component nueva, se lleva a `arquitectura.md` antes de codificar.
- **El bot legacy es referencia, no destino.** Se puede mirar para entender el dominio o tomar primitivas correctas; no se copia tal cual.

---

## 4. Cómo se actualiza este plan

- Cuando se cierra una fase: marcar en este doc, añadir nota breve de _"qué quedó decidido"_.
- Si una decisión obliga a replanificar fases siguientes: actualizar primero la fase afectada en este doc.
- Si se descubre que falta una fase entera: insertarla con número decimal (ej. `Fase 6.5`).
- Si se descubre que una decisión de arquitectura era equivocada: parar, actualizar `arquitectura.md`, replanificar las fases afectadas, y _entonces_ seguir.

---

## 5. Estado actual

> Esta sección se va actualizando a mano según se avanza.

- **Fase actual:** Fase 4 — Primer conector real: GoogleCalendarAdapter.
- **Fases cerradas:** F0 (scaffolding), F1 (Bot Engine standalone), F2 (Connector framework), F3 (Channel Adapter + WhatsApp), F3b (HTTP Dev Channel + configuración de tenant).
- **Decisiones cerradas:** stack tecnológico (FastAPI + uvicorn + uv + Python 3.14), formato de flow (YAML declarativo), motor FSM (intérprete propio), `StateStorePort` / `ConnectorPort` / `ChannelAdapter` como ports hexagonales, `degrade_output` para degradación de canal, scheduler push (ver `arquitectura.md`), containers siempre encendidos, config del container en YAML de tenant (`TENANT_CONFIG_PATH`), router por canal (`make_router` factory), `zoneinfo.ZoneInfo` (stdlib) en lugar de pytz, service account JSON en disco para credenciales Google Calendar, `CalendarConnector` extendido con `mark_reminder_sent`/`mark_manual_confirmed`/`get_pending_manual_events`.
- **Próximo paso concreto:** smoke test manual del GoogleCalendarAdapter contra un Calendar real (F4 definición de hecho), luego F5 vertical slice peluquería.
