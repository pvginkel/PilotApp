"""base64url without padding, as the Push API writes a browser's keys and
VAPID a public key (RFC 4648 §5)."""

import base64


def b64(value: bytes) -> str:
    """`value` in base64url, its padding left off."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    """A base64url value, its padding left off or not."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
