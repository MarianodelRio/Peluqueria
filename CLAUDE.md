# CLAUDE.md — Peluquería Citas Bot

## Project overview

WhatsApp booking bot for a barber shop. Clients book, view, and cancel appointments via WhatsApp. The barber manages everything from Google Calendar.

- **Framework**: FastAPI + uvicorn
- **External APIs**: WhatsApp Cloud API (Meta), Google Calendar API v3
- **Background jobs**: APScheduler 3.x
- **Persistence**: Google Calendar (no database — Calendar is the single source of truth)
- **State**: In-memory conversation state, expires after 30 min of inactivity
- **Deployment**: GCP VM + systemd + nginx reverse proxy + DuckDNS dynamic DNS
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
    calendar/            # All Calendar operations.
      service.py         # Public API: reservar, cancelar, mover, slots
      queries.py         # Read-only Calendar queries (scheduler jobs + client lookups)
      mutations.py       # Calendar writes: crear_cita, cancelar_cita, marcar_* fields
      engine.py          # Slot availability logic
      caches.py          # Slot cache (30s TTL) + citas cache (60s TTL)
      locks.py           # Per-slot booking locks (prevent double-booking)
      client.py          # Thread-local Google Calendar API client
      repository.py      # Raw Calendar API calls, range-batched fetch for day picker
    whatsapp.py          # send_text_message(), send_interactive(), send_template()
    scheduler.py         # 3 jobs: sync manual bookings (60 min), reminders (60 min), state cleanup (10 min)
watchdog.py              # Standalone health monitor: bot /health, RAM, disk, error spike, public domain reachability. Runs via cron every 60 min.
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
pip install -r requirements.txt

# Start server (development)
uvicorn app.main:app --reload --port 8000

# Run all tests
pytest

# Run specific module
pytest tests/test_conversation.py -v

# Coverage report
pytest --cov=app --cov-report=term-missing

# Health check (local)
curl http://localhost:8000/health
# → {"status":"ok","calendar":"ok","metrics":{...}}

# Health check (public, through nginx)
curl https://peluqueriabot.duckdns.org/health
```

### Production deployment (GCP VM)

```bash
make setup      # Install nginx + certbot (snap) — first time only
make install    # Create venv + install Python deps — first time only
make services   # Configure systemd + SSL cert + DuckDNS cron — first time only
make start      # Start or restart all services
make status     # Check service health
make update     # Deploy code changes (git pull + pip install)
```

---

## Environment variables

```ini
WHATSAPP_PHONE_NUMBER_ID=   # Required
WHATSAPP_ACCESS_TOKEN=       # Required — must be a permanent System User token
WHATSAPP_VERIFY_TOKEN=       # Required
WHATSAPP_APP_SECRET=         # Required in production — enables HMAC webhook signature verification
GOOGLE_CALENDAR_ID=          # Required
GOOGLE_CREDENTIALS_PATH=     # Path to service account JSON (default: credentials.json)
ADMIN_PHONE=                 # Required — digits only, no +. Receives watchdog alerts and /estado
PUBLIC_DOMAIN=               # Required — DuckDNS subdomain without https:// (e.g. peluqueriabot.duckdns.org)
DUCKDNS_TOKEN=               # Required — DuckDNS account token (used by make services for SSL + IP updater)
LOG_LEVEL=INFO               # Optional — DEBUG | INFO | WARNING | ERROR
LOG_FILE=                    # Optional — path for rotating log file
```

### Infrastructure overview

```
Meta WhatsApp ──HTTPS:443──▶ GCP VM (104.196.210.121)
                                    │
                              nginx (TLS termination)
                                    │ proxy_pass
                              uvicorn :8000 (127.0.0.1 only)

DNS:  peluqueriabot.duckdns.org → 104.196.210.121  (DuckDNS, updated every 5 min via cron)
SSL:  Let's Encrypt cert via certbot DNS-01 challenge, auto-renewed every 90 days
```

- uvicorn binds to `127.0.0.1` only — never exposed directly to the internet.
- nginx passes `X-Real-IP` and `X-Forwarded-For` headers; uvicorn runs with `--proxy-headers` so `request.client.host` returns the real client IP for rate limiting.
- `watchdog.py` monitors `PUBLIC_DOMAIN` health (check 5) — alert key `proxy_down`.

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
