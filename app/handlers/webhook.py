# handlers/webhook.py
"""
WhatsApp webhook endpoints.
GET: Meta verification handshake.
POST: incoming messages — text, interactive, and unknown types.

Design decisions:
- Always return 200 immediately (WhatsApp requirement, max 5s window).
- Process messages in BackgroundTasks (thread pool) to avoid blocking the event loop.
- Deduplicate by message ID to handle WhatsApp webhook retries safely.
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Request, Response, HTTPException

from app.config import WHATSAPP_VERIFY_TOKEN
from app.handlers.conversation import handle_message

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Message deduplication ──────────────────────────────────────────────────
# WhatsApp retries delivery if it doesn't receive 200 within ~5s.
# We track processed message IDs (with TTL) to avoid double-processing.

_processed_ids: dict[str, datetime] = {}
_processed_ids_lock = threading.Lock()
_PROCESSED_ID_TTL = timedelta(minutes=10)


def _is_duplicate(message_id: str) -> bool:
    """
    Return True if this message_id was already processed.
    Cleans up expired entries on every call (amortised, cheap at low traffic).
    """
    now = datetime.now()
    with _processed_ids_lock:
        # Remove entries older than TTL
        expired = [k for k, ts in _processed_ids.items() if now - ts > _PROCESSED_ID_TTL]
        for k in expired:
            del _processed_ids[k]

        if message_id in _processed_ids:
            return True

        _processed_ids[message_id] = now
        return False


# ── Rate limiting ──────────────────────────────────────────────────────────
# Simple in-memory per-IP token bucket: 60 requests per 60-second window.

_rate_buckets: dict[str, list] = {}
_rate_lock = threading.Lock()
_RATE_LIMIT = 60
_RATE_WINDOW = 60


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request is within limits, False if it should be rejected."""
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.get(ip, [])
        bucket = [ts for ts in bucket if now - ts < _RATE_WINDOW]
        if len(bucket) >= _RATE_LIMIT:
            return False
        bucket.append(now)
        _rate_buckets[ip] = bucket
        return True


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/webhook")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification (Meta handshake)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("[WEBHOOK] Verification successful")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("[WEBHOOK] Verification failed")
    raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Parse incoming WhatsApp payload and dispatch processing to a background thread.

    Returns 200 immediately — WhatsApp requires a response within 5 seconds.
    Actual message handling (Calendar + WhatsApp API calls) runs in the thread pool
    via BackgroundTasks, so the event loop is never blocked.
    """
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        logger.warning(f"[WEBHOOK] Rate limit exceeded for {ip}")
        raise HTTPException(status_code=429, detail="Too Many Requests")

    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    try:
        entry = body.get("entry", [])
        if not entry:
            return {"status": "ok"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ok"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        for msg in messages:
            phone = msg.get("from", "")
            if not phone:
                continue

            # Deduplicate by message ID — handles WhatsApp retries
            message_id = msg.get("id", "")
            if message_id and _is_duplicate(message_id):
                logger.info(f"[WEBHOOK] Duplicate message_id={message_id} from {phone}, skipping")
                continue

            msg_type = msg.get("type", "")
            text: str | None = None
            interactive_id: str | None = None

            if msg_type == "text":
                text = msg.get("text", {}).get("body", "").strip()
                if not text:
                    continue
                logger.info(f"[WEBHOOK] text from {phone}: {text[:80]}")

            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                subtype = interactive.get("type", "")
                if subtype == "button_reply":
                    interactive_id = interactive.get("button_reply", {}).get("id", "")
                elif subtype == "list_reply":
                    interactive_id = interactive.get("list_reply", {}).get("id", "")
                if not interactive_id:
                    continue
                logger.info(f"[WEBHOOK] interactive from {phone}: {interactive_id}")

            else:
                # audio, image, video, sticker, location, etc. → trigger fallback
                logger.info(f"[WEBHOOK] unsupported type '{msg_type}' from {phone} → fallback")
                text = "__unknown__"

            # Dispatch to thread pool — does not block the event loop
            background_tasks.add_task(handle_message, phone=phone, text=text, interactive_id=interactive_id)

    except Exception as e:
        logger.error(f"[WEBHOOK] Error parsing payload: {e}", exc_info=True)

    return {"status": "ok"}
