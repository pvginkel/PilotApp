#!/usr/bin/env python3
"""Create the development database if it does not exist yet.

The Postgres sidecar starts empty, so a fresh clone has no database for
`DATABASE_URL` to point at and `cli upgrade-db` fails before it can run a
migration. This creates it (and nothing else) — schema is Alembic's job.
It creates it in production's locale, as the test suites create theirs.

It reads DATABASE_URL as the app does: the environment, then .env, then the
app's default. `kc project setup` seeds .env before it runs this, so the
database it creates is the one `cli upgrade-db` migrates.

Idempotent: an existing database is left untouched, and one in another
locale is reported, not recreated: drop it and run this again. The test suites
never call this: they create their own databases
(tests/conftest_infrastructure.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv

DEFAULT_DATABASE_URL = (
    # Keep in step with Settings.database_url in app/config.py.
    "postgresql+psycopg://postgres:postgres@localhost:5432/pilot"
)

# Database that always exists, used to issue the CREATE DATABASE.
MAINTENANCE_DATABASE = "postgres"

# Production's locale: the clusters are initialised with ICU 'und' and C. The
# server's default (libc en_US.utf8 on the sidecar) sorts text differently.
# Keep in step with _DATABASE_LOCALE in tests/conftest_infrastructure.py.
DATABASE_LOCALE = (
    "ENCODING 'UTF8' LOCALE_PROVIDER icu ICU_LOCALE 'und' LC_COLLATE 'C' LC_CTYPE 'C'"
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    # Like the app's settings, a variable already in the environment wins.
    load_dotenv(_BACKEND_DIR / ".env")
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    parts = urlsplit(url)

    if not parts.scheme.startswith("postgresql"):
        print(f"Not a PostgreSQL URL, nothing to create: {parts.scheme}")
        return 0

    database = parts.path.lstrip("/")
    if not database:
        print(
            f"No database name in DATABASE_URL (host {parts.hostname})", file=sys.stderr
        )
        return 1

    # psycopg wants a plain postgresql:// conninfo, not SQLAlchemy's
    # dialect+driver form, and connecting to the maintenance database.
    maintenance_url = urlunsplit(
        ("postgresql", parts.netloc, f"/{MAINTENANCE_DATABASE}", "", "")
    )

    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        existing = conn.execute(
            "SELECT datlocprovider, datcollate FROM pg_database WHERE datname = %s",
            (database,),
        ).fetchone()
        if existing:
            print(f"Database '{database}' already exists")
            provider, collate = existing
            if provider != "i" or collate != "C":
                print(
                    f"Database '{database}' is not in production's locale (ICU 'und', "
                    "C): drop it and run this again to recreate it",
                    file=sys.stderr,
                )
            return 0

        # No parameter binding for identifiers in DDL.
        conn.execute(
            f'CREATE DATABASE "{database}" TEMPLATE template0 {DATABASE_LOCALE}'
        )
        print(f"Created database '{database}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
