"""The browser page that sent a write: the frontend's generated mutation
hooks name it in each request's `X-Sender` header (`SENDER`), and read every
query again once the write is answered."""

import re

from flask import has_request_context, request

SENDER_HEADER = "X-Sender"

_SENDER = re.compile(r"[a-z0-9]{1,64}")
"""A page's name: the frontend makes one of 32 lowercase letters and digits.
Any other value names no page."""


def current_sender() -> str | None:
    """The page that sent the request being served, where it named one."""
    if not has_request_context():
        return None
    sender = request.headers.get(SENDER_HEADER, "")
    return sender if _SENDER.fullmatch(sender) else None
