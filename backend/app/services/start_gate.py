"""The gate every start passes (design 2 §13.4, D11; F141.5; DB 229).

A start is held while the controller is unreachable or its project is paused,
a Chat's never for the pause (F141.4). The halt is slice 016's condition, and
the slot slice 020's. The project's pause comes first where both hold: the
outage is the gold bar's.
"""

from app.schemas.timeline import HeldReason

CHAT_KIND = "chat"


def held_reason(
    *, paused: bool, kind_code: str, unreachable: bool
) -> HeldReason | None:
    """Why the gate holds a start of a Session of `kind_code` in a project
    `paused` or not, the controller `unreachable` or not; None while it is
    open."""
    if paused and kind_code != CHAT_KIND:
        return HeldReason.PAUSED
    if unreachable:
        return HeldReason.CONTROLLER_UNREACHABLE
    return None
