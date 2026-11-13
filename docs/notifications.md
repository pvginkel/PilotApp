# Notifications

Pilot notifies a person through web push, on each browser where they turned notifications on: the
installed app on a phone, a desktop browser. Two kinds of notification stand there: one per project
they are a member of, while something in it waits on them, and one per person, the alarms, while
the controller is unreachable or the week's usage halt holds all work. A push alerts only for what
the person has not been shown, and nothing is pushed to them while they are online, in a page of
Pilot on any device. Nothing is dismissed by push: the app closes a notification on the device
where it opens what the notification is about. A push that fails is logged and counted, and never
retried.

## Web push

`WebPushService` (`backend/app/services/web_push.py`, the container's `web_push_service`) pushes to
a person's browsers, each through its own push service, under the stage's VAPID key,
`VAPID_PRIVATE_KEY`, a P-256 private key in unencrypted PEM, which the backend refuses to start
without in production. Where no key is set, nothing is pushed.

`push(user_id, push, db)` pushes to every subscription of the person's, one after the other, and
answers whether any browser's push service took it: false with no subscription, or no key. It runs
in the transaction of the caller's turn (below): the read of the subscriptions is rolled back to a
savepoint before the push services' calls, so that across them no row or table is locked, and the
delete of a subscription answered gone is in that transaction, committed with the turn.

- **The payload**, the service worker's input, is UTF-8 JSON, `{"title", "body", "tag", "url",
  "renotify"}`, plain text, `renotify` true for a push that alerts. The body is cut, ending in "…",
  so that the whole fits one record of 4096 octets, 3993 octets of payload. It is encrypted to the
  browser as RFC 8291 has it, `aes128gcm`, with a fresh salt and key for each push.
- **The request** carries `Authorization: vapid t=<claim>, k=<public key>` (RFC 8292): the claim
  signed ES256 for the push service's origin, its contact the stage's `BASEURL`, expiring twelve
  hours on. `TTL` is a day, and `Urgency` is `high` for an alert and `normal` for an update. The
  call connects within 10 s and waits 30 s for the answer; redirects are not followed.
- **The answer**: a 2xx is `sent`. A `404` or `410` is `gone`, and the subscription is deleted
  while it is still the person's. Any other 4xx is `refused`. A 5xx, a timeout or no connection is
  `unanswered`. Each is counted; a gone is logged at info, and a refused or unanswered push at
  warning, each with the push service's host.

No push is retried: the next change pushes anew. Each subscription names its own push service, so
no readiness check stands for them; the counter shows them failing.

## A browser's subscription

A browser's subscription is a row of `push_subscriptions` ([`record.md`](record.md)), its
`endpoint`, the push service's URL for that browser, unique, and the browser's keys as it gives
them. The endpoints (`backend/app/api/web_push.py`, `backend/app/api/people.py`,
`PushSubscriptionService`):

- **`GET /api/web-push`** answers `{"public_key"}`, the stage's public key in base64url, which a
  browser subscribes with, or `null` where the deployment pushes nothing.
- **`POST /api/people/self/push-subscriptions`**, its body `PushSubscription.toJSON()`, writes the
  browser's subscription for the caller and answers `204`; its `expirationTime` is not read. An
  endpoint that is no absolute http(s) URL, or keys that are not a P-256 public key and a 16-octet
  secret in base64url, are a `400`. An endpoint another person holds becomes the caller's, with
  these keys, as if turned on now.
- **`DELETE /api/people/self/push-subscriptions?endpoint=<url>`** deletes the caller's
  subscription of the endpoint and answers `204`; another person's of it stays.

Both writes refuse a caller with no handle with `409` ([`sign-in.md`](sign-in.md)).

**This browser's notifications** (`useDeviceNotifications`,
`frontend/src/hooks/use-device-notifications.ts`) read the browser alone: they are on while the
browser holds a subscription (`pushManager.getSubscription()`) and the browser's storage says it
was written for this person's handle (`subscribedFor`, `frontend/src/lib/browser-state.ts`). A
person who signs in where another's session ended without a sign-out reads them off, and turning
them on makes the endpoint theirs. Turning them on asks the browser's permission, from that tap,
where the person has not answered it, subscribes the browser with the stage's key and writes the
subscription; with the permission refused, nothing is subscribed. Turning them off deletes the
subscription, then unsubscribes the browser, and leaves the permission granted, so that on again
asks nothing. A refused request is the query client's toast. A browser without a service worker,
the Push API or notifications, as outside a secure context, and a stage with no key, cannot turn
them on.

**On the profile page** (`frontend/src/components/people/profile-notifications.tsx`), under the
handle:

- *Notify me on this device*, a switch, turns this browser's notifications on and off. It is
  disabled while the browser cannot turn them on, while it reads them and while a turn is under
  way. Its note says "This deployment of Pilot sends no notifications.", "This browser cannot show
  Pilot's notifications." or, with the permission refused, "This browser blocks Pilot's
  notifications: its site settings for Pilot unblock them."; else what they are. With the
  permission refused it stays enabled, since a tap reads the permission afresh, so that an unblock
  in the site settings takes at the next tap.
- *Send me alarms*, a switch, the person's on every browser of theirs and on by default, whatever
  this browser's notifications. Its note names what alarms: KubeCoder out of reach for five
  minutes, or the week's usage limit halting the work. **`PUT /api/people/self/alarms`**
  `{alarms}` turns it and answers `200` with the person ([`sign-in.md`](sign-in.md)); it writes the
  switch alone. Off pushes the person no alarm; on alarms on the next condition that comes to hold.

Each is the shared `.switch` ([`ui.md`](ui.md)), as is the page's third, *Join projects started on
my behalf*, under "Projects" ([`projects.md`](projects.md)).

**The offer** (`frontend/src/components/shell/notifications-offer.tsx`) is a gold bar of its own
across the full width of the page's top, on every browser (D154): over the top bar off a phone,
and over the conditions' gold bar on one. "Turn on notifications on this device?", with Turn on,
which asks the browser's permission from its tap, and Not now. It shows for a person with a handle
where the stage has a key, the browser can turn notifications on, its permission is not refused,
its notifications are not this person's, and it has not been offered before. Turn on and Not now
each write `notificationsOffered` to the browser's storage, and so does the profile page's switch
once it has turned them on, and the offer never shows in that browser again.

**Signing out.** A person's Sign out, in the profile menu, deletes this browser's subscription,
unsubscribes it, and then signs out, so that a signed-out browser is pushed nothing. A refused
delete is the query client's toast and leaves them signed in. At the handle step, with no row and
so no subscription, Sign out signs out at once.

## The service worker

`frontend/public/sw.js` shows each push under its `tag`, replacing what stands there,
`showNotification(title, {body, tag, renotify, silent: !renotify, icon: '/icon-192.png', data:
{url}})`: an alert renotifies, and an update is silent, so that it keeps quiet also where nothing
stands under its tag any more, swiped away or closed by the app. A tap closes the notification,
focuses the window last focused and loads the push's `url` in it, or, with no window open, opens
the app at the `url`. The window is focused first, while the tap allows it.

## The app in front of the person

**Online.** A page of Pilot its person is active in beats, and the person is online while a page of
theirs counts (`AppPageService`, `backend/app/services/app_page_service.py`; `app_pages` in
[`record.md`](record.md)). The shell's `useAppPage` (`frontend/src/hooks/use-app-page.ts`) beats
for a person with a handle while the page is visible and has had a key, a pointer, a touch or a
wheel in the last two minutes (`keydown`, `pointerdown`, `pointermove`, `touchstart`, `wheel`, heard
in the capture phase; not `scroll`, which the app's own scrolling fires too): at once as the page
goes active, every thirty seconds after, and at once when the project the route shows changes. The
project it beats with is the route's, by the id its address resolves to, whichever of the
project's addresses the route is at ([`projects.md`](projects.md)).
Hidden, or two minutes without input, it sends its away by beacon, at once, or once a beat in
flight is answered, so that it gets out as the page hides. A beat the network lost is a beat
missed, and the next goes at its time.

- **`POST /api/people/self/app-pages`** `{"project_id": <uuid> | null}` is a page's first beat: it
  writes the page, showing the project or none, and answers `201` `{"id"}`.
- **`PUT /api/people/self/app-pages/<id>`**, the same body, is each beat after it and answers
  `204`. A page that has ended, by its away or its beat's ninety seconds, or another person's, is
  `404`, and the page then beats afresh with the first beat's POST.
- **`POST /api/people/self/app-pages/<id>/away`** deletes the page and answers `204`; its body is
  not read, so that `navigator.sendBeacon` carries it. A page that has ended is nothing to delete.

An unknown project on either beat is `404`, and all three refuse a caller with no handle with
`409`. A page whose beat is ninety seconds old (`EXPIRY_SECONDS`) counts for nothing, so that a
phone locked, switched off or out of reach goes offline: it is deleted by the timer
`app-page-expiry`, on the scheduler's tick, or by the next beat or away of its person, whichever
comes first. Between its ninety seconds and its deletion it counts for nothing already, so that a
person with no other page reads offline before their going offline is told.

The service's listeners hear two things, each once, after the commit that made it so, on the
committing thread, a request's or the scheduler's: `ShowingTurned(user_id, project_id, shown)`, a
project coming to be shown by a page of the person, none of theirs having shown it, or the last of
theirs that showed it deleted or moved off it; and `WentOffline(user_id)`, their last page deleted.
Coming online is told nothing. Every write of a person's pages holds their User row, reads their
pages under it, deletes those ninety seconds old and compares the pages it read with those it
leaves, so that a roll's two processes, a beat racing another page's away, or two sweeps take turns
there: a person goes offline once, and only when no page of theirs is left. The sweep skips a person
another transaction holds.

**Closing on the device.** While the page is visible, `useAppPage` closes, on its own device, the
notifications of what it shows, through the service worker's `getNotifications({tag})`: a project's,
under the project's id, as a page of the project comes to show it, its timeline, one of its
documents or one of its tabs, every route under the project's address (D155), once the address is
resolved to the project, and the alarms', under
`alarms`, wherever a page of Pilot loads; each again as the page comes back to the foreground. It
does so for anyone, a person at the handle step included. Pilot's own address lands on the project
last open ([`projects.md`](projects.md)), so the alarms' tap, whose `url` is the app, closes that
project's notification too.

## A project's notification

What each member should see is derived from the record by the server, never written by the brain
(`StandingNotificationService`, `backend/app/services/standing_notification_service.py`): a
notification while an item waits on them, the project is unarchived, a draft or a finished one
included, and their membership is open; else none. Nothing else of the project shows: no status
line, no running work item, no pause, no plan task.

- **What waits on the member** is the badge's set, `waiting()` in
  `backend/app/services/timeline_service.py` ([`projects.md`](projects.md)), but for an item `for`
  another person, which is neither named nor counted. An item `for` nobody waits on every member.
- **The `tag`** is the project's id.
- **The title** is the project's name, "New project" for a draft its draft has not named yet, cut
  to 250 characters, ending in "…" (D091).
- **The body** names the latest placed of the items that wait on the member, by its title, or by
  its kind's name, such as "Decision", when it has none, followed by ", +<n>" counting the others
  when more wait (D145): `Which tent?, +2`.
- **The `url`** is absolute, on the stage's `BASEURL` (D091), on the project's address, its slug
  or a draft's `draft-<number>` ([`projects.md`](projects.md)): `<BASEURL>/projects/<address>/items/<item
  id>`, the item's permalink, when exactly one item waits on the member, and the project's
  timeline, `<BASEURL>/projects/<address>`, otherwise ([`timeline.md`](timeline.md)). The
  reconcile compares the items, not the link, so that Create sends nothing again for the address
  it moves, and a notification shown before it keeps the `draft-<number>`, which still opens the
  project. On a phone the
  permalink opens the item alone, over the project's Timeline, which Back shows.

## The reconcile

`NotificationReconcileService` (`backend/app/services/notification_reconcile_service.py`) pushes
each member what waits on them that they have not been shown. What a member was shown is their
membership's Item Sightings (`item_sightings`, [`record.md`](record.md)). A member's compare, in
their turn:

- the project archived, their membership closed, or nothing waiting on them: their sightings are
  deleted and nothing is pushed, so that Archive and Leave forget what they were shown, and the last
  item answered pushes nothing;
- a page of theirs shows the project: every item that waits on them is shown, a sighting written for
  each and the others deleted, and nothing is pushed (D155);
- online, with no page of theirs on the project: nothing is pushed, and their sightings stand;
- offline with a browser subscribed: an item that waits with no sighting alerts; else a sighting of
  an item that no longer waits updates the notification silently, another item still waiting; else
  nothing is pushed. Offline with no browser, nothing is pushed and their sightings stand.

A push some browser of theirs took shows them every item it named or counted: a sighting is written
for each, and the others are deleted. One that none took writes no sighting, so that the member's
next reconcile pushes anew. A closed membership's sightings are deleted at every compare, so that a
rejoin alerts anew. A change of the plan alone, or a retitle of an item, pushes nothing: what waits
is unchanged.

A project's reconcile is the loop `notification:<project id>` of the job `notification`, for each
person with a membership of the project open or with sightings. It runs:

- once a commit that emits `ProjectChanged` for the project is in ([`engine.md`](engine.md)): its
  items, a work item's state, a join, a leave and its transitions, Archive and Bring back among
  them. `WorkMoved` alone starts none: no notification shows a work item's line or its steps, and a
  move of its state carries `ProjectChanged`;
- at STARTUP, for every project with an open membership of it unarchived, or with a sighting, so
  that a change no reconcile reached, the server stopping in between, is found then.

A person's reconcile is the loop `notification-person:<person id>` of the job
`notification-person`, the person in each project with a membership of theirs open or with
sightings, at each `ShowingTurned` and `WentOffline` of theirs: so a page that comes to show a
project counts its items shown, and the pushes held while they were online go out as they go
offline.

**The spacing.** A member's pushes in one project go out at most once in two seconds
(`NOTIFICATION_SPACING_SECONDS`), from their last push tried there, taken or not, the latest
`notification_sent_at` of their memberships of the project, a closed one's included, so that the
window holds across a roll's two processes. The push writes it on the open membership. A push due
inside the window is compared again at its end, the run waiting with no turn and no database
connection held: what goes out then is the latest state, so a burst of commits comes to one push,
and a change undone inside the window to none. A run told to stop inside the window pushes nothing
more, and logs each member it held as left to their next reconcile.

**A member's turn.** A member's compare and push in one project take turns under a two-key advisory
lock, `(224, <a 32-bit key drawn from the person's and the project's ids>)` (`advisory_turn`,
`backend/app/services/advisory_turn.py`), so that two processes, a roll's two pods included, push
them once. A turn is one transaction, on a database session of its own, and the lock is that
transaction's (`pg_advisory_xact_lock`): the stages reach PostgreSQL through a pooler in transaction
mode, which hands each transaction whichever server connection is free, so a lock held past its
transaction would hold nothing there. The compare, the push's own read and delete, and the write of
what the push came to run in it, so that a turn holds one connection and never waits on the pool
for a second. Before the push services' calls, what the compare and the push's read did is rolled
back to a savepoint (`let_go`), the write doing again what the compare wrote: across the calls the
transaction holds its lock alone, no row or table locked, and no request or commit waits on them.

## The alarms

`AlarmService` (`backend/app/services/alarm_service.py`) pushes each person the conditions that
alarm, begun since they were last shown them, while they are offline and their alarms switch is
on. Pilot has none. The conditions that hold are the conditions service's, which the gold bar shows
([`controller.md`](controller.md), [`ui.md`](ui.md)), taken by their codes (D089). Two of them
alarm: the outage, due once it has held `OUTAGE_ALARM_AFTER_SECONDS` from its `since`, so that a
shorter blip buzzes nobody, and the week's usage halt ([`usage.md`](usage.md)), due at once. The
five-hour halt and the store's update ([`store-update.md`](store-update.md)) show on the gold bar
alone. The outage is each process's own, and off at a start.

- **The `tag`** is `alarms` (`ALARM_TAG`), every person's, the one the app closes wherever a page
  of Pilot loads.
- **The title** is "Pilot", and **the `url`** the app, `<BASEURL>/`. Every alarm alerts.
- **The body** names the conditions due by their titles, "The controller has been unreachable"
  and "The week's usage halt", the latest begun first, the outage first of two begun at once: the
  first alone, or followed by ", +<n>" counting the others, so `The week's usage halt, +1`.

When a person was last shown the conditions is their `alarm_seen_at`, which only moves forward. An
alarm push moves it to when the latest begun of the conditions it named began, whether a browser
took the push or not, so that none of them is pushed again; a condition begun after that, while the
push was in flight too, alerts in a push of its own. Their going offline moves it to that moment,
every condition that held having shown on the gold bar while they were online, so that an outage
begun before it does not alarm when it comes due after. For a page's expiry that moment is the
sweep's. An outage that began before a condition an alarm named, and came due after that alarm,
does not alarm either: it began before their `alarm_seen_at`. A condition's end pushes nothing.

The reconcile is the one loop, `alarm`, of the job `alarm`: each person with the switch on and a
browser subscribed, in their turn, pushed when a condition due began after their `alarm_seen_at`
and no page of theirs counts. With nothing due it reads nobody. It runs:

- at each turn of a condition: the conditions service's `tell()` calls its listeners first, the
  alarms among them;
- at STARTUP, once;
- at the timer `alarm-due`, when the conditions due, with when each began, differ from those the
  last reconcile read, as they do once the outage has held its time.

A person's going offline is written by a loop `alarm-seen:<n>` of the job `alarm-seen`, its moment
taken on the thread that committed it. The switch asks for no reconcile: it is turned on a page of
Pilot, whose going offline counts what holds then as shown. A person's alarm turns take turns as a
member's do, under `(238, <a key drawn from the person's id>)`, the read, the push and the write in
the turn's one transaction, the read let go before the push, and take no spacing.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `VAPID_PRIVATE_KEY` | empty | the stage's VAPID key, P-256 in unencrypted PEM, which signs every push and whose public key browsers subscribe with; empty pushes nothing, and a backend with `FLASK_ENV=production`, as both deployed stages run, refuses to start so |
| `OUTAGE_ALARM_AFTER_SECONDS` | 300 | how long the controller stays unreachable before its alarm is due; 0 or more |

With no key, nothing is pushed: the jobs `notification`, `notification-person`, `alarm` and
`alarm-seen` and the timer `alarm-due` are not registered, `GET /api/web-push` answers `null`, and
no browser can turn notifications on. A page's beat and the switches still move the record. The
two seconds between a member's pushes and a page's ninety seconds are constants,
`NOTIFICATION_SPACING_SECONDS` and `EXPIRY_SECONDS`. Each deployed stage's key is in
[`deployment.md`](deployment.md); the dev stack runs with none.

The metric, on the backend's `/metrics`: `pilot_web_push_sends_total{outcome}`, each push to a
browser's push service, `sent`, `gone`, `refused` or `unanswered`.

## Testing it

No suite reaches a real push service. `FakePushService`
(`backend/app/services/fake_push_service.py`) is a WSGI app the real `WebPushService` reaches by a
subscription's endpoint. It plays a browser and its push service at once: it issues subscriptions
whose endpoints are its own, keeps each browser's private key and secret, and decrypts what each
push carries, so that a test reads every push a subscription took and whether it alerted. It takes
a push as a push service does: signed with the key the browser subscribed with, by a claim for the
fake's origin that has a contact and expires within 24 hours, `aes128gcm`, with a `TTL`, an
`Urgency` among RFC 8030's, and a body of one record. It answers `201`; a refusal `400`, `401`,
`403` or `413`, as the push services do; and an endpoint it never issued `404`. Where it is simpler
than a push service and a browser: a push that does not decrypt, or whose payload is not the push's
JSON, is refused with `400`, where a push service, which reads no payload, takes it and the browser
drops it; a push is kept at once, as if every browser were reachable; a push's `Topic` is not read;
and nothing expires.

A test drives it through its verbs: `subscribe(application_server_key)`, which answers a
subscription in `PushSubscription.toJSON()`'s shape, its endpoint the fake's; `pushes(endpoint)`;
`fail(endpoint, failure)`, which has the subscription answer every push `gone` (`410`), `refused`
(`429`), `error` (`500`) or `unanswered`, its connection closed with nothing sent, and keep none,
`null` taking them again; and `reset()`.

- **Under pytest**, the fixture `fake_push_service` serves it on a free port
  (`ServedFakePushService`, `backend/tests/support/fake_push_service.py`), whose `browser(public_key)`
  subscribes a browser there; `vapid_key` mints a stage's key for the test, as no key is committed,
  and `web_push_service` makes the real service under it the container's (`web_push_of`). The
  served fake's `on_push` runs once, after it took the next push and before it answers it, a push
  in flight, and `hold(pushes)` holds each push in flight until that many are at once.
- **For Playwright**, it is mounted at `/api/testing/push-service`
  (`backend/app/api/testing_push_service.py`), which answers only with `FLASK_ENV=testing` on a
  `STAGE` other than `prd`: the subscriptions it issues have their endpoints under the mount, and
  its verbs are `POST …/fake/<verb>` with their keyword arguments as the JSON body. `unanswered`
  closes the connection only under werkzeug's server; under a Playwright backend's waitress the
  push is answered `500`, with a `KeyError` in the backend's log, and counted `unanswered` all the
  same. `loadAppBackendEnv()` gives each Playwright backend a VAPID key minted at its start. The
  spec fixture `browserPush` (`frontend/tests/support/browser-push.ts`) gives the spec's browser
  its notifications: `install({permission?, answer?})`, before the page loads, replaces the page's
  permission, its prompt and its `PushManager` with ones of its own, the subscription issued by the
  fake and kept in the page's storage, as the suite's headless Chromium subscribes to no push
  service; `subscription()`, `pushes()` and `prompts()` read what it holds. A spec that does not
  install it never sees the offer, the headless shell's permission being denied. The fixture
  `device` (`frontend/tests/support/device.ts`) hands a push to the page's service worker once the
  page's closing of its notifications is done, since headless Chromium drops a notification
  `getNotifications()` reads while it is being displayed: the ui state `shell.closing` of its
  current load ready (`useAppPage` reports it `loading` as each closing starts, with the tags it
  reads, and `ready` once none is in flight, each event carrying the load's
  `performance.timeOrigin`), and, on a visible page at a project's address, a closing that read the
  project's tag started, the page closing the project's only once it has resolved its address,
  which can come after the alarms' are closed. It waits until the push is displayed, reads the
  notifications standing there, and sets the page's visibility
  (`hide()`, `foreground()`); a push shows only in a file under `test.use({ channel: 'chromium',
  permissions: ['notifications'] })`, Chromium's full build. The record's testing read
  `GET /api/testing/projects/<id>/sightings?handle=<handle>` ([`projects.md`](projects.md)) says
  what a member was shown, which the reconcile writes off the request that showed it.
