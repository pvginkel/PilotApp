"""Pytest configuration and fixtures.

Infrastructure fixtures (app, client, session, OIDC, SSE) are defined in
conftest_infrastructure.py. This file re-exports them and adds app-specific
domain fixtures.

A fixture defined here after the import replaces the template's fixture of
the same name. To change the settings the test apps are built from, replace
``test_settings`` or ``test_app_settings``. With a database they are
session-scoped, because the app is, and a replacement keeps that scope.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import Environment, Project, User
from app.models.reference import UserKind

# Import all infrastructure fixtures
from tests.conftest_infrastructure import *  # noqa: F403


@pytest.fixture
def person(session: Session) -> User:
    """A person who has signed in."""
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-ada",
        handle="ada",
        name="Ada Example",
        avatar_slot=1,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def project(session: Session, person: User) -> Project:
    """A draft, created by ``person``."""
    draft = Project(created_by_user_id=person.id)
    session.add(draft)
    session.flush()
    return draft


@pytest.fixture
def environment(session: Session) -> Environment:
    """An environment Pilot has touched."""
    touched = Environment(id="example-env-1", name="Example-1", exempt=False)
    session.add(touched)
    session.flush()
    return touched
