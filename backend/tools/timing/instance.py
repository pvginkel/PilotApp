"""The timing's PostgreSQL in the prd cluster's `development` namespace
(F154.9): kept between timings, so that the next one starts from the history
the last one wrote instead of writing it again.

    python3 tools/timing/instance.py up      # the Secret if none is held, instance.yaml, running
    python3 tools/timing/instance.py url     # the DATABASE_URL to reach it
    python3 tools/timing/instance.py stop    # stopped, its volume and its Secret kept
    python3 tools/timing/instance.py down    # the instance, its volume, its Secret

A timing ends with `stop`, which frees the instance's memory and CPUs and
keeps its database; `down` is for a history to be thrown away. Run where
`kubectl` is, with a context that writes `development` (in a KubeCoder
environment, `cexec iac`). Its superuser's password is drawn at the first
`up` into the Secret `pilot-timing`, which the database's volume was made
with, and read back from there: it is in no file. Standard library only, so
that it runs beside `kubectl` with no environment of the backend's.
"""

import argparse
import base64
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

NAMESPACE = "development"
NAME = "pilot-timing"
MANIFEST = Path(__file__).with_name("instance.yaml")


def _kubectl(context: str, *args: str, given: str | None = None) -> str:
    return subprocess.run(
        ["kubectl", "--context", context, "-n", NAMESPACE, *args],
        input=given,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def up(context: str) -> None:
    held = _kubectl(context, "get", "secret", NAME, "--ignore-not-found", "-o", "name")
    if not held:
        password = secrets.token_hex(24)
        _kubectl(
            context,
            "create",
            "secret",
            "generic",
            NAME,
            f"--from-literal=password={password}",
        )
    print(_kubectl(context, "apply", "-f", str(MANIFEST)), end="")
    print(_kubectl(context, "scale", f"statefulset/{NAME}", "--replicas=1"), end="")
    print(
        _kubectl(
            context,
            "rollout",
            "status",
            f"statefulset/{NAME}",
            "--timeout=600s",
        ),
        end="",
    )


def url(context: str) -> str:
    encoded = _kubectl(
        context, "get", "secret", NAME, "-o", "jsonpath={.data.password}"
    )
    password = base64.b64decode(encoded).decode()
    host = f"{NAME}.{NAMESPACE}.svc.cluster.local"
    return f"postgresql+psycopg://postgres:{quote(password)}@{host}:5432"


def stop(context: str) -> None:
    print(_kubectl(context, "scale", f"statefulset/{NAME}", "--replicas=0"), end="")
    _kubectl(context, "wait", "--for=delete", f"pod/{NAME}-0", "--timeout=120s")


def down(context: str) -> None:
    for kind, name in (
        ("statefulset", NAME),
        ("service", NAME),
        ("persistentvolumeclaim", f"data-{NAME}-0"),
        ("secret", NAME),
    ):
        print(_kubectl(context, "delete", kind, name, "--ignore-not-found"), end="")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("up", "url", "stop", "down"))
    parser.add_argument("--context", default="prd")
    args = parser.parse_args(argv)
    if args.command == "up":
        up(args.context)
    elif args.command == "url":
        print(url(args.context))
    elif args.command == "stop":
        stop(args.context)
    else:
        down(args.context)


if __name__ == "__main__":
    main(sys.argv[1:])
