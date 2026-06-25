#!/usr/bin/env python3
"""
Load driver para reproducir el problema de concurrencia del bot.

Simula N usuarios que, A LA VEZ, recorren el flujo de reserva enviando
webhooks sinteticos al endpoint /webhook. No necesita WhatsApp real: las
respuestas salen hacia la WhatsApp Cloud API (con telefonos ficticios fallaran,
que es lo esperado), pero el objetivo es estresar la ruta de PROCESAMIENTO.

Mide:
  - latencia del 200 de cada POST (debe ser SIEMPRE rapida; si sube, el event
    loop o el threadpool estan saturados)
  - deltas de /metrics antes/despues: handler_dropped, whatsapp_errors,
    calendar_errors, messages_received

SEGURIDAD EN PRODUCCION:
  --steps read  (por defecto): recorre menu -> servicio -> dia -> hora.
                Hace lecturas a Calendar pero NO crea citas. Seguro en prod.
  --steps full: ademas envia el nombre -> CREA UNA CITA REAL en el calendario.
                Usalo SOLO contra un calendario de pruebas.

Requisitos: solo stdlib (urllib). No instala nada.

Ejemplos:
    python scripts/loadtest_webhook.py --url http://localhost:8000 --users 7
    python scripts/loadtest_webhook.py --url http://localhost:8000 --users 7 \
        --app-secret $WHATSAPP_APP_SECRET --day 2026-06-26 --hour 1030
"""
import argparse
import concurrent.futures as cf
import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error


def make_payload(phone: str, msg_id: str, *, text=None, interactive_id=None) -> bytes:
    if interactive_id is not None:
        # Para list_reply (servicio/dia/hora/periodo) o button_reply (resto):
        is_list = interactive_id.startswith(("service_", "day_", "hour_", "period_"))
        sub = "list_reply" if is_list else "button_reply"
        message = {
            "from": phone, "id": msg_id, "type": "interactive",
            "interactive": {"type": sub, sub: {"id": interactive_id, "title": "x"}},
        }
    else:
        message = {"from": phone, "id": msg_id, "type": "text",
                   "text": {"body": text or "hola"}}
    body = {"object": "whatsapp_business_account",
            "entry": [{"id": "0", "changes": [{"value": {
                "messaging_product": "whatsapp",
                "messages": [message]}, "field": "messages"}]}]}
    return json.dumps(body).encode("utf-8")


def post(url: str, body: bytes, app_secret: str | None) -> tuple[int, float]:
    headers = {"Content-Type": "application/json"}
    if app_secret:
        sig = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={sig}"
    req = urllib.request.Request(url + "/webhook", data=body, headers=headers,
                                 method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception as e:
        print("  ! error:", e)
        return -1, time.time() - t0


def get_metrics(url: str) -> dict:
    try:
        with urllib.request.urlopen(url + "/metrics", timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print("no pude leer /metrics:", e)
        return {}


def booking_steps(args):
    """Cada paso es un mensaje del usuario. 'read' para antes de la hora;
    'full' anade el nombre que crea la cita real."""
    steps = [
        ("menu",    dict(text="hola")),
        ("book",    dict(interactive_id="menu_book")),
        ("service", dict(interactive_id=f"service_{args.service}")),
        ("day",     dict(interactive_id=f"day_{args.day}")),
        ("hour",    dict(interactive_id=f"hour_{args.day}_{args.hour}")),
    ]
    if args.steps == "full":
        steps.append(("name", dict(text="Usuario Test")))
    return steps


def run_user(idx: int, url: str, app_secret: str | None, gap: float, args):
    phone = f"34600000{idx:03d}"
    latencies = []
    for step_name, kw in booking_steps(args):
        msg_id = f"{phone}-{step_name}-{int(time.time()*1000)}"
        body = make_payload(phone, msg_id, **kw)
        status, dt = post(url, body, app_secret)
        latencies.append(dt)
        print(f"[u{idx}] {step_name:8s} -> {status} en {dt*1000:6.0f} ms")
        if gap:
            time.sleep(gap)
    return latencies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=7)
    ap.add_argument("--app-secret", default=None,
                    help="WHATSAPP_APP_SECRET; obligatorio si esta configurado en el server")
    ap.add_argument("--steps", choices=["read", "full"], default="read",
                    help="read=no crea citas (seguro en prod); full=crea cita real")
    ap.add_argument("--service", default="corte")
    ap.add_argument("--day", default="2026-06-26", help="YYYY-MM-DD libre en tu calendario")
    ap.add_argument("--hour", default="1030", help="HHMM libre, p.ej. 1030")
    ap.add_argument("--gap", type=float, default=0.0,
                    help="segundos entre pasos de un mismo usuario (0 = a tope)")
    args = ap.parse_args()

    if args.steps == "full":
        print("!! steps=full CREA CITAS REALES. Usa un calendario de pruebas.\n")

    before = get_metrics(args.url)
    print(f"=== Lanzando {args.users} usuarios simultaneos (steps={args.steps}) ===\n")
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.users) as ex:
        futs = [ex.submit(run_user, i, args.url, args.app_secret, args.gap, args)
                for i in range(args.users)]
        all_lat = [l for f in cf.as_completed(futs) for l in f.result()]
    wall = time.time() - t0
    after = get_metrics(args.url)

    print(f"\n=== Resultado en {wall:.1f}s ===")
    if all_lat:
        all_lat.sort()
        p50 = all_lat[len(all_lat) // 2]
        p95 = all_lat[min(int(len(all_lat) * 0.95), len(all_lat) - 1)]
        print(f"latencia 200  p50={p50*1000:.0f}ms  p95={p95*1000:.0f}ms  "
              f"max={max(all_lat)*1000:.0f}ms")
        print("  (si p95/max suben mucho -> event loop/threadpool saturados)")
    print("\nDeltas /metrics:")
    any_delta = False
    for k in sorted(set(before) | set(after)):
        d = after.get(k, 0) - before.get(k, 0)
        if d:
            any_delta = True
            flag = ("  <-- REVISAR" if k in
                    ("handler_dropped", "whatsapp_errors", "calendar_errors") else "")
            print(f"  {k}: +{d}{flag}")
    if not any_delta:
        print("  (sin cambios; comprueba que /metrics existe y el server recibio los POST)")


if __name__ == "__main__":
    main()
