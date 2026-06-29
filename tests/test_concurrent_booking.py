# tests/test_concurrent_booking.py
"""
Concurrent booking integration test — Calendar REAL, WhatsApp HTTP mocked.

Simulates N users completing the full booking flow simultaneously. Verifies
that every user receives a response (booked or conflict) and no thread hangs.

Run with:
    pytest tests/test_concurrent_booking.py -m integration -s -v
    pytest tests/test_concurrent_booking.py -s -k "n_users=10"

Excluded from normal CI automatically:
    pytest -m "not integration"
"""
import random
import threading
import time
from collections import defaultdict
from statistics import mean
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.handlers.conversation as conv
import app.handlers.webhook as wh
import app.services.calendar as cal
import app.services.whatsapp as whatsapp_module
from app.handlers.webhook import router as webhook_router
from tests.conftest import make_payload

# ── Shared capture state ───────────────────────────────────────────────────
_bot_responses: dict[str, list] = defaultdict(list)
_wa_lock = threading.Lock()

# ── Test app — no lifespan, no scheduler, no validate_config ──────────────
_test_app = FastAPI()
_test_app.include_router(webhook_router)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    # Empty APP_SECRET → _verify_signature() returns True without checking HMAC
    with patch("app.handlers.webhook.WHATSAPP_APP_SECRET", ""):
        with TestClient(_test_app) as c:
            yield c


@pytest.fixture
def calendar_spy():
    """Wrap cal.reservar_cita to record event IDs and measure latency.
    Teardown deletes every created event from the real Calendar."""
    created_ids: list[str] = []
    timings: dict[str, list[float]] = defaultdict(list)
    ids_lock = threading.Lock()

    original_reservar = cal.reservar_cita

    def spy_reservar(d, hora, nombre, telefono, servicio):
        t0 = time.perf_counter()
        event_id, reason = original_reservar(d, hora, nombre, telefono, servicio)
        elapsed = time.perf_counter() - t0
        with ids_lock:
            timings[telefono].append(elapsed)
            if event_id:
                created_ids.append(event_id)
        return event_id, reason

    with patch("app.services.calendar.reservar_cita", side_effect=spy_reservar):
        yield {"created_ids": created_ids, "timings": timings}

    # Teardown runs even if the test fails
    for eid in created_ids:
        try:
            cal.cancelar_cita(eid)
            print(f"[CLEANUP] ✓ borrada {eid}")
        except Exception as e:
            print(f"[CLEANUP] ✗ {eid}: {e}")
    print(f"[CLEANUP] {len(created_ids)} citas de prueba eliminadas")


@pytest.fixture
def whatsapp_spy():
    """Two-layer spy:
    - Layer A: capture what the bot sends (text and interactive) for assertion.
    - Layer B: intercept the real HTTP POST to Meta, replacing it with a fake
               that sleeps in the realistic Meta latency range (150–350 ms).
    The real whatsapp.py logic (delivery tracking, retries) runs unchanged.
    """
    _bot_responses.clear()

    original_text = whatsapp_module.send_text_message
    original_interactive = whatsapp_module.send_interactive

    def spy_text(phone, text):
        with _wa_lock:
            _bot_responses[phone].append({"type": "text", "body": text})
        return original_text(phone, text)

    def spy_interactive(phone, payload):
        with _wa_lock:
            _bot_responses[phone].append({"type": "interactive", **payload})
        return original_interactive(phone, payload)

    ok = MagicMock()
    ok.raise_for_status.return_value = None
    ok.status_code = 200

    def fake_http_post(*args, **kwargs):
        time.sleep(random.uniform(0.15, 0.35))
        return ok

    with patch("app.services.whatsapp.send_text_message", side_effect=spy_text), \
         patch("app.services.whatsapp.send_interactive", side_effect=spy_interactive), \
         patch.object(whatsapp_module._client, "post", side_effect=fake_http_post):
        yield


# ── Response helpers ───────────────────────────────────────────────────────

def last_response(phone: str) -> dict | None:
    r = _bot_responses.get(phone, [])
    return r[-1] if r else None


def extract_first_row_id(payload: dict | None) -> str | None:
    """Return the first non-navigation row ID from an interactive list payload."""
    rows = (
        (payload or {})
        .get("interactive", {})
        .get("action", {})
        .get("sections", [{}])[0]
        .get("rows", [])
    )
    return next((r["id"] for r in rows if not r["id"].startswith("back_")), None)


def is_period_select(payload: dict | None) -> bool:
    """True if the bot is asking morning/afternoon."""
    btns = (payload or {}).get("interactive", {}).get("action", {}).get("buttons", [])
    return any(b.get("reply", {}).get("id", "").startswith("period_") for b in btns)


def is_confirmation(payload: dict | None) -> bool:
    """True if the payload is the booking confirmation message."""
    body = (payload or {}).get("body", "") or \
           (payload or {}).get("interactive", {}).get("body", {}).get("text", "")
    return "confirmada" in body.lower() or "✅" in body


# ── State reset ────────────────────────────────────────────────────────────

def _reset_state() -> None:
    """Clear all in-process state so each parametrized test starts clean."""
    conv._states.clear()
    with conv._phone_locks_guard:
        conv._phone_locks.clear()
    with wh._deduplicator._lock:
        wh._deduplicator._seen.clear()
    with wh.ip_rate_limiter._lock:
        wh.ip_rate_limiter._buckets.clear()
    with wh.phone_rate_limiter._lock:
        wh.phone_rate_limiter._buckets.clear()
    # All TestClient requests share one IP ("testclient"), so the 60/min IP cap
    # would trip at ~10 users — a test artifact (Meta spreads load across many
    # IPs in production). Raise it here only; the per-phone limiter is realistic
    # and stays untouched.
    wh.ip_rate_limiter._limit = 10_000


# ── Single-user booking flow ───────────────────────────────────────────────

def run_user_booking(phone: str, client: TestClient) -> dict:
    """Drive one user through the full 7-step booking flow.

    Each client.post() blocks until the background handler finishes (including
    real Calendar API calls), so timing reflects true end-to-end latency.
    """
    result: dict = {"phone": phone, "steps": [], "outcome": None, "total_ms": 0}

    def step(name: str, **payload) -> dict | None:
        t0 = time.perf_counter()
        client.post("/webhook", json=make_payload(phone, **payload))
        ms = int((time.perf_counter() - t0) * 1000)
        resp = last_response(phone)
        result["steps"].append({"name": name, "ms": ms, "ok": resp is not None})
        return resp

    t_flow = time.perf_counter()

    step("saludo",   text="Hola")
    step("reservar", interactive_id="menu_book")
    resp = step("servicio", interactive_id="service_corte")

    day_id = extract_first_row_id(resp)
    if not day_id:
        result["outcome"] = "error"
        return result
    resp = step("dia", interactive_id=day_id)

    if is_period_select(resp):
        resp = step("periodo", interactive_id="period_morning")

    hour_id = extract_first_row_id(resp)
    if not hour_id:
        result["outcome"] = "error"
        return result
    step("hora", interactive_id=hour_id)

    resp = step("nombre", text=f"Test {phone[-4:]}")

    result["total_ms"] = int((time.perf_counter() - t_flow) * 1000)

    if not _bot_responses.get(phone):
        result["outcome"] = "no_response"     # the bug we're guarding against
    elif is_confirmation(resp):
        result["outcome"] = "booked"          # slot successfully created in Calendar
    else:
        result["outcome"] = "conflict"        # slot taken — graceful response received
    return result


# ── Summary printer ────────────────────────────────────────────────────────

def _print_summary(
    n: int,
    results: dict,
    threads: list,
    cal_spy: dict,
) -> None:
    icons = {
        "booked":      "✅ Reserva",
        "conflict":    "⚠️  Conflicto",
        "error":       "❌ Error",
        "no_response": "🔇 Sin resp",
    }
    times = [r["total_ms"] for r in results.values() if r["total_ms"] > 0]
    print(f"\n{'═'*64}")
    print(f"  CONCURRENCIA — {n} usuarios simultáneos  [Calendar REAL]")
    print(f"{'═'*64}")
    print(f"  {'Teléfono':<14}{'Resultado':<16}{'Total':>8}{'Cal~':>8}{'Pasos':>8}")
    for phone, r in results.items():
        cal_ms = int(sum(cal_spy["timings"].get(phone, [0])) * 1000)
        ok_steps = sum(1 for s in r["steps"] if s["ok"])
        label = icons.get(r["outcome"], "?")
        print(
            f"  {phone:<14}{label:<16}"
            f"{r['total_ms']:>6}ms{cal_ms:>6}ms{ok_steps:>5}/{len(r['steps'])}"
        )
    booked   = sum(1 for r in results.values() if r["outcome"] == "booked")
    conflict = sum(1 for r in results.values() if r["outcome"] == "conflict")
    no_resp  = sum(1 for r in results.values() if r["outcome"] == "no_response")
    hung     = sum(1 for t in threads if t.is_alive())
    print(f"  {'─'*60}")
    print(f"  Reservas OK     : {booked}/{n}")
    print(f"  Conflictos slot : {conflict}/{n}  (respuesta correcta)")
    print(f"  Sin respuesta   : {no_resp}/{n}  ← debe ser 0")
    print(f"  Threads colgados: {hung}/{n}  ← debe ser 0")
    if times:
        print(
            f"  Tiempo medio    : {mean(times)/1000:.2f}s"
            f" | min {min(times)/1000:.2f}s"
            f" | max {max(times)/1000:.2f}s"
        )
    print(f"{'═'*64}\n")


# ── Test ───────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("n_users", [1, 3, 5, 10])
def test_concurrent_booking(n_users, client, calendar_spy, whatsapp_spy):
    _reset_state()

    # Phones in the reserved test prefix range — won't collide with real clients
    phones = [f"34699{i:06d}" for i in range(1, n_users + 1)]
    barrier = threading.Barrier(n_users, timeout=15)
    results: dict[str, dict] = {}

    def run(phone: str) -> None:
        barrier.wait()   # release all threads simultaneously
        results[phone] = run_user_booking(phone, client)

    threads = [
        threading.Thread(target=run, args=(p,), daemon=True) for p in phones
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)   # real Calendar may be slow — generous margin

    _print_summary(n_users, results, threads, calendar_spy)

    hung    = [p for p, t in zip(phones, threads) if t.is_alive()]
    no_resp = [p for p, r in results.items() if r.get("outcome") == "no_response"]

    assert not hung, (
        f"Threads colgados (posible deadlock o timeout Calendar): {hung}"
    )
    assert not no_resp, (
        f"Usuarios sin respuesta (EL BUG): {no_resp}"
    )
