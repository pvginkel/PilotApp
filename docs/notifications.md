# Notifications

Pilot reaches a person's phone through the notification bridge, the estate's service
(`pvginkel/Notifications`), under the bearer token of that person's own registration, which they
paste on their profile. Two kinds of notification stand there: one per project they are a member
of, which reads the project's state and rises when something comes to wait on them, and one per
app-wide condition that holds all work, the alarms. Each is a standing notification: the bridge
shows one per sequence id and updates it in place, and Pilot keeps in the record what it last sent,
so that the phone ends on what the record says.

No bridge call runs on a request (D093). The bridge can take about a minute to answer, so every
submit and dismiss runs on a loop of the server's jobs ([`jobs.md`](jobs.md)), and a token's save
waits on its one-shot as a task.

## The bridge

`NotificationBridgeClient` (`backend/app/services/notification_bridge_client.py`, the container's
`notification_bridge_client`) makes three calls, each under one person's token, sent as given in
the `Authorization` header:

- `submit(token, sequence_id, *, message, title, priority, url)`, `POST /v1/submit`, shows the
  sequence id's notification, or updates the one shown: in place and silently at the same or a
  lower priority, shown again and alerting at a higher one. The bridge keeps no `url`, so every
  submit carries it.
- `dismiss(token, sequence_id)`, `POST /v1/dismiss`, takes it down.
- `send_one_shot(token, *, message, …)` is a submit with no sequence id, which nothing updates or
  dismisses.

A call went out, was refused, or got no answer, and only one that went out returns. Any 4xx is
`NotificationBridgeRefused`, with the `status` and, as its `reason`, the bridge's own `error`, or
the status's phrase where the answer has none. A connection error, a timeout, a 5xx, or a status or
body the bridge never answers with is `NotificationBridgeUnanswered`. Redirects are not followed.
Both are a `NotificationBridgeFailure`, and the caller logs it. A `200` says that the body was
valid and that every channel of the registration was tried, not that anything was delivered: a
channel's error in it is logged as a warning. The client connects within 10 s and waits 120 s for
the answer. Its readiness check, `notification_bridge`, is the bridge's `GET /healthz` within 2 s
and is not critical: Pilot serves its record without the bridge.

## The token

Each person pastes the token of their own bridge registration (D088). Pilot rotates none: a person
whose registration's token changes pastes the new one. `users.notification_token` holds it sealed
with Fernet, under the key the template's `app/utils/auth.py` derives from `SECRET_KEY` for the
OIDC state (`NotificationTokenCipher`, `backend/app/services/notification_token_cipher.py`). It is
opened only to send through it, and never answered back. A ciphertext the key does not open raises
an error, and is never read as no token ([`deployment.md`](deployment.md) says what a new key
costs).

The endpoints are on `/api/people/self` (`backend/app/api/people.py`,
`NotificationSettingsService` in `backend/app/services/notification_settings_service.py`), and
each refuses a caller with no handle with `409` ([`sign-in.md`](sign-in.md)):

- **`PUT /notification-token`** `{token}` saves a token, a first one or another in its place, and
  answers `202` with the save's task (`{task_id, status}`). The token must be visible ASCII, with no
  space or line break (`400`, checked before the bridge, and the message quotes no token), and with
  no bridge configured the answer is `409`. The task, `SaveTokenTask`, sends the one-shot "Pilot
  will notify you here" through the token, at `default`. A token the bridge refuses or does not
  answer fails the task with the bridge's reason, such as "Cannot send a one-shot notification
  through the bridge because external service failed: the bridge refused it with 401: unknown
  bearer token", and nothing is stored. Once the bridge took it, the task locks the person's row and
  stores the token, sealed. It fails instead when their token was cleared or set to another since
  the save began, so a clear or another save made meanwhile stands. Once that commits, their
  projects' notifications and their alarms are submitted through it. A cancelled task stores
  nothing. The task's result is the person, as the self read answers, and its events go to the
  caller's connections alone.
- **A replace** is a rotation of the same registration (D094): it sends nothing through the token
  it replaces, and the reconciles submit everything again through the new one. A token pasted over
  another registration's leaves what that registration's phone shows until it is swiped away.
- **`DELETE /notification-token`** clears the token at once and answers `200` with the person.
  From the commit on, every notification and alarm of theirs that stands, an owed one included,
  reads as dismissed, with nothing owed. Once it commits, each is dismissed through the token just
  cleared, tried once, off the request (D093). What the bridge does not take is logged, counted, and
  stays on the phone until swiped away. A person with no token has nothing to clear, and one whose
  token the app's key does not open is answered `409`.
- **`PUT /alarms`** `{alarms}` turns the alarms switch and answers `200` with the person. Once it
  commits, off dismisses their standing alarms and on submits those due.

The self read carries `notification_token_set`, whether a token is set, and `alarms`, the switch,
which is on by default.

**On the profile page** (`frontend/src/components/people/profile-notifications.tsx`), under the
handle:

- *Notification token* says whether a token is set, over a password field that shows nothing of a
  saved one, with Save and Clear beside it. Save is disabled while the field is blank, and Clear
  while no token is set. Save, or Enter, trims the text, saves it and follows the task with
  `useSSETask`. While the task runs, the field, Save and Clear are disabled and the task's progress
  text shows. A failed task's error shows under the field, which typing clears. A refused request,
  a `400` or a `409`, is a toast.
- *Alarms* is a switch, "Send me alarms", which always shows and is disabled while no token is set.
  Its `.switch` style is a shared piece ([`ui.md`](ui.md)).

## A project's notification

What each member should see is derived from the record by the server, never written by the brain
(`StandingNotificationService`, `backend/app/services/standing_notification_service.py`). A member
sees one while the project is unarchived, a draft or a finished one included, their membership is
open and they hold a token. Otherwise they see none, and what stands is dismissed.

- **The sequence id** is the project's id.
- **The priority** is `high` while an urgent item waits on the member, `default` while any item
  does, and `min` otherwise. The items that wait are the badge's set, `waiting()` in
  `backend/app/services/timeline_service.py` ([`projects.md`](projects.md)). An item `for` one
  person waits on that person alone, and counts in the others' message.
- **The title** is the project's name, "New project" for a draft its draft has not named yet, cut
  to 250 characters (D091).
- **The message** is the project's status line, then what runs and what waits, joined by ` · `
  (D091):
  - the status line: "Draft" or "Finished", else the step reading: the first step in progress by
    name, with ", …" after it when more are, or "Not started", "N of M done" or "All steps done";
  - "Paused" while the project is paused, in the place of what runs, which is otherwise
    "Running: <title>" for one running work item, "Running" when it has no title, and "N running"
    for more;
  - for the items waiting on the member, "<Kind> waiting: <title>" for one, the kind's name, such
    as "Decision waiting: Which tent?", or "<Kind> waiting" when the item has no title, and
    "N waiting" for more;
  - "N waiting on <handle>" for each other person items wait on, whether or not they are still a
    member;
  - for the open waits, "Waiting for: <title>" or "<Kind> open" for one, and "N waits open" for
    more.

  So a project might read `Not started · Decision waiting: Which tent?`. The texts taken from the
  record are escaped for Markdown with a backslash. The message is cut to 4096 characters, ending
  in "…", and never inside an escape.
- **The `url`** is absolute, on the stage's `BASEURL` (D091): `<BASEURL>/projects/<id>/items/<item
  id>`, the item's permalink, when exactly one item waits on the member, and the project's
  timeline, `<BASEURL>/projects/<id>`, otherwise ([`timeline.md`](timeline.md)).

## The reconcile

`NotificationReconcileService` (`backend/app/services/notification_reconcile_service.py`) keeps
each member's notification as the record says it should stand. A project's reconcile is the loop
`notification:<project id>` of the job `notification`. For each person with a membership of the
project that is open, stands or is owed, it compares what they should see with what their
membership last sent, and submits or dismisses when the two differ or a send is owed. It runs:

- once a commit that emits `ProjectChanged` for the project is in ([`engine.md`](engine.md)): its
  items, a work item's state, a join, a leave and its transitions, Archive and Bring back among
  them. `WorkMoved` alone starts none: no notification shows a work item's line, and a move of its
  state carries `ProjectChanged`;
- at the timer `notification-retry`, for each project with an owed membership whose last try is
  60 s old or more;
- at STARTUP, for every project with a membership whose notification stands, is owed, or should
  stand, so that a change no reconcile reached, the server stopping in between, is found then;
- once a token's save commits, for each of the person's projects.

What a membership last sent is its `notification_priority_code`, `notification_text` and
`notification_url`, all three set or none, with `notification_sent_at`. The compare reads the
three. The title is in no column, so a rename alone sends nothing until something the compare
reads changes too. A dismiss leaves the three none and `notification_sent_at` its time. Of one
person in one project the phone shows one notification, whichever of their memberships sent it,
since a rejoin is a new membership; the latest of them takes what goes out.

**A member's turn.** One person's sends in one project take turns under a two-key
transaction-level advisory lock, `(224, <a 32-bit key drawn from the person's and the project's
ids>)` (`advisory_turn`, `backend/app/services/advisory_turn.py`). It is held on a database session
of its own, from before the record is read until what went out is written, so that the phone ends
on the latest state with two processes running, a roll's two pods included. A send is three steps
under it: a read transaction; the bridge's call, outside any transaction, so that no row is locked
and no request or commit waits on it; and a write transaction, which reads the person's token under
their row's lock (`FOR SHARE`) and then locks the memberships' rows. The write is dropped,
`superseded`, when the person's sealed token changed since the read: the save or clear that changed
it says what the record holds. A submit that a clear overtook, and that the bridge did not refuse,
is followed by a dismiss of its own through the token in hand.

**Owed.** A send the bridge refuses or does not answer sets `notification_owed_at` to the time of
the try. The project's next reconcile sends whatever it compares again, and the retry timer's once
60 s have passed. The log warns when a membership turns owed and says when its owed send went out;
the tries between log at debug.

**A token's save and clear.** A save's transaction reads what each of the person's open memberships
of an unarchived project last sent as nothing, so that the reconcile submits its current state
through the new token. A clear's transaction reads every standing or owed membership of theirs as
dismissed, with nothing owed, and a loop `notification-clear:<n>` of the job `notification-clear`
dismisses each project's notification through the token cleared, once, in the member's turn,
unless the person holds that same token again, whose save submits afresh.

## The alarms

`AlarmService` (`backend/app/services/alarm_service.py`) keeps a standing notification per person
and app-wide condition, for every person who holds a token and whose alarms switch is on. Pilot
holds none. The conditions that hold are the conditions service's, which the gold bar shows
([`controller.md`](controller.md), [`ui.md`](ui.md)), taken by their codes, so that each condition
it tells of has its alarm (D089). It tells of the outage alone, so the halts' alarms, built with the
rest, stand only once it tells of a halt.

| Condition | Title | Message | Priority |
|---|---|---|---|
| `outage` | The controller has been unreachable | Nothing starts until it answers. | `high` |
| `week_halt` | The week's usage halt | Work items are halted until a reading puts the week's share back under its limit, or someone overrules the halt. | `high` |
| `five_hour_halt` | The five-hour usage halt | Work items are halted until a reading puts the five-hour window's share back under its limit. | `default` |

An alarm's sequence id is its condition's code, and its `url` is the app, `<BASEURL>/`. A condition
that holds is due at once, and the outage once it has held `OUTAGE_ALARM_AFTER_SECONDS` from its
`since`, so that a shorter blip buzzes nobody. The outage is each process's own, and off at a start.

The reconcile is the one loop, `alarm`, of the job `alarm`. For each person who holds a token with
the switch on and each condition due, and for every alarm standing or owed, it compares whether
the alarm should stand with whether it stands, and submits or dismisses when the two differ or a
send is owed. It runs:

- at each turn of a condition: the conditions service's `tell()` calls its listeners first, the
  alarms among them;
- at STARTUP, so that an outage alarm a stopped process left standing is dismissed;
- at the timer `alarm-retry`, when the alarms due differ from those the last reconcile read, as the
  outage's do once it has held its time, or while an alarm is owed whose last try is 60 s old or
  more. It does not run on every tick while a condition holds, so a process whose outage outlives a
  roll does not submit again what the new process's STARTUP dismissed;
- once a token's save or the switch's turn commits.

An `alarms` row is a person's alarm for one condition: `standing`, `sent_at` and `owed_at`, one per
person and condition. It is born at its first send's write. A first submit that failed leaves it
not standing and owed. Its sends take turns as a member's do, under `(238, <a key drawn from the
person's id and the condition's code>)`, in the same three steps, the write reading the token under
the person's row and dropped when it changed. A token's save reads each of the person's alarms that
should stand as not standing, so that the reconcile submits it through the new token; one whose
condition has ceased stays standing, for its dismiss. A clear reads every alarm of theirs standing
or owed as dismissed, with nothing owed, and a loop `alarm-clear:<n>` of the job `alarm-clear`
dismisses each through the token cleared, once. The switch turned off has the reconcile dismiss the
person's standing alarms, owed while the bridge does not take them; turned on, it submits those
due.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `NOTIFICATION_BRIDGE_URL` | empty | the bridge's base URL, an http(s) address; empty runs the app with no bridge, and a backend with `FLASK_ENV=production`, as both deployed stages run, refuses to start so |
| `OUTAGE_ALARM_AFTER_SECONDS` | 300 | how long the controller stays unreachable before its alarm is due; 0 or more |

With no bridge, nothing is sent: the jobs `notification`, `notification-clear`, `alarm` and
`alarm-clear` and the two retry timers are not registered, and a token's save is refused with
`409`. A clear and the switch still move the record. The 60 s between two tries of an owed send is
a constant, `NOTIFICATION_RETRY_SECONDS`. Each deployed stage's bridge is in
[`deployment.md`](deployment.md); the dev stack runs with none.

The metrics, on the backend's `/metrics`:

- `pilot_notification_bridge_calls_total{call, outcome}`: each call, `submit`, `dismiss` or
  `one_shot`, by how it ended, `sent`, `refused` or `unanswered`.
- `pilot_notification_reconciles_total{outcome}` and `pilot_alarm_reconciles_total{outcome}`: each
  compare, `unchanged`, `sent`, `owed` (the send failed) or `superseded` (the person's token changed
  during the send).
- `pilot_notification_clear_dismisses_total{outcome}` and
  `pilot_alarm_clear_dismisses_total{outcome}`: each dismiss tried once through a token just
  cleared, `sent`, `refused` or `unanswered`.

## Testing it

The bridge has no test mode, so Pilot serves its suites a fake of it, and no suite reaches the real
one (D092). `FakeNotificationBridge` (`backend/app/services/fake_notification_bridge.py`) is a WSGI
app the real client reaches by URL. It knows the registrations a test gives it, each by a name and
its token, refuses any other bearer with `401`, and takes the bridge's bodies with the bridge's
limits, status codes and reasons. A registration shows, per sequence id, what its last submit
carried and whether that submit alerted, and keeps its one-shots and every call it took, in order.
Where it is simpler than the bridge: a registration has one channel, `ntfy`; a channel a test makes
fail answers its error in the `200`, changes nothing shown, and its call is kept in neither the
calls nor the one-shots; a submit alerts when it shows a notification anew or raises its priority,
to `default` or above; nothing is forgotten after 90 days; and it serves no `/metrics`.

A test drives it through its verbs: `add_registration(name, token)`, `rotate_token(name, token)`,
which keeps what shows, `channel_error(name, error=None)`, `unreachable(on=True, answer)`, under
which every call goes unanswered (`none`, `error` or `stall`, a stalled call answered at
`on=False`), and `shown(name)`, `one_shots(name)`, `calls(name)` and `reset()`.

- **Under pytest**, the fixture `fake_notification_bridge` serves it on a free port, and
  `notification_bridge_client` makes the real client on it the container's;
  `bridge_client_of(container, fake)` does the same for `committed_app`
  (`backend/tests/support/fake_notification_bridge.py`). `WatchedFakeNotificationBridge` there runs
  a hook once, after it took the next submit and before it answers it: a submit in flight.
- **For Playwright**, it is mounted at `/api/testing/notification-bridge/<path>`
  (`backend/app/api/testing_notification_bridge.py`), which answers only with `FLASK_ENV=testing`
  on a `STAGE` other than `prd`, its verbs as `POST …/fake/<verb>`, hyphenated, with their keyword
  arguments as the JSON body. `loadAppBackendEnv()` sets each Playwright backend's
  `NOTIFICATION_BRIDGE_URL` to its own mount. The spec fixture `bridge`
  (`frontend/tests/support/notification-bridge.ts`) has `register()`, a fresh registration and
  token, `shown(name)`, `oneShots(name)`, and `hold()` and `answer()`, between which every call
  waits for its answer; it answers again after the spec. A spec that saves a token waits for the
  event stream first (`deploymentSse.ensureConnected()`), since the save's outcome reaches the page
  only as the task's events.
