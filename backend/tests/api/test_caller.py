"""The signed-in caller of an endpoint under the `editor` gate.

`app.api` is imported inside the tests: importing the package registers its
endpoints on the spectree instance the `app` fixture configures.
"""

import pytest
from flask import Flask, g

from app.exceptions import AuthenticationException
from app.services.auth_service import AuthContext


class TestCaller:
    def test_the_caller_the_auth_hook_resolved(self, app: Flask) -> None:
        from app.api.caller import caller

        signed_in = AuthContext(
            subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
        )

        with app.test_request_context():
            g.auth_context = signed_in

            assert caller() is signed_in

    def test_no_one_signed_in_is_unauthenticated(self, app: Flask) -> None:
        from app.api.caller import caller

        with app.test_request_context(), pytest.raises(AuthenticationException):
            caller()
