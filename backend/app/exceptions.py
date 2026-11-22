"""Base exceptions with user-ready messages.

These are template-provided base exceptions that all apps need. Add
app-specific exceptions below these base classes.
"""

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.dashboard.refusal import Fault


class ConfigurationError(Exception):
    """Raised when application configuration is invalid."""

    pass


class BusinessLogicException(Exception):
    """Base exception class for business logic errors.

    All business logic exceptions include user-ready messages that can be
    displayed directly in the UI without client-side message construction.
    """

    def __init__(self, message: str, error_code: str) -> None:
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class RecordNotFoundException(BusinessLogicException):
    """Exception raised when a requested record is not found."""

    def __init__(self, resource_type: str, identifier: str | int) -> None:
        message = f"{resource_type} {identifier} was not found"
        super().__init__(message, error_code="RECORD_NOT_FOUND")


class ResourceConflictException(BusinessLogicException):
    """Exception raised when attempting to create a resource that already exists."""

    def __init__(self, resource_type: str, identifier: str | int) -> None:
        message = f"A {resource_type.lower()} with {identifier} already exists"
        super().__init__(message, error_code="RESOURCE_CONFLICT")


class InvalidOperationException(BusinessLogicException):
    """Exception raised when an operation cannot be performed due to business rules."""

    def __init__(self, operation: str, cause: str) -> None:
        self.operation = operation
        self.cause = cause
        message = f"Cannot {operation} because {cause}"
        super().__init__(message, error_code="INVALID_OPERATION")


class RouteNotAvailableException(BusinessLogicException):
    """Exception raised when accessing endpoints that are not available in the current mode."""

    def __init__(
        self,
        message: str = "This endpoint is only available when the server is running in testing mode",
    ) -> None:
        super().__init__(message, error_code="ROUTE_NOT_AVAILABLE")


class AuthenticationException(BusinessLogicException):
    """Exception raised when authentication fails (missing, invalid, or expired token)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AUTHENTICATION_REQUIRED")


class AuthorizationException(BusinessLogicException):
    """Exception raised when the authenticated user lacks required permissions."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AUTHORIZATION_FAILED")


class ValidationException(BusinessLogicException):
    """Exception raised for request validation failures (malformed input, invalid redirect, etc.)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="VALIDATION_FAILED")


class StateRefusedException(ValidationException):
    """Raised when a view's state of the dashboard has faults; its message is
    the refusal's text, which names every fault and ends on a correct example
    of each kind of part refused (F154.2), and `faults` holds each one."""

    def __init__(self, text: str, faults: tuple["Fault", ...]) -> None:
        super().__init__(text)
        self.error_code = "STATE_REFUSED"
        self.faults = faults


class SyncProtocolUnsupportedException(BusinessLogicException):
    """Raised when a sync call speaks a protocol version outside the range the
    server accepts; answered 426 with the range (design 1 §5.1)."""

    def __init__(self, version: str | None, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = maximum
        message = (
            f"Cannot sync because protocol version {version!r} is outside"
            f" {minimum} to {maximum}"
        )
        super().__init__(message, error_code="SYNC_PROTOCOL_UNSUPPORTED")


class CollectorProtocolUnsupportedException(BusinessLogicException):
    """Raised when a collector's call speaks a protocol version outside the
    range the server accepts; answered 426 with the range."""

    def __init__(self, version: str | None, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = maximum
        message = (
            f"Cannot take the collector's call because protocol version {version!r}"
            f" is outside {minimum} to {maximum}"
        )
        super().__init__(message, error_code="COLLECTOR_PROTOCOL_UNSUPPORTED")


class PublicationInvalidException(ValidationException):
    """Raised when a collector's publication contradicts itself or the
    record's rules for a Transcript; `faults` names each one, and nothing of
    the call is written."""

    def __init__(self, transcript: str, faults: list[str]) -> None:
        self.faults = faults
        super().__init__(
            f"Cannot take the publication of transcript {transcript} because "
            + "; ".join(faults)
        )


class PublicationNotAppendableException(InvalidOperationException):
    """Raised when an appended publication does not continue what Pilot
    holds of its Transcript; `causes` names each reason, and nothing of the
    call is written. Its code tells the collector to publish the transcript
    whole."""

    def __init__(self, transcript: str, causes: list[str]) -> None:
        self.causes = causes
        super().__init__(f"append to transcript {transcript}", "; ".join(causes))
        self.error_code = "PUBLICATION_NOT_APPENDABLE"


class TranscriptNotAdoptableException(InvalidOperationException):
    """Raised when a publication names a group for a Transcript a Session of
    Pilot's ran, which no adopted Project adopts (DB 539); nothing of the
    call is written."""

    def __init__(self, transcript: str, group: str) -> None:
        super().__init__(
            f"adopt transcript {transcript} into the group {group!r}",
            "a session of Pilot's ran it",
        )
        self.error_code = "TRANSCRIPT_NOT_ADOPTABLE"


class NoServiceUserException(InvalidOperationException):
    """Raised when a publication first names a group while the stage holds no
    service user, an adopted Project's creator (DB 584); nothing of the call
    is written."""

    def __init__(self, group: str) -> None:
        super().__init__(
            f"make the adopted project of the group {group!r}",
            "the stage has no service user to make it",
        )
        self.error_code = "NO_SERVICE_USER"


QueryRefusal = Literal["timeout", "temp_file_limit", "busy"]


class QueryRefusedException(InvalidOperationException):
    """Raised when the dashboard's engine cannot answer a view within its
    bounds (F154.5): `reason` says which, a statement past the engine's
    timeout, one the database ended at its limit on temporary files, or no
    slot among the engine's statements at once freed within the timeout."""

    def __init__(self, reason: QueryRefusal, cause: str) -> None:
        super().__init__("answer the dashboard's view", cause)
        self.reason = reason
        self.error_code = {
            "timeout": "QUERY_TIMEOUT",
            "temp_file_limit": "QUERY_TEMP_FILE_LIMIT",
            "busy": "QUERY_BUSY",
        }[reason]
