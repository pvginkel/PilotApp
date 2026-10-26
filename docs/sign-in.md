# Sign-in and access

Pilot signs its users in through Keycloak with the template's OIDC login, and admits only an account
that holds one role: `editor`, a client role of its stage's Keycloak client in the realm `homelab`
at `https://auth.ginbov.nl`: production's client is `pilot-app`, and the dev stage has one of its
own ([`deployment.md`](deployment.md)). The operator makes each client and grants its `editor` in
Keycloak, each stage's apart from the other's. The role is the whole of access control: every holder
sees and works every project, and an account without it cannot use Pilot.

Keycloak keeps no handle, the short name that stands for a person in Pilot's files, so a person
chooses theirs at their first sign-in, before the app opens, and is on Pilot's record from then
(below).

## What the backend checks

`AuthService` is wired with `editor` as both its read and its write role, and no admin role
(`backend/app/services/container.py`). With sign-in on (`OIDC_ENABLED`, as in both deployed stages):

- **Every endpoint on the API blueprint needs `editor`**, reads included: the template's and every
  one `register_blueprints()` in `backend/app/startup.py` adds. A request with no valid token
  answers `401`; a valid token without the role, `403`.
- **The sign-in routes under `/api/auth/` are public.** `/api/auth/self` answers `401` with no
  valid session and `403` to a signed-in account without `editor`; the UI shows its "No Access"
  screen on that `403`, with signing out the only action.
- **Roles come from the token's realm roles and its client roles** for the audience
  (`resource_access.<audience>`; with `OIDC_AUDIENCE` unset the audience is the client id). A realm
  role named `editor` passes too.
- **The event stream `/api/sse/stream` has the same gate.** The backend serves it, and the UI's
  nginx proxies it with the rest of `/api/`. It reads the token from the access-token cookie, the
  one an `EventSource` sends, and refreshes an expired one from the refresh cookie. It refuses in
  the stream, since an `EventSource` does not reconnect a non-`200`: a `200` with one `rejected`
  event, status `401` with no valid token and `403` to a token without `editor`, and the stream
  ends, never registered. The check runs only when a stream opens, so a stream already open stays
  open after its token expires.
- **Two surfaces are not a person's, and sit outside the API blueprint**, where the OIDC gate never
  sees them: the store's sync routes, behind the store's bearer ([`sync.md`](sync.md)), and the
  tools' routes, the worker's `/tools/pilot-work/` and the brain's `/tools/pilot-store/`, behind the
  bearer Pilot minted for the session that calls ([`mcp.md`](mcp.md)), which no site reaches.

On a `rejected` event the UI stops reconnecting and asks `/api/auth/self`, which refreshes an
expired token: on `200` it opens a new stream, on `401` it goes to the login page, and on anything
else it shows a "connection lost" message. The shared worker and the plain `EventSource` that a
browser without `SharedWorker` and the Vite dev server use both recover this way, and neither
retries in a loop.

## The person on the record

A person is a `users` row of kind `person` ([`record.md`](record.md)), keyed by the token's
subject, made when they choose their handle. The endpoints are `backend/app/api/people.py`, on
`PeopleService` (`backend/app/services/people_service.py`).

- **`GET /api/people/self`** answers the signed-in person, `{handle, handle_prefill, name,
  initials, avatar_slot}`, and is the sign-in on the record too, since the template's OIDC callback
  has no hook for the app: for a person with a row it refreshes the email (the token's, or none),
  the last seen time, and the name, which a token without one leaves as it was. Before the row,
  `handle` and `avatar_slot` are null, and `handle_prefill` is what the handle step offers: the
  name's first word, case-folded, folded to ASCII and stripped of everything but lower-case
  letters, digits and hyphens ("Émile" gives `emile`), or empty. `name` and `initials` are null
  for a token with no name or a blank one. Once the handle is chosen, `handle_prefill` is null.
- **`POST /api/people/self/handle`** `{handle}` makes the row and answers `201` with the same body.
  A handle is lower-case letters, digits and hyphens (else `400`), not `agent`, which is Pilot's,
  not another person's, and chosen once: each of those is a `409`. The refusal's reason is the
  error envelope's `error`, worded to be shown. The row takes the token's name, or the handle when
  the token carries none (D014), and the lowest free avatar slot, counting from 1. Choosers take
  turns: the choice locks `users` before its checks, so a second chooser sees what the first
  committed.
- **Initials** are the first two capitals of the name; a name with fewer gives the first letters of
  its first two words, upper-cased ("jan-piet" gives `JP`), else its first character.
- **A write in a person's name** needs the row: an endpoint that writes one refuses a caller
  without a handle with `409`, "Cannot … because you have not chosen your handle yet".

**The handle step** (`frontend/src/components/people/handle-step.tsx`). Until the person has a
handle, no screen opens: the step stands under the top bar, whose menu holds the name, the theme and
Sign out, so a person can leave before choosing (D013). It reads "Choose your handle", "The short
name that stands for you in Pilot's files." and "Lower-case letters, digits and hyphens. Once
chosen, it cannot be changed.", over a one-line field prefilled from `handle_prefill`, where Enter
chooses, and the Choose button. A refusal shows as a toast and keeps the typed text. Once the
handle is chosen, the address the person asked for opens.

**The profile page**, `/profile` (`frontend/src/routes/_shell/profile.tsx`), opened from Profile in
the same menu, shows the person's avatar, their name and their handle, and nothing to edit: a
handle never changes.

## Without sign-in

With `OIDC_ENABLED` false, the default and the dev stack's setting, a request with no test session
is not gated, `/api/auth/self` answers a fixed local user, and the event stream is opened for that
user. That user, `Local Admin` with the subject `local-user`, meets the handle step as anyone does;
the dev seed does not hold it, so recreating the database takes its handle with it.

In testing mode a test session (`POST /api/testing/auth/session`) is checked like a token, by the
API and the event stream alike: it passes only if its roles include `editor`. The frontend suite's
`auth.createSession()` gives a session no roles unless told, so a test that signs in passes
`roles: ['editor']`. `POST /api/testing/sse/force-callback-error?status=401` (or `403`) makes the
next stream's connect callback refuse it, once.

A test session writes no person row: a spec gets a person with a handle the way production does,
through `POST /api/people/self/handle` (the suite's `people.signIn()`, [`ui.md`](ui.md)), and
another person through `POST /api/testing/people` ([`projects.md`](projects.md)).
