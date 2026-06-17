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

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import (
    MAX_CONCURRENT_HANDLERS,
    WHATSAPP_APP_SECRET,
    WHATSAPP_VERIFY_TOKEN,
)
from app.handlers.conversation import handle_message
from app.utils import metrics
from app.utils.dedup import MessageDeduplicator
from app.utils.rate_limiter import RateLimiter
from app.utils.security import mask_phone

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Concurrency guard ──────────────────────────────────────────────────────
# Limits concurrent background handlers to prevent thread pool exhaustion.
_handler_semaphore = threading.Semaphore(MAX_CONCURRENT_HANDLERS)

# ── Rate limiters and deduplicator ─────────────────────────────────────────
ip_rate_limiter    = RateLimiter(limit=60, window_seconds=60)
phone_rate_limiter = RateLimiter(limit=20, window_seconds=60)
_deduplicator      = MessageDeduplicator(ttl_minutes=120)


def _handle_with_semaphore(phone: str, text, interactive_id):
    """Acquire semaphore before processing; release when done."""
    if not _handler_semaphore.acquire(blocking=False):
        logger.warning(
            "[WEBHOOK] Handler capacity exceeded, dropping message from %s",
            mask_phone(phone),
        )
        metrics.inc('handler_dropped')
        return
    try:
        handle_message(phone=phone, text=text, interactive_id=interactive_id)
    finally:
        _handler_semaphore.release()


# ── Constants ──────────────────────────────────────────────────────────────
MAX_PAYLOAD_BYTES       = 65_536   # 64 KB — plenty for any valid Meta webhook
_MAX_TEXT_LEN           = 4_096    # WhatsApp text message hard limit
_MAX_INTERACTIVE_ID_LEN = 256      # WhatsApp interactive payload ID limit

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


# ── Request helpers ────────────────────────────────────────────────────────

def _is_json_content(request: Request) -> bool:
    ct = request.headers.get("content-type", "").split(";")[0].strip()
    return ct == "application/json"


async def _read_body_safely(request: Request, ip: str) -> bytes | None:
    try:
        body_bytes = await request.body()
    except Exception:
        return None
    if len(body_bytes) > MAX_PAYLOAD_BYTES:
        logger.warning(f"[WEBHOOK] Oversized payload ({len(body_bytes)} B) from {ip}")
        raise HTTPException(status_code=413, detail="Payload Too Large")
    return body_bytes


def _parse_json_safely(body_bytes: bytes) -> dict | None:
    try:
        return json.loads(body_bytes)
    except Exception:
        return None


def _iter_messages(body: dict):
    entry = body.get("entry", [])
    if not entry:
        return
    changes = entry[0].get("changes", [])
    if not changes:
        return
    value = changes[0].get("value", {})
    yield from value.get("messages", [])


def _extract_text(msg: dict, phone: str) -> str | None:
    text = msg.get("text", {}).get("body", "").strip()
    if not text:
        return None
    if len(text) > _MAX_TEXT_LEN:
        logger.warning(f"[WEBHOOK] Text too long from {mask_phone(phone)}, truncating")
        text = text[:_MAX_TEXT_LEN]
    logger.info(f"[WEBHOOK] text from {mask_phone(phone)}: {text[:80]}")
    return text


def _extract_interactive_id(msg: dict, phone: str) -> str | None:
    interactive = msg.get("interactive", {})
    subtype = interactive.get("type", "")
    if subtype == "button_reply":
        id_ = interactive.get("button_reply", {}).get("id", "")
    elif subtype == "list_reply":
        id_ = interactive.get("list_reply", {}).get("id", "")
    else:
        return None
    if not id_:
        return None
    if len(id_) > _MAX_INTERACTIVE_ID_LEN:
        logger.warning(
            "[WEBHOOK] interactive_id too long from %s, skipping",
            mask_phone(phone),
        )
        return None
    logger.info(f"[WEBHOOK] interactive from {mask_phone(phone)}: {id_}")
    return id_


def _validate_and_extract(msg: dict, ip: str) -> dict | None:
    phone = msg.get("from", "")
    if not phone:
        return None
    if not _validate_phone(phone):
        logger.warning(f"[WEBHOOK] Invalid phone format: {mask_phone(phone)}")
        return None
    if not phone_rate_limiter.check(phone):
        logger.warning(f"[WEBHOOK] Phone rate limit exceeded for {mask_phone(phone)}")
        return None
    metrics.inc('messages_received')
    message_id = msg.get("id", "")
    if message_id and _deduplicator.seen(message_id):
        logger.info(
            "[WEBHOOK] Duplicate msg_id=%s from %s, skipping",
            message_id, mask_phone(phone),
        )
        return None
    msg_type = msg.get("type", "")
    if msg_type == "text":
        text = _extract_text(msg, phone)
        if text is None:
            return None
        return {"phone": phone, "text": text, "interactive_id": None}
    elif msg_type == "interactive":
        iid = _extract_interactive_id(msg, phone)
        if iid is None:
            return None
        return {"phone": phone, "text": None, "interactive_id": iid}
    else:
        # audio, image, sticker, etc. → trigger fallback menu
        logger.info(
            "[WEBHOOK] unsupported type '%s' from %s → fallback",
            msg_type, mask_phone(phone),
        )
        return {"phone": phone, "text": "__unknown__", "interactive_id": None}


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

    if not ip_rate_limiter.check(ip):
        logger.warning(f"[WEBHOOK] IP rate limit exceeded for {ip}")
        raise HTTPException(status_code=429, detail="Too Many Requests")

    if not _is_json_content(request):
        return {"status": "ok"}

    body_bytes = await _read_body_safely(request, ip)
    if body_bytes is None:
        return {"status": "ok"}

    signature = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(body_bytes, signature):
        logger.warning(f"[WEBHOOK] Invalid X-Hub-Signature-256 from {ip}")
        raise HTTPException(status_code=403, detail="Forbidden")

    body = _parse_json_safely(body_bytes)
    if body is None:
        return {"status": "ok"}

    try:
        for msg in _iter_messages(body):
            kwargs = _validate_and_extract(msg, ip)
            if kwargs:
                background_tasks.add_task(_handle_with_semaphore, **kwargs)
    except Exception as e:
        logger.error(f"[WEBHOOK] Error parsing payload: {e}", exc_info=True)

    return {"status": "ok"}
