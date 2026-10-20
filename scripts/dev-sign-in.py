#!/usr/bin/env python3
"""Sign in to the dev stage as its test account, through Keycloak's login page.

Usage:
    scripts/dev-sign-in.py [base URL]      # https://pilot-dev.home by default

The deployed checks of docs/slice-test-plan.md §4 sign in to pilot-dev as the
test account, a user of production's realm holding the dev client's `editor`
role alone. Its username and password come from PILOT_DEV_TEST_USERNAME and
PILOT_DEV_TEST_PASSWORD, which this environment projects from its secret
catalog (.kubecoder/config.yaml). Neither is printed, nor is anything that
carries one: Keycloak's pages echo the username back, and the email
/api/auth/self answers is the username, since the realm signs in by email.

The script walks the app's own flow, as a browser does: the app's login route,
Keycloak's login form, the form's post, the app's callback. It prints a line
per step, ending in the roles /api/auth/self reports. The session is the app's
cookies (access_token, refresh_token, id_token), written to tmp/dev-session/ in
two forms, both readable by this user alone:

- cookies.txt, curl's cookie jar: `-b` sends it, `-c` keeps the cookies a
  refresh replaces.
- state.json, a Playwright context's `storageState`.

Exit 0 signed in as an editor; 1 a step answered otherwise, named; 2 the two
variables unset.
"""

import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_DIR = ROOT / "tmp" / "dev-session"
DEFAULT_BASE = "https://pilot-dev.home"
TIMEOUT = 15

# Markers of the pages Keycloak answers a form post with when it does not
# redirect, by the element id its default theme gives each.
KEYCLOAK_PAGES = {
    "kc-form-login": "the login form again: Keycloak refused the credentials",
    "kc-passwd-update-form": "a required action: update the password",
    "kc-otp-login-form": "a one-time code",
    "kc-totp-settings": "a required action: configure a one-time code",
    "kc-update-profile-form": "a required action: update the profile",
    "kc-update-email-form": "a required action: update the email",
    "kc-terms-text": "a required action: accept the terms",
    "kc-verify-email": "a required action: verify the email",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Step(Exception):
    pass


def fail(message: str) -> None:
    raise Step(message)


def request(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body)
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode(errors="replace")


def login_form_action(page: str) -> str:
    form = re.search(r'<form\b[^>]*\bid="kc-form-login"[^>]*>', page)
    if not form:
        fail('Keycloak\'s answer holds no login form (id="kc-form-login")')
    action = re.search(r'\baction="([^"]+)"', form.group(0))
    if not action:
        fail("Keycloak's login form has no action")
    return html.unescape(action.group(1))


def keycloak_page(page: str) -> str:
    for marker, meaning in KEYCLOAK_PAGES.items():
        if f'id="{marker}"' in page:
            return meaning
    return "a page this script does not know"


def sign_in(base: str, username: str, password: str) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), NoRedirect
    )

    status, _, _ = request(opener, f"{base}/api/auth/self")
    print(f"anonymous /api/auth/self: {status}")
    if status != 401:
        fail(f"an anonymous /api/auth/self answered {status}, not 401")

    status, headers, _ = request(opener, f"{base}/api/auth/login?redirect=/")
    authorize = headers.get("Location", "")
    if status != 302 or not authorize:
        fail(f"the login route answered {status}, not a 302 to Keycloak")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorize).query)
    endpoint = authorize.split("?", 1)[0]
    redirect_uri = query.get("redirect_uri", ["none"])[0]
    print(f"login: 302 to {endpoint}, redirect_uri {redirect_uri}")

    status, _, page = request(opener, authorize)
    if status != 200:
        error = re.search(r"Client not found\.|Invalid parameter: [a-z_]+", page)
        fail(
            f"Keycloak's authorization endpoint answered {status}"
            f" ({error.group(0) if error else 'no error message'})"
        )
    action = login_form_action(page)
    print("Keycloak: 200, the login form")

    status, headers, page = request(
        opener,
        action,
        {"username": username, "password": password, "credentialId": ""},
    )
    callback = headers.get("Location", "")
    if status != 302:
        fail(f"the form's post answered {status} with {keycloak_page(page)}")
    if not callback.startswith(f"{base}/api/auth/callback?") or "code=" not in callback:
        fail("the form's post redirected elsewhere than the app's callback")
    print("the form's post: 302 to the app's callback, with a code")

    status, headers, _ = request(opener, callback)
    if status != 302:
        fail(f"the app's callback answered {status}, not 302")
    names = sorted(
        c.name for c in jar if c.domain == urllib.parse.urlsplit(base).hostname
    )
    print(f"callback: 302 to {headers.get('Location')}, cookies {names}")

    status, _, body = request(opener, f"{base}/api/auth/self")
    if status != 200:
        fail(f"a signed-in /api/auth/self answered {status}, not 200")
    roles = json.loads(body)["roles"]
    print(f"signed-in /api/auth/self: 200, roles {roles}")
    if "editor" not in roles:
        fail("the session holds no editor role")
    return jar


def save(jar: http.cookiejar.CookieJar, host: str) -> None:
    cookies = [c for c in jar if c.domain == host]
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SESSION_DIR, 0o700)

    def write(name: str, text: str) -> None:
        fd = os.open(SESSION_DIR / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)

    write(
        "cookies.txt",
        "# Netscape HTTP Cookie File\n"
        + "".join(
            f"#HttpOnly_{c.domain}\tFALSE\t{c.path}\t{'TRUE' if c.secure else 'FALSE'}"
            f"\t{c.expires or 0}\t{c.name}\t{c.value}\n"
            for c in cookies
        ),
    )
    write(
        "state.json",
        json.dumps(
            {
                "cookies": [
                    {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path,
                        "expires": c.expires or -1,
                        "httpOnly": True,
                        "secure": c.secure,
                        "sameSite": c.get_nonstandard_attr("SameSite", "Lax"),
                    }
                    for c in cookies
                ],
                "origins": [],
            }
        ),
    )
    print(f"session: {SESSION_DIR.relative_to(ROOT)}/cookies.txt and state.json")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")
    username = os.environ.get("PILOT_DEV_TEST_USERNAME", "")
    password = os.environ.get("PILOT_DEV_TEST_PASSWORD", "")
    if not username or not password:
        print("PILOT_DEV_TEST_USERNAME or PILOT_DEV_TEST_PASSWORD is unset")
        return 2
    try:
        jar = sign_in(base, username, password)
    except Step as e:
        print(f"FAIL: {e}")
        return 1
    save(jar, urllib.parse.urlsplit(base).hostname or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
