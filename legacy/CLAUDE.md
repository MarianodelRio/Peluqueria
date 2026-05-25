# CLAUDE.md — Peluquería Citas Bot

## Project overview

WhatsApp booking bot for a barber shop. Clients book, view, and cancel appointments via WhatsApp. The barber manages everything from Google Calendar.

- **Framework**: FastAPI + uvicorn
- **External APIs**: WhatsApp Cloud API (Meta), Google Calendar API v3
- **Background jobs**: APScheduler 3.x
- **Persistence**: Google Calendar (no database — Calendar is the single source of truth)
- **State**: In-memory conversation state, expires after 30 min of inactivity
- **Deployment**: Linux + systemd (production), ngrok (development)
- **Tests**: pytest — all external APIs mocked, no real credentials needed

---

## Module map

```
app/
  config.py              # All constants and env vars. Edit HORARIO_BASE for schedule changes.
  main.py                # FastAPI app + lifespan (scheduler start/stop) + /health + /metrics
  handlers/
    webhook.py           # GET /webhook (verification) + POST /webhook (incoming messages)
    conversation.py      # State machine: MENU → BOOK_SELECT_SERVICE → BOOK_SELECT_DAY → BOOK_SELECT_PERIOD → BOOK_SELECT_HOUR → BOOK_ENTER_NAME; CANCEL_SELECT → CANCEL_CONFIRM. Entry: handle_message()
  services/
    calendar.py          # All Calendar operations. Slot cache (30s TTL). Per-slot booking locks. Range-batched fetch for day picker.
    whatsapp.py          # send_text_message(), send_interactive(), send_template()
    scheduler.py         # 3 jobs: sync manual bookings (5 min), reminders (1 h), state cleanup (10 min)
  utils/
    parser.py            # parse_tel/nombre/estado/reminder/cfg, set_field, remove_field
    slots.py             # get_base_slots_for_day(), generate_slots(), filter_available_slots()
    interactive.py       # WhatsApp interactive message builders (lists and buttons)
    messages.py          # All Spanish-language text strings
    metrics.py           # In-memory counters — metrics.inc('counter_name')
tests/
  conftest.py            # Shared fixtures — mock Calendar service, mock WhatsApp calls
  test_calendar.py / test_conversation.py / test_slots.py / ... (one file per module)
```

---

## Key patterns and invariants

### Google Calendar event description format
All appointment events have these fields in the description (parsed by `parser.py`):
```
Nombre: Juan García
Telefono: +34612345678
Servicio: corte | corte_barba | mechas
Estado: pendiente | confirmada
Recordatorio: no | sí
```

### [CFG] events
Title-based config events — never treated as appointments:
- `[CFG] CERRADO` → day is closed
- `[CFG] VACACIONES` → range is closed
- `[CFG] HORARIO HH:MM-HH:MM` → overrides schedule for that day

### Thread safety
- Per-phone locks (`_get_phone_lock(phone)`) in `conversation.py` — serialize concurrent messages from the same number.
- Per-slot locks (`_get_slot_lock(d, hora)`) in `calendar.py` — prevent double-booking race conditions.
- Shared dict iteration always snapshots first: `snapshot = list(d.items())`.

### WhatsApp interactive message limits
- Interactive list: max 10 rows (8 content + 2 navigation).
- Interactive buttons: max 3.
- Use `_go_to_hour_select()` (not `build_hours_list()` directly) — it applies period splitting to stay under the row limit.

### Booking atomic flow
`lock → slot_sigue_libre(d, hora, duracion_min, presencia_cliente_min) → crear_cita(servicio) → _invalidate_slot_cache(d)`

### Services
Three services are defined in `SERVICIOS` in `config.py`. Each affects slot generation and Calendar event duration:

| Key | Display name | Price | `duracion_min` | `presencia_cliente_min` |
|-----|-------------|-------|---------------|------------------------|
| `corte` | Corte de pelo | 10 € | 30 min | 30 min |
| `corte_barba` | Corte de pelo + barba | 12 € | 30 min | 30 min |
| `mechas` | Mechas | 30 € | 60 min | 180 min |

- `duracion_min` controls the Calendar event duration and the collision window with other events (active barber time).
- `presencia_cliente_min` controls when the last slot of the day/period is offered (the client must finish before closing).
- For services without a waiting period, both values are equal.
- The slot cache key includes both `duracion_min` and `presencia_cliente_min` — calls with different durations or presence windows are cached separately.

### Day-picker fetch
`_handle_book_select_service` calls `get_slots_disponibles_range(today, today+14d)` ONCE — single Calendar API call that populates the per-day slot cache, so subsequent single-day fetches are cache hits.

### Scheduler idempotency
- Reminder job checks `Recordatorio: sí` before sending — skips if already sent.
- Manual sync job checks `Estado: confirmada` — skips if already processed.

---

## Dev commands

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Start server (development)
uvicorn app.main:app --reload --port 8000

# Run all tests
pytest

# Run specific module
pytest tests/test_conversation.py -v

# Coverage report
pytest --cov=app --cov-report=term-missing

# Health check
curl http://localhost:8000/health
# → {"status":"ok","calendar":"ok","metrics":{...}}
```

---

## Environment variables

```ini
WHATSAPP_PHONE_NUMBER_ID=   # Required
WHATSAPP_ACCESS_TOKEN=       # Required
WHATSAPP_VERIFY_TOKEN=       # Required
GOOGLE_CALENDAR_ID=          # Required
GOOGLE_CREDENTIALS_PATH=     # Path to service account JSON (default: credentials.json)
WHATSAPP_APP_SECRET=         # Optional — enables HMAC webhook signature verification
LOG_LEVEL=INFO               # Optional — DEBUG | INFO | WARNING | ERROR
LOG_FILE=                    # Optional — path for rotating log file
```

---

## Role System (Strict)

One task = one clean cycle: **plan → implement → review**.

Pass context between roles via explicit artifacts (plan text, file paths, implementation summary). Never skip phases or merge roles.

### Planner
- Produces step-by-step plans, identifies files to modify, defines acceptance criteria.
- Does **NOT** write or modify code.
- Use agent: `planner`

### Coder
- Executes exactly what the plan says, minimal focused changes.
- Does **NOT** redesign, extend scope, or add unrequested features.
- Runs `pytest` before reporting done.
- Use agent: `coder`

### Reviewer
- Evaluates changes against the plan, detects bugs and regressions.
- Does **NOT** implement fixes — reports them for a new cycle.
- Gives the user `pytest` commands to run.
- Use agent: `reviewer`

### Advisor
- Deep technical consultant for architecture and strategy decisions.
- Gives **one clear recommendation** — never "it depends" without resolving it.
- Does **NOT** write code or pseudocode.
- Use agent: `advisor` (Opus model)

### Researcher
- Investigates API capabilities, algorithms, and implementation patterns.
- Reads codebase **first**, then searches externally.
- Does **NOT** invent findings.
- Escalates to `advisor` for multi-approach architectural decisions.
- Use agent: `researcher`

### User-invocable skills
- `/research` — Conversational session to mature an idea into a Research Design Solution (RDS).
- `/new-feature` — Full pipeline: RDS → planner → coder → reviewer, with checkpoint approval at each phase.
