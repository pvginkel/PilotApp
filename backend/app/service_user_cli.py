"""`create-service-user`: the row of a service user, the party a session
outside Pilot calls Pilot's projects surface as (F150.13; DB decision 77, 338).

No sign-in step makes the row, and none rewrites it: the command writes its
handle, its name and its subject, the service account of the Keycloak client
whose credential the calls carry. The subject is the `sub` claim of a token
minted from that client, which the backend logs for every authenticated
request.
"""

import sys

import click

from app.app import App
from app.database import scoped_session
from app.exceptions import InvalidOperationException, ValidationException


@click.command()
@click.option(
    "--handle",
    required=True,
    help="Its handle: lower-case letters, digits and hyphens; never changed after.",
)
@click.option("--name", required=True, help="Its name, as an author's avatar shows it.")
@click.option(
    "--subject",
    required=True,
    help="The `sub` claim of its client's tokens: the client's service account.",
)
@click.pass_context
def create_service_user(
    ctx: click.Context, handle: str, name: str, subject: str
) -> None:
    """Make a service user's row: a User of kind `service`."""
    handle_create_service_user(
        ctx.obj["app"], handle=handle, name=name, subject=subject
    )


def handle_create_service_user(
    app: App, *, handle: str, name: str, subject: str
) -> None:
    """Make the row and say so; exits 1 at a refusal, nothing written."""
    container = app.container
    with app.app_context():
        try:
            with scoped_session(container):
                container.people_service().make_service_user(handle, name, subject)
        except (InvalidOperationException, ValidationException) as refused:
            print(refused.message, file=sys.stderr)
            sys.exit(1)
    print(f"Made the service user {handle!r}, named {name!r}, of subject {subject!r}.")
