# handlers/webhook.py
"""
WhatsApp webhook endpoints.
GET: Meta verification handshake.
POST: incoming messages — text, interactive, and unknown types.

Security measures:
- X-Hub-Signature-256 HMAC verification (requires WHATSAPP_APP_SECRET in .env).
- Content-Type: application/json enforced on POST.
- Payload size capped at 64 KB.
- Per-IP and per-phone rate limiting.
- Phone format validation (E.164: digits only, 7-15 chars).
- Text and interactive_id length limits.
- Phone numbers masked in all log lines.
- Deduplication by message ID (handles WhatsApp retries).
"""
import hashlib
import hmac as _hmac
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import MAX_CONCURRENT_HANDLERS, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
from app.handlers.conversation import handle_message
from app.utils import metrics
from app.utils.security import mask_phone

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Concurrency guard ──────────────────────────────────────────────────────
# Limits concurrent background handlers to prevent thread pool exhaustion.
_handler_semaphore = threading.Semaphore(MAX_CONCURRENT_HANDLERS)


def _handle_with_semaphore(phone: str, text, interactive_id):
    """Acquire semaphore before processing; release when done."""
    if not _handler_semaphore.acquire(blocking=False):
        logger.warning(f"[WEBHOOK] Handler capacity exceeded, dropping message from {mask_phone(phone)}")
        metrics.inc('handler_dropped')
        return
    try:
        handle_message(phone=phone, text=text, interactive_id=interactive_id)
    finally:
        _handler_semaphore.release()


# ── Constants ──────────────────────────────────────────────────────────────
MAX_PAYLOAD_BYTES      = 65_536   # 64 KB — plenty for any valid Meta webhook
_MAX_TEXT_LEN          = 4_096    # WhatsApp text message hard limit
_MAX_INTERACTIVE_ID_LEN = 256     # WhatsApp interactive payload ID limit

# ── Message deduplication ──────────────────────────────────────────────────
_processed_ids: dict[str, datetime] = {}
_processed_ids_lock = threading.Lock()
_PROCESSED_ID_TTL = timedelta(minutes=10)


def _is_duplicate(message_id: str) -> bool:
    """Return True if this message_id was already processed (with TTL cleanup)."""
    now = datetime.now()
    with _processed_ids_lock:
        expired = [k for k, ts in _processed_ids.items() if now - ts > _PROCESSED_ID_TTL]
        for k in expired:
            del _processed_ids[k]
        if message_id in _processed_ids:
            return True
        _processed_ids[message_id] = now
        return False


# ── Rate limiting — per IP ─────────────────────────────────────────────────
_rate_buckets: dict[str, list] = {}
_rate_lock = threading.Lock()
_RATE_LIMIT  = 60   # requests
_RATE_WINDOW = 60   # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if within limit. Stale bucket entries are filtered on each call."""
    now = time.time()
    with _rate_lock:
        bucket = [ts for ts in _rate_buckets.get(ip, []) if now - ts < _RATE_WINDOW]
        if len(bucket) >= _RATE_LIMIT:
            _rate_buckets[ip] = bucket
            return False
        bucket.append(now)
        _rate_buckets[ip] = bucket
        return True


# ── Rate limiting — per phone ──────────────────────────────────────────────
_phone_rate_buckets: dict[str, list] = {}
_phone_rate_lock = threading.Lock()
_PHONE_RATE_LIMIT  = 20   # messages per phone
_PHONE_RATE_WINDOW = 60   # seconds


def _check_phone_rate_limit(phone: str) -> bool:
    """Return True if within per-phone limit."""
    now = time.time()
    with _phone_rate_lock:
        bucket = [ts for ts in _phone_rate_buckets.get(phone, []) if now - ts < _PHONE_RATE_WINDOW]
        if len(bucket) >= _PHONE_RATE_LIMIT:
            _phone_rate_buckets[phone] = bucket
            return False
        bucket.append(now)
        _phone_rate_buckets[phone] = bucket
        return True


# ── Input helpers ──────────────────────────────────────────────────────────
_PHONE_RE = re.compile(r'^\d{7,15}$')


def _validate_phone(phone: str) -> bool:
    """Validate phone: digits only, E.164 length (7–15 digits)."""
    return bool(_PHONE_RE.match(phone))


# ── HMAC signature verification ────────────────────────────────────────────

def _verify_signature(body_bytes: bytes, signature_header: str) -> bool:
    """
    Verify X-Hub-Signature-256 HMAC header sent by Meta on every POST.
    Uses hmac.compare_digest to prevent timing-attack leakage.
    If WHATSAPP_APP_SECRET is not configured, verification is skipped
    (a warning is emitted at startup by validate_config()).
    """
    if not WHATSAPP_APP_SECRET:
        return True  # disabled — warned at startup
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = _hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return _hmac.compare_digest(expected, received)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/webhook")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification (Meta handshake)."""
    params    = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
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
    Actual message handling (Calendar + WhatsApp API calls) runs in the thread pool.
    """
    ip = request.client.host if request.client else "unknown"

    # 1. IP rate limit
    if not _check_rate_limit(ip):
        logger.warning(f"[WEBHOOK] IP rate limit exceeded for {ip}")
        raise HTTPException(status_code=429, detail="Too Many Requests")

    # 2. Content-Type must be application/json
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type != "application/json":
        return {"status": "ok"}

    # 3. Read raw body bytes (must happen before JSON parse — required for HMAC)
    try:
        body_bytes = await request.body()
    except Exception:
        return {"status": "ok"}

    # 4. Payload size limit
    if len(body_bytes) > MAX_PAYLOAD_BYTES:
        logger.warning(f"[WEBHOOK] Oversized payload ({len(body_bytes)} B) from {ip}")
        raise HTTPException(status_code=413, detail="Payload Too Large")

    # 5. HMAC-SHA256 signature verification
    signature = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(body_bytes, signature):
        logger.warning(f"[WEBHOOK] Invalid X-Hub-Signature-256 from {ip}")
        raise HTTPException(status_code=403, detail="Forbidden")

    # 6. Parse JSON
    try:
        body = json.loads(body_bytes)
    except Exception:
        return {"status": "ok"}

    try:
        entry = body.get("entry", [])
        if not entry:
            return {"status": "ok"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ok"}

        value    = changes[0].get("value", {})
        messages = value.get("messages", [])

        for msg in messages:
            phone = msg.get("from", "")
            if not phone:
                continue

            # 7. Validate phone format
            if not _validate_phone(phone):
                logger.warning(f"[WEBHOOK] Invalid phone format: {mask_phone(phone)}")
                continue

            # 8. Per-phone rate limit
            if not _check_phone_rate_limit(phone):
                logger.warning(f"[WEBHOOK] Phone rate limit exceeded for {mask_phone(phone)}")
                continue

            # 9. Count all inbound messages (before dedup) and deduplicate
            metrics.inc('messages_received')
            message_id = msg.get("id", "")
            if message_id and _is_duplicate(message_id):
                logger.info(f"[WEBHOOK] Duplicate msg_id={message_id} from {mask_phone(phone)}, skipping")
                continue

            msg_type: str       = msg.get("type", "")
            text: str | None    = None
            interactive_id: str | None = None

            if msg_type == "text":
                text = msg.get("text", {}).get("body", "").strip()
                if not text:
                    continue
                # 10. Text length limit
                if len(text) > _MAX_TEXT_LEN:
                    logger.warning(f"[WEBHOOK] Text too long from {mask_phone(phone)}, truncating")
                    text = text[:_MAX_TEXT_LEN]
                logger.info(f"[WEBHOOK] text from {mask_phone(phone)}: {text[:80]}")

            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                subtype     = interactive.get("type", "")
                if subtype == "button_reply":
                    interactive_id = interactive.get("button_reply", {}).get("id", "")
                elif subtype == "list_reply":
                    interactive_id = interactive.get("list_reply", {}).get("id", "")
                if not interactive_id:
                    continue
                # 11. Interactive ID length limit
                if len(interactive_id) > _MAX_INTERACTIVE_ID_LEN:
                    logger.warning(f"[WEBHOOK] interactive_id too long from {mask_phone(phone)}, skipping")
                    continue
                logger.info(f"[WEBHOOK] interactive from {mask_phone(phone)}: {interactive_id}")

            else:
                # audio, image, sticker, etc. → trigger fallback menu
                logger.info(f"[WEBHOOK] unsupported type '{msg_type}' from {mask_phone(phone)} → fallback")
                text = "__unknown__"

            # Dispatch to thread pool — never blocks the event loop
            background_tasks.add_task(
                _handle_with_semaphore, phone=phone, text=text, interactive_id=interactive_id
            )

    except Exception as e:
        logger.error(f"[WEBHOOK] Error parsing payload: {e}", exc_info=True)

    return {"status": "ok"}
