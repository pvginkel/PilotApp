#!/usr/bin/env python3
"""Create the development database if it does not exist yet.

The Postgres sidecar starts empty, so a fresh clone has no database for
`DATABASE_URL` to point at and `cli upgrade-db` fails before it can run a
migration. This creates it (and nothing else) — schema is Alembic's job.

Idempotent: an existing database is left untouched. Tests never call this;
they run on SQLite.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg

# Keep in step with Settings.database_url in app/config.py.
DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/pilot"

# Database that always exists, used to issue the CREATE DATABASE.
MAINTENANCE_DATABASE = "postgres"


def main() -> int:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    parts = urlsplit(url)

    if not parts.scheme.startswith("postgresql"):
        print(f"Not a PostgreSQL URL, nothing to create: {parts.scheme}")
        return 0

    database = parts.path.lstrip("/")
    if not database:
        print(f"No database name in DATABASE_URL: {url}", file=sys.stderr)
        return 1

    # psycopg wants a plain postgresql:// conninfo, not SQLAlchemy's
    # dialect+driver form, and connecting to the maintenance database.
    maintenance_url = urlunsplit(
        ("postgresql", parts.netloc, f"/{MAINTENANCE_DATABASE}", "", "")
    )

    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if exists:
            print(f"Database '{database}' already exists")
            return 0

        # No parameter binding for identifiers in DDL.
        conn.execute(f'CREATE DATABASE "{database}"')
        print(f"Created database '{database}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
