# Sign-in and access

Pilot signs its users in through Keycloak with the template's OIDC login, and admits only an account
that holds one role: `editor`, a client role of Pilot's Keycloak client `pilot-app` in the realm
`homelab` at `https://auth.ginbov.nl`. The operator makes the client and grants the role in
Keycloak. The role is the whole of access control: every holder sees and works every project, and
an account without it cannot use Pilot.

## What the backend checks

`AuthService` is wired with `editor` as both its read and its write role, and no admin role
(`backend/app/services/container.py`). With sign-in on (`OIDC_ENABLED`, as in production):

- **Every endpoint on the API blueprint needs `editor`**, reads included: the template's and every
  one `register_blueprints()` in `backend/app/startup.py` adds. A request with no valid token
  answers `401`; a valid token without the role, `403`.
- **The sign-in routes under `/api/auth/` are public.** `/api/auth/self` answers `401` with no
  valid session and `403` to a signed-in account without `editor`; the UI shows its "No Access"
  screen on that `403`, with signing out the only action.
- **Roles come from the token's realm roles and its client roles** for the audience
  (`resource_access.<audience>`; with `OIDC_AUDIENCE` unset the audience is the client id). A realm
  role named `editor` passes too.
- **The event stream `/api/sse/stream` has the same gate.** The UI's nginx proxies it to the SSE
  gateway, which opens a stream only after the backend's connect callback (`/api/sse/callback`)
  accepts it. The callback reads the token the browser sent, from the access-token cookie or an
  `Authorization` header, and answers `401` with no valid token and `403` to a token without
  `editor`. The gateway turns that refusal into a `rejected` event on the stream and ends it. The
  check runs only when a stream opens, so a stream already open stays open after its token
  expires.

On a `rejected` event the UI's shared worker stops reconnecting and asks `/api/auth/self`, which
refreshes an expired token: on `200` it opens a new stream, on `401` it goes to the login page, and
on anything else it shows a "connection lost" message. A browser without `SharedWorker`, and the
Vite dev server, use a plain `EventSource` instead, which does not act on `rejected` and keeps
retrying on its own.

## Without sign-in

With `OIDC_ENABLED` false, the default and the dev stack's setting, a request with no test session
is not gated, `/api/auth/self` answers a fixed local user, and the event stream is opened for that
user.

In testing mode a test session (`POST /api/testing/auth/session`) is checked like a token, by the
API and the event stream alike: it passes only if its roles include `editor`. The frontend suite's
`auth.createSession()` gives a session no roles unless told, so a test that signs in passes
`roles: ['editor']`. `POST /api/testing/sse/force-callback-error?status=401` (or `403`) makes the
next stream's connect callback refuse it, once.
