# Arquitectura del Sistema — Plataforma de Bots Conversacionales

> **Documento de diseño a alto nivel.** Recoge la visión, los componentes, sus responsabilidades y cómo se conectan. **NO** incluye detalles de implementación, formatos concretos ni elección final de librerías — cada componente tiene una sección _"A investigar"_ para esos detalles, que se trabajarán en sesiones posteriores.

---

## 1. Visión General

Plataforma SaaS multi-tenant que permite ofrecer **bots conversacionales** a múltiples negocios (peluquerías, clínicas, gimnasios, restaurantes…) sobre una **infraestructura común** orquestada centralmente, donde cada cliente ejecuta su propio runtime aislado.

**Target de diseño:** muchos tenants (cientos o miles) con **baja concurrencia por tenant** — negocios pequeños/medianos donde rara vez hay decenas de conversaciones simultáneas. El sistema escala horizontalmente añadiendo más containers pequeños a medida que crece la base de clientes, no aumentando el tamaño de un container monolítico.

### El modelo de dos planos

La plataforma se divide en **dos planos** muy distintos en propósito y despliegue:

| Plano | Cuántos hay | Dónde corre | Qué hace |
|-------|-------------|-------------|----------|
| **Control Plane** | Uno compartido | En una VM (o cluster de VMs para alta disponibilidad) | Gestiona la plataforma entera: tenants, flows, despliegues, observabilidad, tareas programadas, panel de administración |
| **Data Plane** | Uno por cliente | Un container por tenant (siempre encendido, con reinicio programado) | Ejecuta el bot del cliente: recibe mensajes, los procesa, llama a sus conectores, responde |

**Todos los containers de Data Plane corren la MISMA imagen de código.** Lo que diferencia a un tenant de otro es **qué configuración carga en arranque** — su flow, sus credenciales, sus conectores enchufados. No hay código específico por cliente.

### Principios rectores

1. **Genericidad por defecto.** Las abstracciones del código son agnósticas al dominio. Lo específico de cada cliente vive en _datos_ (config + flow), nunca en código.
2. **Hexagonal en cada componente.** Cada bounded context tiene un núcleo de lógica pura rodeado de puertas (_ports_) y adaptadores (_adapters_) intercambiables.
3. **Datos importados, no programados.** Definiciones de bots, identidades, configuraciones y tareas se cargan desde el Control Plane en tiempo de ejecución. Añadir un cliente nuevo **no requiere desplegar código**.
4. **Pluggable por categorías.** Los conectores se agrupan por _rol_ (calendario, pago, notificación…). El bot referencia el rol; la configuración del tenant decide qué implementación concreta usar.
5. **Aislamiento físico entre tenants.** Cada cliente vive en su propio container — un fallo en uno no afecta a los otros. No hace falta `tenant_id` dentro de un container porque solo procesa datos suyos.
6. **Una sola imagen, muchas instancias.** El código se actualiza una vez en el Control Plane; las actualizaciones se propagan a todos los containers como rolling deploy.

### Las tres capas de abstracción

| Capa | Vive en | Qué contiene |
|------|---------|--------------|
| **Plataforma (código)** | La imagen Docker | Clases base, interfaces, runtime — sin lógica de dominio específica |
| **Configuración compartida (datos)** | BD del Control Plane | Identidades, flows, bindings de conectores, tareas — registro central |
| **Runtime de cliente (datos locales)** | Volumen / store del container del tenant | Estado de las conversaciones activas de ese cliente |

> **Implicación clave:** dar de alta un cliente nuevo = (1) registrar metadata en el Control Plane y (2) provisionar un container con su config. NO requiere tocar la imagen de código.

---

## 2. Diagrama de Arquitectura

```
┌────────────────────────────────────────────────────────────────────────┐
│                          CONTROL PLANE                                  │
│                  (compartido — corre en VM)                             │
│                                                                         │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐   │
│  │ Tenant &         │  │ Flow Authoring    │  │ Tenant           │   │
│  │ Identity Service │  │ Service           │  │ Orchestrator     │   │
│  │ - tenants        │  │ - definiciones    │  │ - provisiona     │   │
│  │ - credentials    │  │ - versionado      │  │   containers     │   │
│  │ - contactos      │  │ - validación      │  │ - deploy / kill  │   │
│  └──────────────────┘  └───────────────────┘  └──────────────────┘   │
│                                                                         │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐   │
│  │ Task Scheduler   │  │ Observability     │  │ Admin Panel      │   │
│  │ - tareas         │  │ & Audit           │  │ - UI admin       │   │
│  │   programadas    │  │ Aggregator        │  │ - UI cliente     │   │
│  │ - cron & one-off │  │ - logs, métricas, │  │ - dashboards     │   │
│  │ - cancelaciones  │  │   traces, audit   │  │                  │   │
│  └──────────────────┘  └───────────────────┘  └──────────────────┘   │
│                                                                         │
│                    CONTROL PLANE DB (compartida, tenant_id)            │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 │  Control Plane API
                                 │  (config, eventos, telemetría)
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
   │ Container      │  │ Container      │  │ Container      │
   │ Tenant A       │  │ Tenant B       │  │ Tenant C       │
   │                │  │                │  │                │
   │ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
   │ │ Channel    │ │  │ │ Channel    │ │  │ │ Channel    │ │
   │ │ Adapter(s) │ │  │ │ Adapter(s) │ │  │ │ Adapter(s) │ │
   │ └─────┬──────┘ │  │ └─────┬──────┘ │  │ └─────┬──────┘ │
   │       ▼        │  │       ▼        │  │       ▼        │
   │ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
   │ │ Bot        │ │  │ │ Bot        │ │  │ │ Bot        │ │
   │ │ Engine     │ │  │ │ Engine     │ │  │ │ Engine     │ │
   │ └─────┬──────┘ │  │ └─────┬──────┘ │  │ └─────┬──────┘ │
   │       ▼        │  │       ▼        │  │       ▼        │
   │ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
   │ │ Connector  │ │  │ │ Connector  │ │  │ │ Connector  │ │
   │ │ Execution  │ │  │ │ Execution  │ │  │ │ Execution  │ │
   │ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
   │                │  │                │  │                │
   │ (state local)  │  │ (state local)  │  │ (state local)  │
   └────────────────┘  └────────────────┘  └────────────────┘

           DATA PLANE — N containers, todos con la misma imagen
                Cada uno aislado, con su propia config y estado
```

---

## 3. Topología de Despliegue

### Control Plane

- Corre en una **VM** (o cluster pequeño de VMs para alta disponibilidad).
- Contiene servicios "siempre encendidos" (varios procesos pero un mismo deployment).
- Tiene una BD compartida (multi-tenant con `tenant_id` row-level) donde vive toda la metadata.
- Punto único de gestión: panel admin, dashboards, autoría de flows, lifecycle de tenants.

### Data Plane

- **Un container por tenant**, todos con la **misma imagen Docker**.
- Cada container es independiente: su propia URL pública (para webhooks), sus propias credenciales, su propio estado local.
- **Siempre encendido**, con **reinicio programado periódico** (típicamente diario, en ventana de baja actividad) para aplicar actualizaciones y refrescar memoria. No se usa scale-to-zero — el coste se mantiene bajo dimensionando los containers pequeños por defecto (la concurrencia esperada por tenant es baja).
- **Despliegues** de versión nueva de imagen en ventana de baja actividad mediante rolling deploy. Las conversaciones a medias pueden interrumpirse en un restart — los clientes simplemente vuelven a empezar al siguiente mensaje, comportamiento aceptado dada la franja horaria elegida.
- Plataforma de hosting: alguna que permita provisioning por API y gestión de muchos containers pequeños (la elección concreta es decisión posterior — opciones razonables: Fly.io Machines, Cloudflare Containers, ECS, etc.).

### Comunicación entre planos

- **Boot-time pull**: cuando un container arranca, llama al Control Plane para cargar su config y su flow.
- **Runtime callbacks**: el container emite eventos al Control Plane (telemetría, audit, eventos de dominio).
- **Operaciones de lifecycle**: el Control Plane invoca al provider de hosting para crear/actualizar/destruir containers.

---

## 4. Caso Central: Onboarding de un Cliente Nuevo

Este es el caso que define si la arquitectura está bien o no. Si dar de alta a un cliente es fácil, hemos diseñado bien.

### Flujo de onboarding

```
1. Operador (o el propio cliente) usa el Admin Panel
   │
2. Rellena un formulario con:
   ─ Datos del negocio (nombre, contacto, etc.)
   ─ Qué FLOW va a usar (elige uno de la biblioteca de flows o sube uno)
   ─ Qué CONECTORES enchufa, y las credenciales de cada uno:
     · calendario → Google Calendar (calendar_id + service account JSON)
     · notificación → WhatsApp Cloud API (phone_number_id + token)
     · pago → Stripe (api_key) [opcional]
     · ...
   ─ Metadata adicional (servicios ofrecidos, horarios, precios — formato libre)
   │
3. Hace clic en "Crear"
   │
4. Control Plane:
   a. Guarda toda la config en su BD
   b. Cifra las credenciales en reposo
   c. Llama al Orchestrator: "provisiona un container para este tenant"
   d. Orchestrator crea el container vía API del hosting provider
   e. El container arranca, llama al Control Plane para cargar su config
   f. Una vez listo, el Control Plane devuelve la URL pública del container
   │
5. Operador configura WhatsApp (u otro canal) para apuntar a esa URL
   │
6. LISTO — el cliente está en producción
```

### Lo que NO se hace al dar de alta

- ❌ No se toca código.
- ❌ No se hace un deploy nuevo de la imagen.
- ❌ No se modifica ningún flow existente.
- ❌ No se reinicia nada que afecte a otros clientes.

### Lo que cuesta dar de alta a un cliente

- **Tiempo**: minutos (mayoritariamente esperando a que arranque el container).
- **Infra**: el coste de un container adicional (pequeño y de bajo consumo dado el perfil de tráfico esperado por tenant).
- **Trabajo humano**: rellenar el formulario.

---

## 5. Componentes del Control Plane

### 5.1 Tenant & Identity Service

**Responsabilidad.** Registro central de todos los clientes (tenants), sus credenciales, los bindings de conectores y los contactos finales (usuarios de cada cliente).

**Diseño a alto nivel.**

Entidades principales:

- **Tenant**: el cliente (peluquería, clínica…) — nombre, plan, estado (activo/suspendido), metadata.
- **Channel Binding**: qué canal/número/ID pertenece a qué tenant (ej: el número WhatsApp `+34...` es del tenant `peluqueria-sur`).
- **Contact**: el usuario final identificado por _canal + ID_ dentro de un tenant.
- **Connector Binding**: para un tenant, qué adapter concreto usa por categoría (ej: `calendar → google_calendar`).
- **Credentials**: tokens y claves de los conectores de cada tenant, cifrados en reposo.

**A investigar.**

- Esquema concreto de la BD (tablas, índices, relaciones).
- Modelo de gestión de credenciales: vault externo vs cifrado en BD con key management propio.
- Identidad cross-canal: un mismo humano usando WhatsApp y Telegram, ¿son Contacts separados o uno solo?
- Rotación de credenciales sin interrumpir al container.
- API que expone para que los containers consulten su config al arrancar.

---

### 5.2 Flow Authoring Service

**Responsabilidad.** Almacenar, versionar y validar las definiciones de los flows (el _guion_ de cada bot). **NO ejecuta nada.**

**Diseño a alto nivel.**

- Storage de definiciones de flows (formato declarativo, importable).
- **Biblioteca de flows reutilizables**: plantillas de las que cuelgan los flows concretos de cada tenant (ej: plantilla `booking-flow-v3` que la peluquería Sur y la clínica Centro usan ambas con sus parámetros).
- **Versionado**: cada cambio crea una versión nueva; activar/desactivar versiones; rollback.
- **Validación previa a publicar**: estructura correcta, referencias a categorías de conectores existentes, no hay estados sin transiciones, etc.
- API que sirve flows a los containers cuando arrancan o cuando hay updates.

**A investigar.**

- Formato del flow (XState JSON, YAML custom, BPMN simplificado, statechart propio…).
- Cómo se editan los flows (editor visual, editor texto, GitOps, plantillas paramétricas).
- Estrategia de caché en el container + invalidación cuando hay versión nueva.
- Compatibilidad hacia atrás cuando el formato del flow evoluciona.
- Cómo se hace "preview" de un flow antes de publicarlo.

---

### 5.3 Tenant Orchestrator

**Responsabilidad.** Provisionar, actualizar y destruir los containers del Data Plane. Es la pieza que habla con el provider de hosting.

**Diseño a alto nivel.**

- Expone operaciones tipo: `create_tenant_container`, `update_tenant_container`, `destroy_tenant_container`, `restart_tenant_container`.
- Por dentro, llama a la API del provider (Fly.io, Cloudflare, ECS, etc.) — esto es un adapter intercambiable.
- Mantiene un mapeo `tenant_id → container_id + URL pública`.
- Gestiona el **rollout de versiones nuevas** de la imagen: rolling deploy a todos los containers con health checks.
- Si un container falla repetidamente, alerta a Observability.

**A investigar.**

- Provider de hosting concreto (Fly.io Machines vs Cloudflare Containers vs ECS vs K8s vs otros).
- Estrategia de rollout: a la vez vs progresivo vs canary.
- Cómo se gestionan rollbacks por tenant individual.
- Estrategia de "tenants noisy" — si un tenant consume demasiados recursos, qué se hace.
- Tier/plan por tenant: containers más grandes para clientes premium.

---

### 5.4 Task Scheduler

**Responsabilidad.** Disparar tareas programadas y recurrentes para los tenants. Mantiene el registro central de tareas pendientes, las ejecuta cuando toca, y propaga cancelaciones y reprogramaciones que provienen del bot.

**Modelo primario: push (registro explícito de tareas).**

Cuando el bot decide que algo debe ocurrir en el futuro, **registra explícitamente** una tarea en el Scheduler. El Scheduler la dispara cuando toca. Si la entidad subyacente cambia (la cita se cancela o se reprograma), el bot llama a `cancel` o re-registra con la misma clave idempotente.

Push se elige sobre polling porque:
- **Generalidad**: cubre cualquier caso de uso futuro (recordatorios, timeouts de conversación, retries, alarmas one-off, jobs cron). Polling solo cubre casos derivables de una fuente consultable.
- **Escalabilidad**: O(1) por tarea registrada vs O(N entidades) por ciclo de polling.
- **Observabilidad**: cada tarea es una entidad con identidad propia, historial y estado. _"¿Por qué no se envió el recordatorio X?"_ tiene respuesta directa en su task_instance.

Polling sobre fuentes de datos sigue siendo posible, pero se modela como **tarea recurrente** (un cron registrado) — no como un mecanismo distinto.

**API canónica del Scheduler.**

| Operación | Uso |
|-----------|-----|
| `schedule(idempotency_key, execute_at, action, payload, scope)` | Registra una tarea o sobrescribe la existente con la misma clave |
| `schedule_recurring(idempotency_key, cron, action, payload, scope)` | Registra una tarea recurrente |
| `cancel(idempotency_key)` | Cancela una tarea pendiente; idempotente (si no existe, no falla) |

**Anatomía de una tarea.**

- **idempotency_key**: clave estable, típicamente derivada de la entidad (ej. `reminder:evt_42`). Permite cancelar y reprogramar sin tener que guardar `task_id` en cada entidad.
- **execute_at / cron**: timestamp absoluto (push one-off) o expresión cron (recurrente).
- **action**: identificador del handler que ejecutará la tarea en el container.
- **payload**: datos que recibe el handler (típicamente IDs de entidades, no estado).
- **scope**: tenant y opcionalmente contact/entity.
- **retry policy**: política de reintentos en caso de fallo.

**Garantías y red de seguridad.**

- **At-least-once**: si el Scheduler no recibe confirmación del container, reintenta. El handler en el container es responsable de la idempotencia final.
- **Verificación en el executor**: antes de actuar, el handler comprueba que la entidad subyacente sigue siendo válida (la cita no ha sido cancelada, el contacto sigue existiendo, etc.). Es la red de seguridad frente a race conditions entre `cancel` y `fire`.
 
**Ejemplos típicos.**

- Recordatorio 24h antes de una cita → push one-off, clave `reminder:evt_id`. Al cancelar la cita, `cancel("reminder:evt_id")`. Al reprogramarla, nuevo `schedule` con la misma clave (sobrescribe).
- Sincronización periódica de eventos manuales del calendario → tarea recurrente, clave `sync_calendar:tenant_id`.
- Timeout de conversación inactiva → push one-off, clave `timeout:tenant_id:contact_id`.
- Limpieza de estados expirados → tarea recurrente del sistema (no del tenant).

**Por qué el Scheduler vive en el Control Plane.**

- Centralización: una sola fuente de verdad de "qué tareas hay pendientes". Observable, debugable, auditable.
- Evita duplicar lógica de scheduling en cada container.
- Sigue siendo el sitio correcto aunque los containers estén siempre encendidos — no se mete un task store en cada container.

**A investigar.**

- Formato de definición de tareas (declarativo, importable).
- Backend del scheduler (APScheduler, RQ, Arq, Temporal, propio).
- Tareas del sistema (limpieza, retries) vs tareas del tenant (definidas en el flow del cliente).
- Cómo se versiona/actualiza una tarea recurrente sin perder ejecuciones pendientes.
- Política exacta de reintentos y dead-letter cuando un container no responde repetidamente.
- Modelo de ejecución: ¿el Scheduler llama al container vía sync HTTP, o publica a un bus que el container consume?

---

### 5.5 Observability & Audit Aggregator

**Responsabilidad.** Recibir logs, métricas, traces y audit events de **todos** los containers, agregarlos y servirlos para análisis y dashboards.

**Diseño a alto nivel — cuatro tipos de datos:**

| Tipo | Qué es | Origen |
|------|--------|--------|
| **Logs** | Texto estructurado | Todos los containers + Control Plane |
| **Métricas** | Contadores y tiempos agregados | Todos los containers + Control Plane |
| **Traces** | Cadena causal entre componentes | Todos los containers + Control Plane |
| **Audit trail** | Bitácora inmutable de decisiones del bot y llamadas a conectores | Containers (por tenant) |

**Plataforma de monitoring:**
- Dashboards multi-tenant: vista global del sistema + vista por cliente.
- Alertas a operadores cuando algo va mal.
- Vista self-service para los clientes (cada uno ve solo sus datos).

**A investigar.**

- Stack concreto (OpenTelemetry + Prometheus + Grafana + Loki, ELK, Datadog, etc.).
- Esquema del audit trail y retención legal.
- Aislamiento por tenant en dashboards.
- Cómo se correlacionan logs/traces/audit con un trace ID común desde el webhook.
- Estrategia de muestreo a alta carga.

---

### 5.6 Admin Panel

**Responsabilidad.** Interfaz humana para gestionar la plataforma. Dos audiencias:

- **Admin** (operadores de la plataforma): dar de alta tenants, ver monitoring global, intervenir si algo va mal, gestionar el catálogo de conectores disponibles.
- **Cliente** (dueño del negocio): editar su flow, gestionar metadata, ver sus dashboards, gestionar credenciales de sus conectores, ver sus contactos.

**Diseño a alto nivel.**

- API web que consume los demás servicios del Control Plane.
- Frontend separado (web app) — admin y cliente probablemente comparten el mismo frontend con RBAC distinto.
- **Auth + RBAC**: roles, permisos, scope por tenant.
- **Editor de flows**: pieza clave UX — visual o textual según perfil del cliente.

**A investigar.**

- Stack del frontend.
- Modelo de auth/RBAC (Auth0, Clerk, Keycloak, propio).
- Editor visual de flows (drag-and-drop) vs editor texto/YAML para clientes técnicos.
- Sandbox/staging por tenant para probar cambios.
- Marketplace de plantillas de flow reutilizables.

---

## 6. Componentes del Data Plane (Dentro de Cada Container)

Cada container ejecuta los siguientes componentes. **El código es el mismo en todos los containers** — lo que cambia es la config que cargan al arrancar.

### 6.1 Channel Adapters (Entrada / Salida)

**Responsabilidad.** Traducir entre el mundo exterior (WhatsApp, Telegram, web chat, voz…) y el formato interno del bot. Sin lógica de dominio. Solo lectura y respuesta.

**Diseño a alto nivel.**

- Una clase abstracta `ChannelAdapter` con dos operaciones principales:
  - `receive(payload) → InternalMessage`
  - `send(InternalMessage) → channel-specific output`
- Una implementación concreta por canal: `WhatsAppAdapter`, `TelegramAdapter`, `WebChatAdapter`, etc.
- Validación de seguridad (HMAC, firmas, rate limiting) ocurre **antes** de normalizar.
- Cada adapter declara sus _capabilities_ (qué tipos de mensaje soporta). El runtime las consulta para no pedir al adapter algo que no puede.
- En el container de un tenant solo se activan los adapters de los canales que ese cliente tiene configurados.

**A investigar.**

- Formato exacto del `InternalMessage` — suficientemente rico para cubrir todos los canales sin acoplarse a ninguno.
- Degradación cuando un canal no soporta lo que el bot quiere mandar (lista interactiva → texto numerado).
- Estrategia de retries y dead-letter cuando un canal falla al enviar.

---

### 6.2 Bot Engine + Conversation Runtime

> **Es el corazón del sistema y la pieza más abstracta.** Una sola clase `Bot` (genérica) ejecuta cualquier flow para cualquier cliente.

**Responsabilidad.** Ejecutar conversaciones. Recibe un mensaje normalizado, lo procesa según el flow del tenant, devuelve respuestas.

**Diseño a alto nivel — la clase `Bot` genérica.**

Al arrancar el container:
- Carga la config del tenant desde el Control Plane (qué flow usa, qué conectores tiene, etc.).
- Cachea el flow localmente.

Por cada mensaje:
- Recibe un `InternalMessage` del Channel Adapter.
- Carga el estado actual de esa conversación (almacenado localmente en el container).
- Aplica una transición del flow basada en el mensaje.
- Durante la transición puede ejecutar acciones: llamar a conectores, generar respuestas, programar tareas, emitir eventos.
- Persiste el nuevo estado.
- Emite eventos al Control Plane (telemetría, audit).
- Devuelve la(s) respuesta(s) al Channel Adapter para enviarlas.

**Ports que necesita (cosas del exterior):**

| Port | Lo provee | Uso |
|------|-----------|-----|
| `FlowLoaderPort` | Control Plane (con caché local) | Cargar la definición de flow activa |
| `StateStorePort` | Storage local del container | Leer/guardar estado de conversación |
| `ConnectorPort` | Connector Execution (componente 6.3) | Invocar conectores externos |
| `EventEmitterPort` | Control Plane Aggregator | Emitir eventos de dominio y audit |
| `OutboundChannelPort` | Channel Adapter (6.1) | Mandar respuestas |
| `TaskSchedulingPort` | Control Plane Scheduler | Programar tareas futuras |

**A investigar.**

- Motor de ejecución del flow (intérprete de DSL propio, librería FSM, statemachine library…).
- Modelo concreto del estado de conversación (qué campos siempre, cuáles dependen del flow).
- Concurrencia: dos mensajes del mismo contacto a la vez → lock o cola por contact.
- Timeouts: usuario abandona la conversación a mitad → política de limpieza.
- Persistencia del estado: volumen del container vs store dedicado.
- Estrategia de "free text" cuando el flow espera botones (posible punto de inserción de LLM opcional).

---

### 6.3 Connector Execution

**Responsabilidad.** Ejecutar las llamadas hacia el exterior (calendarios, pagos, notificaciones, etc.) que el bot necesita.

**Diseño a alto nivel — generalización por categorías.**

Cada conector pertenece a una **categoría** que define la interfaz abstracta. Categorías iniciales propuestas:

| Categoría | Operaciones típicas |
|-----------|---------------------|
| `CalendarConnector` | `list_slots`, `create_event`, `cancel_event`, `update_event` |
| `PaymentConnector` | `charge`, `refund`, `create_subscription` |
| `NotificationConnector` | `send_email`, `send_sms`, `send_push` |
| `CRMConnector` | `create_lead`, `update_contact`, `search` |
| `StorageConnector` | `read`, `write`, `delete` |
| `LLMConnector` | `complete`, `extract_intent`, `embed` |

Para cada categoría hay N implementaciones concretas:
- `CalendarConnector` → `GoogleCalendarAdapter`, `CalComAdapter`, `OutlookAdapter`…
- `NotificationConnector` → `TwilioAdapter`, `ResendAdapter`, `SendGridAdapter`…

**Todas las implementaciones viven en la imagen Docker.** Lo que cambia por tenant es cuál se activa: la config del tenant dice _"para categoría `calendar`, usa `google_calendar` con estas credenciales"_.

**Cross-cutting concerns aplicados centralizadamente (no en cada conector):**
- Retries con backoff.
- Rate limiting por categoría/operación.
- Timeouts.
- Métricas y logging estructurado.
- Inyección de credenciales del tenant.
- Circuit breaker cuando un proveedor está caído.

El conector concreto solo escribe la lógica específica del proveedor — todo lo demás lo da el framework.

**A investigar.**

- Las categorías iniciales y la forma exacta de cada interfaz.
- ¿Escape hatch para integraciones que no encajan en ninguna categoría? (Un conector "HTTP genérico" donde el flow define la llamada.)
- Versionado de un conector (Google Calendar v3 → v4) sin romper flows existentes.
- Cómo se añade un conector nuevo al catálogo (idealmente sin modificar el core).
- Si los conectores corren in-process o aislados.
- Manejo de credenciales OAuth con refresh tokens.

---

## 7. Cómo se Conectan los Componentes

### Dentro del Control Plane

Comunicación principalmente síncrona vía llamadas internas + BD compartida. Los servicios del Control Plane están todos juntos en la misma VM, así que el coste de comunicación es bajo.

### Dentro de un container del Data Plane

Comunicación síncrona vía llamadas a métodos: el Channel Adapter llama al Bot Engine, que llama a Connector Execution. Todo dentro del mismo proceso.

### Entre Control Plane y Data Plane

| Quién llama a quién | Cuándo | Tipo |
|---------------------|--------|------|
| Container → Control Plane | Al arrancar | Sync — carga config inicial |
| Container → Control Plane | Al recibir cualquier mensaje | Async fire-and-forget — emite telemetría/audit |
| Container → Control Plane | Cuando publica un evento de dominio | Async — el Control Plane lo consume |
| Container → Control Plane | Al programar una tarea futura | Sync — registra la tarea en el Scheduler |
| Control Plane → Container | Cuando una tarea programada se dispara | Sync HTTP |
| Control Plane → Container | Cuando el cliente publica un flow nuevo | Async (notificación) — el container invalida su caché |
| Control Plane → Provider de hosting | Cuando se da de alta/baja un tenant | Sync API |
| Container → API externa (Calendar, etc.) | Cuando el bot lo necesita | Sync HTTP con retries |
| WhatsApp/Telegram → Container | Cuando llega un mensaje | Sync HTTP (webhook) |

---

## 8. Modelo de Datos a Alto Nivel

### En el Control Plane (BD compartida con `tenant_id`)

| Storage | Entidades principales |
|---------|----------------------|
| Identity Store | `tenants`, `channel_bindings`, `contacts`, `tenant_credentials`, `connector_bindings` |
| Flow Definitions Store | `flows`, `flow_versions`, `flow_templates` |
| Task Store | `task_definitions`, `task_instances` (pendientes/ejecutadas) |
| Audit Log | Append-only, alto volumen, retención larga |
| Metrics / Traces backend | Stack separado (no necesariamente en la BD principal) |

**Regla universal de aislamiento en el Control Plane:** toda fila de toda tabla lleva `tenant_id`. La capa de acceso a datos lo aplica de forma obligatoria — interfaz que **no permite omitirlo**.

### En el Data Plane (storage local del container)

- **Conversation State**: estado de las conversaciones activas de ese tenant.

No hay otros datos. Todo lo demás (config, flow, credenciales) se carga del Control Plane al arrancar y se mantiene en memoria.

---

## 9. Aislamiento Multi-Tenant

### Nivel físico (Data Plane)

Cada tenant tiene su propio container. **No comparte proceso, memoria ni storage local con otros tenants.** Un fallo, un bug o una saturación en un container no puede afectar a los demás. Aislamiento total a nivel runtime.

### Nivel lógico (Control Plane)

La BD del Control Plane es compartida. Todo dato lleva `tenant_id`. La capa de acceso a datos enforce el filtro de tenant en cada query, sin excepción.

### Nivel de credenciales

Las credenciales de cada tenant viven cifradas en el Control Plane. Se inyectan al container del tenant correspondiente al arrancarlo — nunca se exponen entre tenants.

### Nivel de red

Cada container tiene su propia URL pública. Webhooks de WhatsApp/Telegram para el tenant X apuntan exclusivamente a la URL del container X.

---

## 10. Hexagonal: Cómo Aplica a Cada Componente

Dentro de cada componente (tanto Control Plane como Data Plane):

- **Core**: lógica de dominio pura. No importa de FastAPI, Postgres, WhatsApp, ni de ninguna tecnología externa.
- **Ports**: interfaces que el core necesita del exterior (storage, mensajería, tiempo, etc.).
- **Adapters**: implementaciones concretas. Enchufadas por inyección de dependencias al arrancar.

Esto permite:
- Testear el core en aislamiento total (con fakes).
- Cambiar tecnología sin reescribir lógica.
- Que el mismo código corra en distintos contextos (un container de tenant vs un test unitario) cambiando solo los adapters.

---

## 11. Áreas Cross-Component a Investigar

Lo que afecta a varios componentes y se decide _una vez_:

1. **Provider de hosting para containers** (Fly.io Machines vs Cloudflare Containers vs ECS vs Kubernetes vs otros).
2. **Stack del Control Plane**: BD principal, framework web, etc.
3. **Manejo de secretos** (vault externo, cifrado en BD con KMS).
4. **Estrategia de migraciones de schema** sin downtime.
5. **Estrategia de testing**: end-to-end multi-tenant, integración Control Plane ↔ Data Plane.
6. **Estrategia de feature flags** para releases progresivos.
7. **Localización (i18n)** — los flows van a estar en muchos idiomas.
8. **Backup y disaster recovery**: para el Control Plane y para el estado local de cada container.
9. **Modelo de costes por tenant** (cuánto consume cada uno, cómo facturarlo).
10. **Ventana de despliegue y reinicio programado**: franja horaria para rolling deploys y reinicios diarios, política frente a conversaciones interrumpidas.

---

## 12. Próximos Pasos

1. **Refinar la abstracción del Bot (6.2)** — es la pieza más central y aún tiene preguntas abiertas. Hasta que esté clara, no podemos diseñar bien el flow ni el runtime.
2. **Decidir las categorías iniciales de conectores (6.3)** y la forma exacta de su interfaz.
3. **Decidir el formato de definición de flows (5.2)** y el motor de ejecución.
4. **Diseñar el modelo de datos en detalle** (sección 8 expandida).
5. **Decidir el stack tecnológico** por capa (sección 11).
6. **Decidir el provider de hosting** para containers.
7. **Crear la rama** y empezar el scaffolding del Control Plane + la imagen base del Data Plane.

---

> _Este documento evolucionará. Cada sesión de refinamiento añadirá detalle a sus secciones y resolverá los puntos "A investigar". Los detalles técnicos vivirán en documentos separados por componente._
