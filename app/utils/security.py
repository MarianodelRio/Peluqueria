# utils/security.py
"""
Shared security utilities.
"""


def mask_phone(phone: str) -> str:
    """Mask phone number for safe logging — show only last 4 digits."""
    return f"****{phone[-4:]}" if len(phone) > 4 else "****"
