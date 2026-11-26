"""Pilot as a walk calls it (F152.1, F152.2, F152.6): its inventory, a
publication of one transcript, the labeller's vocabularies and the walk's
end, the four routes behind Pilot's door for a collector.

Every call carries the collector's bearer and names the version of the
collector's API it speaks. An answer is the call's own, or one of five
failures a walk tells apart: `NotAppendable`, an appended publication that
does not continue what Pilot holds, whose transcript is then published
whole; `NotAdoptable`, a publication's `group` for a transcript a Session of
Pilot's ran, which is then published without it; `Refused`, the same call
refused again, which costs the walk that transcript, or the vocabularies;
`NotAdmitted`, no call of this collector's taken; and `Unreachable`, no
answer of Pilot's to the call.
"""

from typing import Any, Self

import httpx
from pilot_collection.inventory import InventorySchema
from pilot_collection.publication import CollectorProtocolRangeSchema, PublicationSchema
from pilot_collection.vocabularies import VocabulariesSchema
from pydantic import ValidationError

PROTOCOL = 2
"""The version of the collector's API these calls speak."""

_ROUTES = "/api/collector"

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
"""Seconds a call waits on Pilot: to connect, and for each part of an answer.
A publication is one transaction on Pilot's side, the largest transcript's
included."""

_SAID = 2_000
"""The characters of a refusal's body a message quotes."""

_NOT_APPENDABLE = "PUBLICATION_NOT_APPENDABLE"
"""The `code` of the 409 that refuses an appended publication."""

_NOT_ADOPTABLE = "TRANSCRIPT_NOT_ADOPTABLE"
"""The `code` of the 409 that refuses a publication's `group`."""

_NO_SERVICE_USER = "NO_SERVICE_USER"
"""The `code` of the 409 that refuses a publication's `group` no project
holds yet, on a stage with no service user to make one."""


class NotAppendable(Exception):
    """Pilot refused an appended publication: it does not continue what
    Pilot holds of the transcript. The message has Pilot's reasons."""


class NotAdoptable(Exception):
    """Pilot refused a publication's `group`: a Session of Pilot's ran the
    transcript, and the same call without its `group` is taken."""


class Refused(Exception):
    """Pilot refused a publication or a declaration, and refuses the same
    call again: it does not validate, its body is too large, or its `group`
    names no project and the stage has no service user to make one."""


class NotAdmitted(Exception):
    """Pilot takes no call of this collector's: its bearer or its protocol
    version is not Pilot's."""


class Unreachable(Exception):
    """Pilot gave the call no answer, or one that is none of the call's."""


class Pilot:
    """The collector's calls to one Pilot, over connections it keeps."""

    def __init__(self, url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=url.rstrip("/") + _ROUTES,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Pilot-Collector-Protocol": str(PROTOCOL),
            },
            timeout=_TIMEOUT,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def inventory(self) -> InventorySchema:
        """What Pilot holds, whole, and the walk's two settings."""
        answer = self._call("GET", "/inventory")
        if answer.status_code != 200:
            raise Unreachable(_unexpected(answer))
        try:
            return InventorySchema.model_validate_json(answer.content)
        except ValidationError as error:
            raise Unreachable(f"Pilot's inventory is none: {error}") from error

    def publish(self, publication: PublicationSchema) -> None:
        """Publish one transcript: Pilot then holds it as the call says.

        Raises:
            NotAppendable: Pilot answered 409 `PUBLICATION_NOT_APPENDABLE`.
            NotAdoptable: Pilot answered 409 `TRANSCRIPT_NOT_ADOPTABLE`.
            Refused: Pilot answered 400, 413 or 409 `NO_SERVICE_USER`; the
                message has what it said.
        """
        answer = self._call(
            "POST",
            "/publications",
            content=publication.model_dump_json(exclude_none=True),
            headers={"Content-Type": "application/json"},
        )
        if answer.status_code == 409:
            try:
                said = answer.json()
            except ValueError:
                said = None
            code = said.get("code") if isinstance(said, dict) else None
            if code == _NOT_APPENDABLE:
                raise NotAppendable(str(said.get("error"))[:_SAID])
            if code == _NOT_ADOPTABLE:
                raise NotAdoptable(str(said.get("error"))[:_SAID])
            if code == _NO_SERVICE_USER:
                raise Refused(f"409: {_reason(answer)}")
        if answer.status_code in (400, 413):
            raise Refused(f"{answer.status_code}: {answer.text[:_SAID]}")
        if answer.status_code != 204:
            raise Unreachable(_unexpected(answer))

    def declare(self, vocabularies: VocabulariesSchema) -> None:
        """Declare the labeller's vocabularies, whole: Pilot then holds them
        as the call says.

        Raises:
            Refused: Pilot answered 400 or 413; the message has its reason,
                the same at each refusal of the same call.
        """
        answer = self._call(
            "PUT",
            "/vocabularies",
            content=vocabularies.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
        if answer.status_code in (400, 413):
            raise Refused(f"{answer.status_code}: {_reason(answer)}")
        if answer.status_code != 204:
            raise Unreachable(_unexpected(answer))

    def end_walk(self) -> None:
        """Tell Pilot a walk ended, after the walk's last publication."""
        answer = self._call("POST", "/walks")
        if answer.status_code != 204:
            raise Unreachable(_unexpected(answer))

    def _call(self, method: str, path: str, **sent: Any) -> httpx.Response:
        try:
            answer = self._client.request(method, path, **sent)
        except httpx.HTTPError as error:
            raise Unreachable(
                f"Pilot did not answer: {type(error).__name__}: {error}"
            ) from error
        if answer.status_code == 401:
            raise NotAdmitted("Pilot does not take the collector's bearer")
        if answer.status_code == 426:
            try:
                taken = CollectorProtocolRangeSchema.model_validate_json(answer.content)
            except ValidationError as error:
                raise Unreachable(_unexpected(answer)) from error
            raise NotAdmitted(
                f"Pilot takes the protocol versions {taken.min} to {taken.max},"
                f" and the collector speaks {PROTOCOL}"
            )
        return answer


def _reason(answer: httpx.Response) -> str:
    """The `error` of an answer's body, Pilot's reason for it without the
    call's own correlation id; the body, where it holds none."""
    try:
        said = answer.json()
    except ValueError:
        said = None
    reason = said.get("error") if isinstance(said, dict) else None
    return (reason if isinstance(reason, str) else answer.text)[:_SAID]


def _unexpected(answer: httpx.Response) -> str:
    return f"Pilot answered {answer.status_code}: {answer.text[:_SAID]}"
