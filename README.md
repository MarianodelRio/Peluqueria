# Plataforma de Bots Conversacionales

Plataforma SaaS multi-tenant para ofrecer bots conversacionales a múltiples negocios (peluquerías, clínicas, gimnasios, restaurantes…) sobre infraestructura común. Arquitectura de **dos planos**: un control plane compartido que gestiona la plataforma, y un container por cliente que ejecuta su bot.

> **Estado: fase de diseño.** El código de la plataforma aún no existe. Este repo contiene el documento de arquitectura, la estructura del proyecto, y el código `legacy` que sirve de referencia.

---

## Estructura del repositorio

```
.
├── arquitectura.md       ← documento de diseño (fuente de verdad)
├── PLAN.md               ← fases de implementación F0–F13 con criterios de aceptación
├── legacy.md             ← patrones portables del bot legacy y checklist de migración
├── legacy/               ← implementación single-tenant anterior (referencia working)
│   ├── app/              · código de la app (FastAPI + APScheduler)
│   ├── tests/            · suite pytest
│   ├── watchdog.py       · monitor standalone
│   ├── config.yaml       · config del negocio
│   ├── README.md         · documentación del bot legacy
│   ├── CLAUDE.md         · instrucciones para Claude del bot legacy
│   └── ...
└── platform/             ← la nueva plataforma (greenfield, en construcción)
    ├── control_plane/    · servicios compartidos
    ├── data_plane/       · imagen del container por tenant
    ├── shared/           · ports, dominio, utilidades comunes
    └── tests/            · suite de tests de la plataforma
```

---

## El documento clave

**[arquitectura.md](arquitectura.md)** es la fuente de verdad del diseño. Describe:

- El modelo de dos planos (Control Plane + Data Plane).
- Los componentes, sus responsabilidades y qué NO hacen.
- Cómo se conectan entre sí.
- El flujo concreto de alta de un cliente nuevo.
- Las decisiones tomadas y las que quedan por investigar.

> Antes de tocar código en `platform/`, leer `arquitectura.md`.

---

## Sobre `legacy/`

El código en `legacy/` es la implementación single-tenant que existía antes de empezar este diseño. **No se va a refactorizar.** Vive ahí como **implementación de referencia** de lo que un container del Data Plane tiene que hacer:

- Recibir webhooks de WhatsApp.
- Hablar con Google Calendar.
- Gestionar conversaciones con estado.
- Programar recordatorios y tareas periódicas.

Cuando se implemente un componente nuevo en `platform/`, se mira `legacy/` para ver cómo se resolvió cada problema y se reutilizan las piezas que tengan sentido. Especialmente:

- Integración con WhatsApp Cloud API ([legacy/app/services/whatsapp.py](legacy/app/services/whatsapp.py))
- Integración con Google Calendar ([legacy/app/services/calendar/](legacy/app/services/calendar/))
- Parseo de descripciones de eventos ([legacy/app/utils/parser.py](legacy/app/utils/parser.py))
- Generación de slots ([legacy/app/utils/slots.py](legacy/app/utils/slots.py))
- Deduplicación de webhooks ([legacy/app/utils/dedup.py](legacy/app/utils/dedup.py))
- HMAC + rate limiting ([legacy/app/handlers/webhook.py](legacy/app/handlers/webhook.py), [legacy/app/utils/rate_limiter.py](legacy/app/utils/rate_limiter.py))
- Patrones de testing ([legacy/tests/conftest.py](legacy/tests/conftest.py))

**Lo que NO se porta:**

- El flow conversacional específico de peluquería (en la nueva arquitectura es **datos** en el Control Plane, no código).
- Los textos hardcoded en español (pasan a ser config por tenant).
- El modelo de "una sola fuente YAML global" (sustituido por config por tenant en el Control Plane).
- El estado de conversación en memoria (sustituido por estado durable por container).

---

## Sobre `platform/`

Las cuatro carpetas están vacías a propósito. Cada una corresponde a una pieza de la arquitectura:

| Carpeta | Qué contendrá | Componentes (ver arquitectura.md) |
|---------|---------------|-----------------------------------|
| `platform/control_plane/` | Los servicios compartidos en VM | Tenant & Identity, Flow Authoring, Tenant Orchestrator, Task Scheduler, Observability Aggregator, Admin Panel |
| `platform/data_plane/` | La imagen del container por tenant | Channel Adapters, Bot Engine, Connector Execution |
| `platform/shared/` | Código común a ambos planos | Dominio, ports, utilidades, modelo de mensaje interno |
| `platform/tests/` | Suite de tests de la plataforma | Tests unitarios + integración + end-to-end |

---

## Estado actual

- ✅ Diseño de arquitectura a alto nivel — en `arquitectura.md`.
- ✅ Código legacy preservado como referencia — en `legacy/`.
- ✅ Estructura de carpetas de la nueva plataforma — en `platform/`.
- ✅ Plan de implementación por fases — en `PLAN.md`.
- ✅ Catálogo de patrones portables y guía de migración — en `legacy.md`.
- ⏳ Implementación de la plataforma — en curso. **Fase actual: F0 — Scaffolding** (ver `PLAN.md`).

Próximos pasos detallados en `PLAN.md`. El criterio de "done" para F0: `make run-control-plane` y `make run-data-plane` retornan 200 en `/health`, y `make test` y `make lint` pasan.

---

## Trabajando con Claude en este repo

Este repo usa agentes y comandos de Claude configurados en `.claude/`. Cada agente tiene un rol acotado; el flujo normal es: research → plan → code → review.

### Agentes disponibles

| Agente | Descripción |
|--------|-------------|
| `advisor` | Consultor de arquitectura: da UNA recomendación clara ante decisiones difíciles (hosting, scheduler, modelo de credenciales, etc.). No escribe código. |
| `planner` | Produce planes de implementación paso a paso, situados en una fase de `PLAN.md`. No escribe código. |
| `coder` | Ejecuta el plan aprobado con cambios mínimos y focalizados. No ejecuta tests. |
| `reviewer` | Revisa la implementación contra el plan: hexagonal, tenant isolation, sin modificar `legacy/`. Entrega los comandos de test al usuario. |
| `researcher` | Investiga APIs, patrones y opciones externas. Devuelve hallazgos accionables con fuentes. |

### Comandos disponibles

| Comando | Descripción |
|---------|-------------|
| `/research` | Sesión de investigación interactiva: carga el contexto del proyecto, hace preguntas aclaratorias, invoca `researcher` y `advisor`, y produce un Research Design Solution (RDS) cuando se lo pides. |
| `/new-feature` | Pipeline completo planner → coder → reviewer con aprobación explícita del usuario en cada fase. Requiere un RDS como entrada. |
