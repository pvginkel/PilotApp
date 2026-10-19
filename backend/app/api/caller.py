"""The signed-in caller of an endpoint under the `editor` gate."""

from app.exceptions import AuthenticationException
from app.services.auth_service import AuthContext
from app.utils.auth import get_auth_context


def caller() -> AuthContext:
    """The caller the request's auth hook resolved.

    Raises:
        AuthenticationException: no one is signed in.
    """
    auth_context = get_auth_context()
    if auth_context is None:
        raise AuthenticationException("No valid token provided")
    return auth_context
