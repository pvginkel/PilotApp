# Slice testing strategy

How a slice is proven once its phases are merged. This is the doc `.aiworkflowrc` names as
`test_phase.strategy`: the run loop's test phase is "read this and execute it", and nothing else
names it. Read it top to bottom and do what it says.

## What this phase proves, and what it does not

**Pilot has two stages, and a push deploys to dev** ([`deployment.md`](deployment.md)). A push to
`main` runs the Jenkins job `PilotApp/Build-Main` (the suites, the sidecar's tests, the `pilot`,
`pilot-ui` and `pilot-sync` images, tagged `dev-<n>`), which pins `pilot` and `pilot-ui` for both
stages in `pvginkel/PilotDeploy`'s `main`, from which Argo CD rolls the Application `pilot-dev`: the
pod behind `https://pilot-dev.home`, internal, whose sessions and environments are
`kubecoder-dev`'s. Production, `pilot-prd` behind `https://pilot.ginbov.nl`, which the operator and
their wife use, follows PilotDeploy's `prd` branch, which only `PilotApp/Promote-PRD` moves, and only
the operator starts it. So this phase proves the slice **locally first** (the suites, then the dev
stack running here), pushes only what that proved, confirms the rollout on `pilot-dev`, and then
checks `pilot-dev` for what only a deployment can show.

Three things follow:

- **A check may write on dev, and signs in.** `pilot-dev` is the slices' own: no one's work is in
  its database or its fleet. A deployed check signs in through Keycloak's login page as the test
  account, a user of production's realm holding the dev client's `editor` role alone (step 4.6),
  and works the app through the API or the UI as a user does. What it writes is invented, as on the
  dev stack (§2), and stays in dev's database.
- **Nothing checks production.** The test phase never starts `PilotApp/Promote-PRD`, a slice's
  first promotion included: the promotion is the operator's, and the close-out names it as theirs
  ([the operator gate](#the-operator-gate)). Production is only read, to show that the pushes left
  it where it was (step 4.1).
- **The test phase holds the devlock** (D024). `.aiworkflowrc` names a lease, `slices/.devlock.lock`
  in the spec repo, the mount every environment of the project shares. The run loop's driver takes
  it before the test phase starts, keeps it across a findings re-loop, and lets it go once the phase
  is clean and every repo has reached `origin`; it takes it again for the doc phase's push alone.
  While one slice holds it, another slice's test phase waits, so two slices never push, roll and
  check `pilot-dev` at once; the waiting run's log names the holder, from the `dev-holder` note the
  driver writes beside the lease. Nothing in this doc takes or frees it.

What the checks cannot show from here is reported as *not verified*: production after a promotion,
its store included, and anything that needs a part of the fleet no slice has wired into the
deployment yet (YouTrack). The dev stage's store is wired, and a check that needs it works it
(step 4.7). The KubeCoder controller is wired: what Pilot does with it is proven on two
real turns against `kubecoder-dev` (§2, the fleet's live check), and `pilot-dev` shows that its
backend reaches that controller (step 4.3). A check that needs a work item on the dev stage places
one by repository through the record's testing route `POST /api/testing/projects/<id>/work`
([`projects.md`](projects.md)), whose start makes or takes an environment of Pilot's own on
`kubecoder-dev`, which needs the dev cluster up; with it powered off, the dev stage's gold bar reads
the controller unreachable, and what the check would prove is *not verified*.

## 0. Preconditions

The driver has ff-merged every code phase into the base branch of every repo the slice touched
(`state.json`'s `bases`). Confirm each code repo's tree is clean (`git status --short`) before
starting. The spec repo (`../PilotAppSpecs`) is in `bases` too but is not checked: the driver keeps
the slice's run files (`log.txt`, `state.json`, `run.lock`, `phases/`, `setup/`, `sweeps/`)
untracked there for the whole run. A dirty code tree here means an earlier phase left something
behind, and that is a finding, not something to tidy away.

Every verb below runs from the repo root, because `kc project` is cwd-bound.

## 1. The suites

```bash
kc project build
kc project test
kc project lint
```

All three must be green. No gate is known red, so a failure is this slice's. A `kc project` verb
prints its output only on failure, so read its exit code directly and never through a pipe.

`kc project test` prints one `[ OK ]` per suite and no counts. Run the suites once directly and read
the counts, so that a suite that collected nothing is not taken for a green one. The sidecar's
suite prints a line per package: `ok`, or `?` for `cmd/pilot-sync`, which has no tests.

```bash
cexec modern-app sh -c 'cd backend && uv run pytest -q' 2>&1 | tail -1
cexec modern-app sh -c 'cd frontend && pnpm playwright test' 2>&1 | tail -3
cexec go sh -c 'cd sidecar && go test -race ./...'
```

Then the same verbs from the root of every other repo the slice touched, each where it declares
them: `../PilotDeploy`, whose `test` reads `../PilotApp/docs/architecture/architecture.yaml` and so
needs this checkout beside it, and a registry repo the slice changed in `/work/scratch/`
(ArgoCDDeploy, Architecture).

## 2. The local live check

The dev stack is the backend (Flask, debug mode) on 3501, which serves the SSE stream too, and the
Vite dev server on 3500, both in the `modern-app` tool container, against the `pilot` database on
the environment's PostgreSQL sidecar. `scripts/dev.py` starts both; it runs until stopped, so start
it in the background under a timeout:

```bash
timeout 900 scripts/dev.py > /tmp/pilot-dev.log 2>&1 &
```

Wait for the two ports with a socket connect, not with `curl` on the SSE stream: it never ends, and
a `curl` against it burns its whole timeout.

```bash
for i in $(seq 1 60); do
  python3 -c "import socket; [socket.create_connection(('localhost', p), 1).close() for p in (3500, 3501)]" 2>/dev/null && break
  sleep 1
done
```

Then the stack's own checks, each expected to answer `200`:

```bash
curl -s -m 10 http://localhost:3501/health/readyz      # "status": "ok": checks.database "ok"
curl -s -m 10 -o /dev/null -w '%{http_code}\n' http://localhost:3500/
curl -s -m 10 http://localhost:3500/api/auth/self      # through the Vite proxy; the dev stack runs without OIDC, as "Local Admin"
```

The frontend is also published at the `frontend` URL `kc env describe` lists
(`https://frontend.<environment id>.home`); a check that needs the page as a browser on another
machine sees it uses that URL.

Then the slice's own checks: every acceptance criterion in `verification.json` that the suites did
not settle and that the stack can show, exercised against it through the API, or through the UI
with Playwright. The data a check writes is invented and goes into this environment's own dev
database, which nothing else reads. A check that wants projects, items and a plan to work on loads
the dev seed first, an invented record ([`record.md`](record.md)); the command recreates the
database from the migrations:

```bash
cexec modern-app sh -c 'cd backend && uv run cli load-test-data --yes-i-am-sure'
```

**The sync's live proof** (D009). A slice that changes the sync, at either end
([`sync.md`](sync.md)), runs its script with the stack up, from the repo root:

```bash
scripts/sync-live-proof.py
```

It builds `pilot-sync` (`cexec go`), loads the dev seed and leaves it loaded, and puts the dev
backend in testing mode for the store: it appends `FLASK_ENV=testing`, a throwaway `SYNC_TOKEN` and
this environment's id as `STORE_ENVIRONMENT_ID` to `backend/.env`, which the backend restarts on.
It then runs the binary as a plain process on a temporary tree, behind a proxy it can cut, and
proves five things: a file edited in the tree reaches the record; a record edit rewrites the file
and is not sent back; the local check answers a clean save, reverted lines and a stray file; a
dropped connection reconciles; a `manifest` event reconciles. It prints `PASS <n>.` or `FAIL <n>.`
per step and `5 of 5 passed`, and exits 0 only then. On exit, SIGTERM included, it writes
`backend/.env` back byte for byte and waits for the backend to restart on it. A stack that is not
up fails it at once; a failed run keeps its `/tmp/pilot-sync-proof-*` directory, the binary's log
in it.

**The fleet's live check** (D019). A slice that changes how Pilot works the KubeCoder fleet (the
controller's client, the fleet stream, an environment's create, take, reset, start, stop or delete,
a session's start, send or relay: [`controller.md`](controller.md), [`sessions.md`](sessions.md))
proves it on two real turns against KubeCoder's dev stage, `https://kubecoder-dev.home`, with the
stack up; a check of the slice's own that needs the fleet rides on the same turns. The dev stage is
a KubeCoder instance of its own, not production. The check places two work items of
`pvginkel/KubeCoderTestRepo` by repository, one after the other, through the record's testing route:
for the first, Pilot creates an environment of its own there, a managed one of Pilot's bearer; the
second takes it once it is free and resets it; Pilot's timers then stop it and delete it. The
stopped `pvginkel/KubeCoderTestRepo` environments the controller lists are the operator's: Pilot
takes only what it created, and the check touches none of them. Its waits come to 56 minutes at most
(the create and the first turn 20, the reset and the second turn 20, the delete timer 10, the rest
6), so a slice that runs it starts the stack with `timeout 4500` rather than `timeout 900`. The node
admits `maxEnvironments` environments that are not exempt (2 on `kubecoder-dev`), and a create or a
reset beyond them is refused `409 admission-blocked`, F125's failed start; the check holds one at a
time, so it needs `runningEnvironments` below `maxEnvironments`. Without the token in this
environment, with the dev controller down, or with its node full, nothing below runs, and everything
it would prove is *not verified*:

```bash
[ -n "$PILOT_DEV_CONTROLLER_TOKEN" ] && echo "token present"
curl -s -m 10 -o /dev/null -w '%{http_code}\n' https://kubecoder-dev.home/readyz     # 200
curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" https://kubecoder-dev.home/capacity |
  python3 -c 'import json, sys; c = json.load(sys.stdin); print(c["runningEnvironments"], "of", c["maxEnvironments"])'   # fewer than the cap
```

Every step keeps what the next one reads in `tmp/fleet/`, since a shell variable does not outlive
its command. A check cut short after step 2 ends with step 8, which deletes what the check created
and only that, before it runs again: step 1's seed recreates the database step 8 finds them in.

1. **The dev backend in testing mode, on the dev controller**, by the switch the sync's live proof
   makes (`scripts/sync-live-proof.py`), not a second one: settings appended to `backend/.env`,
   which the backend restarts on (`backend/scripts/dev-watch.sh`) and whose last line for a key wins
   (python-dotenv), and the file's original bytes written back in step 8, whatever happened before
   it. A step 1 run again before step 8 keeps the copy the first one saved, the only copy of the
   original, and step 8 clears `tmp/fleet/` once the original is back. `FLASK_ENV=testing` opens the
   testing routes. The token is `PILOT_DEV_CONTROLLER_TOKEN`, which this environment projects from
   its secret catalog (`.kubecoder/config.yaml`) and the backend never reads by that name: it goes
   into the file as `CONTROLLER_TOKEN` and is never printed; the backend's start logs its settings
   with the token as `***`. `ENVIRONMENT_STOP_AFTER_SECONDS=60` and
   `ENVIRONMENT_DELETE_AFTER_SECONDS=300` shorten the shutdown timer and the delete timer to fit the
   check. `CONTROLLER_CA_FILE` stays unset: the `modern-app` container's `REQUESTS_CA_BUNDLE` is the
   system bundle, which holds the homelab root. The dev seed goes in first, for the person the
   check's projects are made by, and the operator's environments of the repository, those no client
   manages, are read with their name, status and `updatedAt` for step 7 to read again. `updatedAt`
   is the later of `createdAt` and its pod's start, so a stopped environment reads its `createdAt`:
   the comparison sees a rename, a delete or one left running, and a start or a reset followed by a
   stop shows in Pilot's log alone:

   ```bash
   cexec modern-app sh -c 'cd backend && uv run cli load-test-data --yes-i-am-sure'
   mkdir -p tmp/fleet && find tmp/fleet -type f ! -name env.orig ! -name no-env -delete
   if [ ! -e tmp/fleet/env.orig ] && [ ! -e tmp/fleet/no-env ]; then
     if [ -e backend/.env ]; then cp backend/.env tmp/fleet/env.orig; else touch tmp/fleet/no-env; fi
   fi
   DB=$(sed -n 's/^DATABASE_URL=postgresql+psycopg:/postgresql:/p' tmp/fleet/env.orig 2>/dev/null | tail -1)
   echo "${DB:-postgresql://postgres:postgres@localhost:5432/pilot}" > tmp/fleet/db
   curl -s -m 15 -G -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" https://kubecoder-dev.home/environments --data-urlencode repo=pvginkel/KubeCoderTestRepo |
     python3 -c 'import json, sys; sys.stdout.writelines(" ".join(str(e[k]) for k in ("envId", "name", "status", "updatedAt")) + "\n" for e in json.load(sys.stdin)["items"] if e["managedBy"] is None)' |
     sort | tee tmp/fleet/operators-before                                             # the operator's, about twelve
   { echo; echo FLASK_ENV=testing; echo CONTROLLER_URL=https://kubecoder-dev.home
     printf 'CONTROLLER_TOKEN=%s\n' "$PILOT_DEV_CONTROLLER_TOKEN"
     echo ENVIRONMENT_STOP_AFTER_SECONDS=60; echo ENVIRONMENT_DELETE_AFTER_SECONDS=300; } >> backend/.env
   SECONDS=0; until curl -s -m 5 http://localhost:3501/health/readyz | grep -q '"controller"' || [ $SECONDS -ge 90 ]; do sleep 1; done
   curl -s -m 10 http://localhost:3501/health/readyz                                   # checks.controller.status "ok"
   curl -s -m 10 http://localhost:3501/metrics | grep '^pilot_fleet_stream_connected'  # 1.0
   grep 'Fleet stream connected' logs/backend.log | tail -1                            # "<n> environments listed"
   ```

   The `controller` check appears once the backend has restarted with a controller; its `ok` is the
   controller's `/readyz`, which asks for no token. The connect line and the gauge at `1` are what
   show the token works: the fleet consumer's list of the controller's environments is
   authenticated.

2. **Two projects, and the first work item placed by repository.** The record's testing route
   `POST /api/testing/projects` makes two open projects of `ada`'s, each with a slug of its own,
   `project-<12 hex>`, the name its environment takes. The SSE stream is held first, as a browser
   holds it. The record's testing route `POST /api/testing/projects/<id>/work` places a work item in
   the first by repository, as the brain places one: its Work keeps `repo`, and its Session is
   `starting` with no Environment. Once the request commits, its start finds no free environment of
   Pilot's own made from the repository and creates one (`POST /environments`, `managed: true`,
   named the project's slug), commits its row, Pilot's own (`server_created_at`, `repo`), as the
   Session's Environment, and awaits its bring-up; then the headless create in `cwd`, then the
   brief as Turn 1. The route answers the work item's id, its Session's too; the subscribe follows
   its `201`:

   ```bash
   for n in 1 2; do
     curl -s -m 10 -X POST http://localhost:3501/api/testing/projects -H 'Content-Type: application/json' \
       -d '{"members": ["ada"]}' | sed -n 's/.*"id": *"\([^"]*\)".*/\1/p' > tmp/fleet/project-$n
     psql "$(cat tmp/fleet/db)" -Atc "select slug from projects where id = '$(cat tmp/fleet/project-$n)'" | tee tmp/fleet/slug-$n   # project-<12 hex>
   done
   timeout 1500 curl -sN 'http://localhost:3501/api/sse/stream?request_id=fleet-check' > tmp/fleet/sse &
   timeout 30 sh -c 'until grep -q "^event: ready" tmp/fleet/sse; do sleep 0.5; done'
   printf '{"repo": "pvginkel/KubeCoderTestRepo", "cwd": "/work/KubeCoderTestRepo", "title": "Fleet check", "brief": "%s"}' \
     "List the files at the root of this repository, then say in one sentence how many there are." > tmp/fleet/start.json
   curl -s -m 30 -w '\n%{http_code}\n' -X POST "http://localhost:3501/api/testing/projects/$(cat tmp/fleet/project-1)/work" \
     -H 'Content-Type: application/json' -d @tmp/fleet/start.json | tee tmp/fleet/started-1   # {"id": ...} 201
   sed -n 's/.*"id": *"\([^"]*\)".*/\1/p' tmp/fleet/started-1 > tmp/fleet/session-1
   curl -s -m 10 -o /dev/null -w '%{http_code}\n' -X POST "http://localhost:3501/api/sessions/$(cat tmp/fleet/session-1)/stream" \
     -H 'Content-Type: application/json' -d '{"request_id": "fleet-check", "view": "fleet-check"}'   # 204
   ```

   The environment is the Session's as soon as the create has answered, while it still provisions.
   Its row is Pilot's own, and the controller reports it named the first project's slug and managed
   by Pilot's client, its `managedBy`, under which its list, filtered, shows it:

   ```bash
   SID=$(cat tmp/fleet/session-1); SECONDS=0
   until psql "$(cat tmp/fleet/db)" -Atc "select environment_id from sessions where id = '$SID'" | grep -q . || [ $SECONDS -ge 120 ]; do sleep 1; done
   psql "$(cat tmp/fleet/db)" -Atc "select environment_id from sessions where id = '$SID'" | tee tmp/fleet/env-id
   ENV=$(cat tmp/fleet/env-id)
   grep "Created environment $ENV from pvginkel/KubeCoderTestRepo" logs/backend.log
   psql "$(cat tmp/fleet/db)" -Atc "select server_created_at is not null, repo, name from environments where id = '$ENV'"   # t|pvginkel/KubeCoderTestRepo|<slug-1>
   curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV" |
     python3 -c 'import json, sys; e = json.load(sys.stdin); print(e["repo"], e["name"], e["status"], e["managedBy"]); open("tmp/fleet/client", "w").write(e["managedBy"] or "")'
   curl -s -m 15 -G -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" https://kubecoder-dev.home/environments \
     --data-urlencode "managedBy=$(cat tmp/fleet/client)" --data-urlencode repo=pvginkel/KubeCoderTestRepo |
     python3 -c 'import json, sys; print("listed under its client:", open("tmp/fleet/env-id").read().strip() in [e["envId"] for e in json.load(sys.stdin)["items"]])'
   ```

   The controller prints `pvginkel/KubeCoderTestRepo <slug-1> provisioning <client>` (or
   `starting`, or `running` once it is up), the client's name not `None`, and the list `True`. No
   Environment within the 2 minutes, or a Session `failed`, failed the check; its `server` records
   say why (step 5), a `409 admission-blocked` among them if the node filled meanwhile.

3. **The first turn, watched.** The current line, read once a second until the turn has ended. It
   runs as long as the environment's bring-up and the turn, up to 20 minutes, so it goes in the
   background:

   ```bash
   SID=$(cat tmp/fleet/session-1); SECONDS=0
   until psql "$(cat tmp/fleet/db)" -Atc "select state_code, current_line from sessions where id = '$SID'" | tee -a tmp/fleet/lines-1 |
     grep -Eq '^(idle|stopped|failed)\|' || [ $SECONDS -ge 1200 ]; do sleep 1; done
   uniq tmp/fleet/lines-1
   ```

   It moves through `starting` lines whose `text` is `Preparing <slug-1>…` (a `starting` line with
   nothing after the bar before it, while the create has not answered), then `Creating the
   session…`, then `running` with `thinking`, `working` (with the `step` of a tool call) and
   `writing`, and ends `idle|` with nothing after the bar: `current_line` null at the turn's end. A
   Session that ends `failed` failed the check; its `server` records say why (step 5).

4. **Free, then a second fresh start that takes it**, run as soon as step 3 has ended, before step
   5: the delete timer deletes the environment 300 s after it became free, and one deleted before
   the take, a `Deleted environment` line before `took environment`, is the check's own pace, not a
   finding: step 8, then the check again. The turn's end left no Session there `running`,
   `starting`, `held`, `stopped` or `failed`, so the environment is free, and the delete timer's
   next tick (`SCHEDULER_TICK_SECONDS`, 10) clears its name at the controller and sets its
   `delete_due_at` (`Environment <id> is free: its name cleared, its delete due <iso>`). A file is
   then written on its checkout through the controller's file API, for the reset to clear, and a
   work item of the same repository placed in the second project:

   ```bash
   ENV=$(cat tmp/fleet/env-id); SECONDS=0
   until grep -q "Environment $ENV is free" logs/backend.log || [ $SECONDS -ge 60 ]; do sleep 1; done
   grep "Environment $ENV is free" logs/backend.log
   psql "$(cat tmp/fleet/db)" -Atc "select name = id, delete_due_at is not null, server_started_at is not null, last_state from environments where id = '$ENV'"   # t|t|t|running
   curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV" |
     python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])'                     # None
   printf 'Written before the reset.\n' | curl -s -m 15 -o /dev/null -w '%{http_code}\n' -X PUT --data-binary @- \
     -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV/file?path=/work/KubeCoderTestRepo/pilot-fleet-check.txt"   # 204
   curl -s -m 30 -w '\n%{http_code}\n' -X POST "http://localhost:3501/api/testing/projects/$(cat tmp/fleet/project-2)/work" \
     -H 'Content-Type: application/json' -d @tmp/fleet/start.json | tee tmp/fleet/started-2   # {"id": ...} 201
   sed -n 's/.*"id": *"\([^"]*\)".*/\1/p' tmp/fleet/started-2 > tmp/fleet/session-2
   ```

   The row reads the environment free and one a start takes: its name its id, its delete due, and
   `running` under Pilot's claim, or `t|t|f|stopping` or `t|t|f|stopped` once the shutdown timer has
   stopped it, 60 s after the turn's end; the controller's `name` is `None`. The second start takes
   it, the most recently freed of the repository's, its claim and its delete cleared, renames it the
   second project's slug and writes `Preparing <slug-2>…`; then it stops it, unless it is stopped,
   waits for its settled `stopped`, resets it (`POST …/reset`) and awaits the bring-up the reset
   ends in, with no start after it:

   ```bash
   SID=$(cat tmp/fleet/session-2); ENV=$(cat tmp/fleet/env-id); SECONDS=0
   until psql "$(cat tmp/fleet/db)" -Atc "select current_line->>'text' from sessions where id = '$SID'" | grep -q '^Preparing' || [ $SECONDS -ge 120 ]; do sleep 1; done
   psql "$(cat tmp/fleet/db)" -Atc "select environment_id = '$ENV', current_line->>'text' from sessions where id = '$SID'"   # t|Preparing <slug-2>…
   grep "Session $SID took environment $ENV" logs/backend.log
   curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV" |
     python3 -c 'import json, sys; e = json.load(sys.stdin); print(e["name"], e["status"])'   # <slug-2> and its status
   ```

   An `f` before the bar, a Session in another environment, is a second create where the take
   belonged, and fails the check.

5. **The first turn's records, read back and seen live.** The records route pages them from `seq`
   1; the SSE stream carried the ones written after the subscribe as `record` frames, and the main
   thread's block starts and text deltas as `partial` frames:

   ```bash
   curl -s -m 10 "http://localhost:3501/api/sessions/$(cat tmp/fleet/session-1)/records?limit=1000" > tmp/fleet/records.json
   python3 - <<'PY'
   import collections, json
   page = json.load(open("tmp/fleet/records.json"))
   records = {r["seq"]: r for r in page["records"]}
   print("records", len(records), "| numbered 1..n:", sorted(records) == list(range(1, len(records) + 1)), "| ended:", page["ended"])
   print("kinds", dict(collections.Counter(r["kind"] for r in records.values())))
   claude = [r for r in records.values() if r["kind"] == "claude"]
   print("raw offsets rising:", [r["raw_offset"] for r in claude] == sorted({r["raw_offset"] for r in claude}))
   print("stream_event lines stored:", sum(isinstance(r["payload"], dict) and r["payload"].get("type") == "stream_event" for r in claude))
   frames = [json.loads(line[6:]) for line in open("tmp/fleet/sse") if line.startswith("data: {")]
   frames = [f["payload"] for f in frames if f.get("type") == "session"]
   live = [f["data"] for f in frames if f["frame"] == "record"]
   seqs = [r["seq"] for r in live]
   print("live records", len(live), "| consecutive to the last:", bool(seqs) and seqs == list(range(seqs[0], max(records) + 1)))
   print("live as read back:", all((r["kind"], r.get("payload")) == (records[r["seq"]]["kind"], records[r["seq"]].get("payload")) for r in live))
   print("partials", sum(f["frame"] == "partial" for f in frames), "| end", sum(f["frame"] == "end" for f in frames))
   PY
   ```

   Every `True`, `ended` false; the kinds `server` (the start's phases), `claude` and one `result`,
   and no `send`, since the brief has no author; no `stream_event` line stored; partials above `0`;
   no `end`, since an `idle` Session's stream goes on.

6. **The second turn, watched, in a tree made anew.** Its current line, as step 3 reads the first's,
   up to 20 minutes for the stop, the reset's bring-up and the turn, in the background:

   ```bash
   SID=$(cat tmp/fleet/session-2); SECONDS=0
   until psql "$(cat tmp/fleet/db)" -Atc "select state_code, current_line from sessions where id = '$SID'" | tee -a tmp/fleet/lines-2 |
     grep -Eq '^(idle|stopped|failed)\|' || [ $SECONDS -ge 1200 ]; do sleep 1; done
   uniq tmp/fleet/lines-2
   ```

   It moves through `Preparing <slug-2>…`, then `Creating the session…`, then `running`, and ends
   `idle|`; a Session that ends `failed` failed the check, its `server` records saying why, a reset
   refused `409 admission-blocked` among them. The log shows the reset made, the database a single
   environment of Pilot's own, and the file step 4 wrote is gone, the checkout cloned again:

   ```bash
   ENV=$(cat tmp/fleet/env-id)
   grep "Reset environment $ENV" logs/backend.log
   psql "$(cat tmp/fleet/db)" -Atc 'select count(*) from environments where server_created_at is not null'   # 1
   curl -s -m 15 -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" \
     "https://kubecoder-dev.home/environments/$ENV/file?path=/work/KubeCoderTestRepo/pilot-fleet-check.txt"   # 404
   ```

7. **Pilot's timers stop the environment, then delete it.** The second turn's end arms the shutdown
   (`Armed the shutdown of environment <id>, due <iso>`), and the delete timer's next tick frees the
   environment again (`Environment <id> is free: …`). The first scheduler tick past the shutdown's
   due stops it (`Stopped environment <id>, due <iso>`), clearing `server_started_at` and
   `stop_due_at`; the first past the delete's due, 300 s after it became free, deletes it (`Deleted
   environment <id>, due <iso>`), its row kept with `last_state` `gone`, which the fleet stream's
   `gone` frame writes again after its `deleting`, and the controller then answers `404`:

   ```bash
   ENV=$(cat tmp/fleet/env-id); SECONDS=0
   until grep -q "Deleted environment $ENV" logs/backend.log || [ $SECONDS -ge 420 ]; do sleep 2; done
   grep -E "(Armed the shutdown of|Stopped|Deleted) environment $ENV|Environment $ENV is free" logs/backend.log
   SECONDS=0
   until [ "$(psql "$(cat tmp/fleet/db)" -Atc "select last_state from environments where id = '$ENV'")" = gone ] &&
     [ "$(curl -s -m 15 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV")" = 404 ] ||
     [ $SECONDS -ge 120 ]; do sleep 2; done
   psql "$(cat tmp/fleet/db)" -Atc "select last_state, server_started_at, stop_due_at, delete_due_at from environments where id = '$ENV'"   # gone|||
   curl -s -m 15 -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV"   # 404
   ```

   The lines come in that order after the first turn's armed shutdown and free; a `Stopped
   environment` line between those and the take is the shutdown timer's stop of a free one, which
   the take allows. No `Stopped environment` line after the second turn, no `Deleted environment`
   line within the 7 minutes, or a row other than `gone`, fails this step, a finding.

   The operator's environments are read again as step 1 read them, and Pilot's log, which names
   each environment Pilot takes, creates, starts, resets, stops or deletes, searched for their ids:

   ```bash
   curl -s -m 15 -G -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" https://kubecoder-dev.home/environments --data-urlencode repo=pvginkel/KubeCoderTestRepo |
     python3 -c 'import json, sys; sys.stdout.writelines(" ".join(str(e[k]) for k in ("envId", "name", "status", "updatedAt")) + "\n" for e in json.load(sys.stdin)["items"] if e["managedBy"] is None)' |
     sort > tmp/fleet/operators-after
   python3 - <<'PY'
   before, after = (set(open(f"tmp/fleet/operators-{when}")) for when in ("before", "after"))
   log = open("logs/backend.log").read()
   ids = {line.split()[0] for line in before | after}
   print("operator's", len(before), "| changed:", sorted({line.split()[0] for line in before ^ after}))
   print("named in Pilot's log:", sorted(i for i in ids if i in log))
   PY
   ```

   Both lists `[]`. An id the log names fails the check, a finding: Pilot acted on an environment it
   did not create. One changed that the log does not name was changed by someone else, the operator
   or KubeCoder's own timers, whose pick takes only environments no client manages, and is no
   finding.

8. **The backend put back, and what the check created deleted**, whatever happened before:
   `backend/.env`'s original bytes written back and the backend restarted on them, which ends the
   SSE stream and leaves it no controller; then every environment of Pilot's own in the check's
   database (`server_created_at` set, with `tmp/fleet/db` there) that the controller still has and
   reports managed is deleted through it, as cleanup only, never as a step's pass: after a whole run
   it answers `404`. The operator's environments are in neither set, and nothing else is deleted.
   Then the token found in none of the logs and files the check wrote:

   ```bash
   if [ -e tmp/fleet/no-env ]; then rm -f backend/.env; else cp tmp/fleet/env.orig backend/.env && cmp backend/.env tmp/fleet/env.orig && echo "backend/.env restored"; fi
   SECONDS=0; until r=$(curl -s -m 5 http://localhost:3501/health/readyz) && [ -n "$r" ] && ! printf '%s' "$r" | grep -q '"controller"' || [ $SECONDS -ge 90 ]; do sleep 1; done
   echo "$r"                                                                                # no controller check
   psql "$(cat tmp/fleet/db)" -Atc 'select id from environments where server_created_at is not null' | while read -r ENV; do
     code=$(curl -s -m 15 -o tmp/fleet/left.json -w '%{http_code}' -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV")
     if [ "$code" = 200 ] && python3 -c 'import json, sys; sys.exit(not json.load(open("tmp/fleet/left.json"))["managedBy"])'; then
       curl -s -m 15 -o /dev/null -w "$ENV deleted: %{http_code}\n" -X DELETE -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV"
     else echo "$ENV: $code"; fi
   done                                                                                     # "<id>: 404" after a whole run, "<id> deleted: 202" after one cut short
   grep -cF -- "$PILOT_DEV_CONTROLLER_TOKEN" logs/backend.log /tmp/pilot-dev.log tmp/fleet/*   # 0 each
   { [ -e tmp/fleet/no-env ] && [ ! -e backend/.env ]; } || cmp -s backend/.env tmp/fleet/env.orig && rm -rf tmp/fleet && echo "tmp/fleet/ cleared"
   ```

**Stop the stack** from another shell, and confirm it is down:

```bash
scripts/dev.py stop          # prints "dev stack stopped"
python3 -c "import socket; print([p for p in (3500, 3501) if socket.socket().connect_ex(('localhost', p)) == 0])"   # []
cexec modern-app ps -eo pid,ppid,etime,args --no-headers   # read it: no honcho, flask or vite left
```

Never stop it by killing the background job or the `cexec` client: the services run in sessions of
their own in the tool container and keep their ports. Read the process table rather than grepping
it, since the pod is one PID namespace and a `grep` matches its own command line.

To leave the dev database empty for the next slice, recreate it from the migrations:

```bash
cexec modern-app sh -c 'cd backend && uv run cli upgrade-db --recreate --yes-i-am-sure'
```

## 3. Push, and confirm the rollout

Pushing is this phase's job. The driver ff-merges locally and never pushes a code phase, then checks
before the doc phase that every repo in `state.json`'s `bases` reached `origin`. Push each one,
honouring any repo named in `plan.md`'s `## Push holds`, in an order that holds:

1. **Read what a public repo's push carries first.** PilotApp and PilotDeploy are public:
   `git log -p origin/main..main` in each, before its push. No secret, token or literal key
   (no client secret, no generated value, no fallback for one), neither of the test account's
   credentials, and no excerpt of a real project, chat or decision document. One found comes out of
   the history before the push; it is never pushed. The credentials are counted, never shown:

   ```bash
   for r in . ../PilotDeploy; do git -C $r log -p origin/main..main | grep -cF -e "$PILOT_DEV_TEST_USERNAME" -e "$PILOT_DEV_TEST_PASSWORD"; done   # 0 each
   ```

2. **PilotDeploy first when it adds a pin key the PilotApp build writes.** The build's last stage,
   `cicd.writeVersionPins`, edits `images.pilot` and `images.pilotUI` in PilotDeploy's
   `config/dev/values.yaml` and `config/prd/values.yaml` in place, in one commit, and fails on a
   file or key that `origin/main` does not already hold. Every green build pins, so the rule is
   about a key the PilotDeploy change adds, not about pinning as such. Otherwise push the chart
   first when the new image needs what the chart adds, the image first when the chart needs the new
   image, and either when neither does.
3. **Rebase, never force.** Every green PilotApp build commits its pins to PilotDeploy's `main`, so
   before a PilotDeploy push, `git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy rebase
   origin/main`. A rejected push means a pin commit landed first: fetch and rebase again. The same
   holds for ArgoCDDeploy and Architecture, which the whole estate pushes to: rebase onto
   `origin/main`, run their gate again from their root, then push. PilotDeploy's `prd` is the
   promotion job's: nothing here pushes it, but for its creation ([a stage's first
   deploy](#a-stages-first-deploy), step 2).
4. **A registry entry only once what it names exists.** A producer's entry in Architecture's
   `pipeline-producers.yaml` once its `AaC/<Repo>` job has a green build: a registered producer
   with no artifact fails `AaC/Architecture`'s collector. A stage of Pilot's in ArgoCDDeploy's
   `releases/values.yaml` once the PilotDeploy branch it follows is on `origin` and its values pin
   images the registry holds (`:0`, the seed, names none): the Application syncs as soon as it
   exists, and one whose branch is not on `origin` cannot resolve its revision. ArgoCDDeploy and
   Architecture are the estate's, and a push there needs the operator's ruling in the plan.
5. **The plan's `## Ordering constraints`**, where they say more.

Before the first push, record production's pod and its images, which step 4.1 reads again:

```bash
mkdir -p tmp/prd && cexec iac kubectl -n pilot-prd get pods -l app.kubernetes.io/name=pilot \
  -o jsonpath='{range .items[*]}{.metadata.name} {.spec.containers[*].image}{"\n"}{end}' | tee tmp/prd/before
```

### Following a build

Each push starts its repo's jobs, and each is followed to its end:

| Push to | Starts |
|---------|--------|
| PilotApp | `PilotApp/Build-Main` (`Jenkinsfile`: the suites, the sidecar's tests, three images tagged `dev-<n>` and `dev-latest`, the pin commit of two for both stages) and `AaC/PilotApp` (`Jenkinsfile.architecture`: validates and archives `docs/architecture/*.yaml`) |
| PilotDeploy's `main`, the build's pin commits included | `AaC/PilotDeployDev` (`Jenkinsfile.architecture-dev`: generates and publishes the `pilot-dev-deploy` model, the dev stage's), and `pilot-dev` rolls it |
| PilotDeploy's `prd`, which a promotion moves | `AaC/PilotDeploy` (generates and publishes the `pilot-deploy` model, production's) |
| Architecture | `AaC/Architecture` |
| ArgoCDDeploy | `AaC/ArgoCDDeploy` |

`PilotApp/Promote-PRD` has no trigger, and nothing here starts it.

`AaC/Architecture` also runs after every green `AaC/PilotApp`, `AaC/PilotDeploy` and
`AaC/PilotDeployDev` build (an upstream trigger, after a 90 s quiet period). `track_build.py` does not wait for it: it follows an
`AaC/*` build to that build's own result alone.

```bash
timeout 1800 track_build.py PilotApp/Build-Main --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
timeout 900 track_build.py AaC/PilotApp --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
```

It needs `JENKINS_TOKEN`, which this environment projects, and the deploy repo's clone
(`../PilotDeploy`), which it fetches to follow the pin commit. Once `PilotApp/Build-Main`'s build is
green it reads the pin line from the console (`pvginkel/PilotDeploy <sha> pins
config/dev/values.yaml, config/prd/values.yaml.`) and waits until every Application that follows
the commit has rolled it: one whose source tracks PilotDeploy's `main` and whose values files name a
pinned file, which is `pilot-dev` alone, since `pilot-prd` tracks `prd`. The `timeout` sits above
the build (the job's first build took 270 s, the model app's run near ten minutes), the 120 s Argo
CD may take to see the pin commit and the ten-minute roll deadline after that, so that a slow roll
ends in `track_build.py`'s own exit `6` with its diagnosis rather than in `timeout`'s `124` with
none. The pin commit starts `AaC/PilotDeployDev` alone, which `track_build.py` does not follow:
`AaC/PilotDeploy` builds `prd`. While Argo CD has no
`pilot-dev` (before its first deploy below), pass `--no-follow-argocd`: the pins have nothing to
roll them yet. Its exit status says where it stopped:

| Exit | Meaning | What to do |
|------|---------|------------|
| `0` | Every build is green and `pilot-dev` rolled the pin commit (or nothing was followed into Argo CD). | Wait for the roll check to end, then go on to the deployed checks. The Application is `Healthy` once the old pod's termination has started, not once the pod is gone. |
| `1` | A build failed; nothing was followed into Argo CD. | `--diagnose` printed the console tail; the full log's path is in the summary. A finding. |
| `3` | An operational problem: Jenkins or Kubernetes auth, a build that never appeared, a failed fetch; with `--deploy`, a repo and branch no Application follows. | Fix the cause and run it again; the build is not re-run. |
| `4` | The builds are green, but there is no clone of the deploy repo they pushed to. | The summary gives the `git clone` line. This environment declares PilotDeploy, so this is an environment fault, not a slice finding. |
| `5` | The roll failed: the sync failed, an error condition, or the Application settled `Degraded` or `Missing`. | A finding; the diagnosis written beside the logs names the failing resources and holds the PreSync hook's log. |
| `6` | The Application had not rolled the commit ten minutes after Argo CD saw it. | A finding; the diagnosis is on disk as for `5`. |
| `7` | Argo CD will not roll the commit on its own: it never saw it (a lost webhook), or the sync is not automated. | A finding, except where a step below expects it. This kubeconfig cannot sync or refresh an Application, and waiting longer does not help. |

A push to PilotDeploy's `main` that no build made is followed into Argo CD by its commit, once it is
on `origin/main`; `pilot-dev` is the Application that rolls it:

```bash
timeout 900 track_build.py --deploy PilotDeploy main "$(git -C ../PilotDeploy rev-parse HEAD)"
```

### The roll check

**Every roll of a running pod is watched from before its push until the old pod is gone.**
`pilot-dev` rolls by starting the new pod beside the old one (`RollingUpdate`, `maxSurge: 1`,
`maxUnavailable: 0`), and retires the old pod only once the new one is ready. Each of the old pod's
containers goes on serving for 15 s after its termination starts, then the backend drains: its
`preStop` calls `/health/drain` and waits for it 40 s at most, and the drain stops the backend's
long-lived jobs (the fleet stream, the relays, the timers) within `GRACEFUL_SHUTDOWN_TIMEOUT`,
20 s. Nothing drains to completion: a relay cut mid-turn is resumed by the new pod. The termination
grace is 70 s (15 + 40 + 15), so the old pod is gone within 70 s. This environment reads the prd
cluster, where both stages run, but cannot roll anything there (its kubeconfig is read-only outside
`development`), so the check rides the roll a push causes: a PilotApp push, whose build pins new
images, and a push to PilotDeploy's `main` that changes dev's pod template
(`chart/templates/deployment.yaml`, or a value of `config/dev/values.yaml` it reads). A PilotDeploy
push that leaves dev's pod template alone rolls nothing and has no roll check. Start the check in
the background, before the push:

```bash
SECONDS=0
mkdir -p tmp/roll && rm -f tmp/roll/*
cexec iac kubectl -n pilot-dev get pods -l app.kubernetes.io/name=pilot -o name | cut -d/ -f2 > tmp/roll/old
[ "$(wc -l < tmp/roll/old)" -eq 1 ] || { echo "tmp/roll/old names $(wc -l < tmp/roll/old) pods, not one: no check"; exit 1; }
probe() { while :; do echo "$(date -u +%T.%3N) $(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1") $1"; sleep 0.5; done >> tmp/roll/probes; }
probe https://pilot-dev.home/ & probe https://pilot-dev.home/api/auth/self &
until [ $SECONDS -ge 1800 ] || { cexec iac kubectl -n pilot-dev get pods -l app.kubernetes.io/name=pilot --no-headers --request-timeout=10s > tmp/roll/now &&
    sed "s/^/$(date -u +%T) /" tmp/roll/now >> tmp/roll/pods && ! grep -qwFf tmp/roll/old tmp/roll/now; }; do sleep 5; done
kill $(jobs -p)
grep -vwFf tmp/roll/old tmp/roll/now | cut -d' ' -f1 > tmp/roll/new
grep -qwFf tmp/roll/old tmp/roll/now && echo "the old pod outlived the check"
awk '{ print $3, $2 }' tmp/roll/probes | sort | uniq -c
```

`tmp/roll/old` names the one pod that runs before the push, and the check stops at once unless it
names exactly one: none means the listing failed, or `pilot-dev` is not deployed yet (a first
deploy has no roll check); two, a roll already under way, so wait for it to end and start again. The
check probes the site every half second, with reads that write nothing, lists the pods every 5 s,
and ends on its own once the pod in `tmp/roll/old` is gone, its termination included, or after
30 minutes. It prints how often each URL gave each status. `/` answers `200` (the UI's nginx) and
`/api/auth/self` answers `401` (the backend, through that nginx, refusing a request with no
session); any other status is a finding: a `502` or `504` is nothing answering behind a proxy, a
`503` traffic that reached a pod while it was not ready, a draining one included, and a `000` no
answer at all. `tmp/roll/probes` has each answer's time (UTC), and `tmp/roll/pods` the pods' states
every 5 s to set beside it. "the old pod outlived the check" means the roll did not finish within
30 minutes, which is a finding too. The pod the roll produced is named in `tmp/roll/new`. One roll
at a time: a push waits until the check of the one before it has ended.

### A stage's first deploy

While Argo CD has no Application for a stage (`cexec iac kubectl -n argocd-prd get application
pilot-<stage>` answers `NotFound`), the slice that adds it takes it live, and the order is fixed.
Steps 1 to 4 of the order above decide it; this is how each push is followed. The commands name
`pilot-dev`, whose first deploy also put production on the `prd` branch (step 2).

1. **PilotDeploy's `main`**, with the stage's `config/<stage>/`: its `values.yaml` holds every key
   the build pins, pinned to images the registry holds (a build's tag, never the `:0` seed), so
   that the stage syncs before PilotApp's push; its `terraform.tfvars` sets `manage_webhook =
   false`, the repository's one webhook being production's. Follow the push into the Applications
   that track `main` already with `track_build.py --deploy` (above); with none, it refuses with
   exit `3`, and there is nothing to follow.
2. **PilotDeploy's `prd`, while `origin` has none** (`git -C ../PilotDeploy ls-remote --heads origin
   prd` prints nothing). It is made once, by hand, at the commit step 1 pushed, whose
   `config/prd/values.yaml` pins no `:prd-<n>` tag: the promotion job admits that tip unrecorded
   and refuses every other one no release records ([`deployment.md`](deployment.md)). Production's
   render there is the one `pilot-prd` runs, so moving it onto `prd` (step 3) rolls nothing. The
   push starts `AaC/PilotDeploy`'s first build from `prd`:

   ```bash
   git -C ../PilotDeploy show HEAD:config/prd/values.yaml | grep -cE '^[^#]*:prd-[0-9]'   # 0
   git -C ../PilotDeploy push origin "$(git -C ../PilotDeploy rev-parse HEAD):refs/heads/prd"
   timeout 900 track_build.py AaC/PilotDeploy --hash "$(git -C ../PilotDeploy rev-parse HEAD)" --appear-timeout 120 --diagnose
   ```

   From then on only the promotion moves `prd`.
3. **ArgoCDDeploy**, the stage's entry. Follow `AaC/ArgoCDDeploy` by the pushed commit, and the
   registry's sync:

   ```bash
   timeout 900 track_build.py --deploy ArgoCDDeploy main "$(git -C /work/scratch/ArgoCDDeploy rev-parse HEAD)"
   ```

   The Application `releases` rolls the commit, and that creates `pilot-<stage>`. `argocd-prd`, Argo
   CD's own Application, follows the same repo and branch and is synced by hand on purpose, so the
   run ends `7` with `argocd-prd` the one Application reported as having no automated sync policy,
   or `0` if it had compared the commit already. Either is the expected end when the summary lists
   `releases` as rolled; anything else is a finding. An Application the commit moved onto another
   branch, `pilot-prd` onto `prd`, is `Synced` there at the commit it ran before, its pod the one
   recorded before the first push:

   ```bash
   cexec iac kubectl -n argocd-prd get application pilot-prd \
     -o jsonpath='{.spec.source.targetRevision} {.status.sync.revision} {.status.sync.status} {.status.health.status}{"\n"}'
   ```

4. **The first sync**, which has no pod before it and so no roll check. `pilot-dev` syncs on its
   own: Argo applies the chart's Namespace `pilot-dev` first, before it creates the hook Job; then
   the PreSync hook (Job `tf-presync-pilot-dev` in `argocd-hooks`) applies PilotDeploy's Terraform
   with `config/dev/`, which makes the stage's role and database, `pilot_dev_db`, on `postgres-pas`
   and writes the Secret `pilot-db` into `pilot-dev`; then the secret generators and the
   ExternalSecrets; then the Deployment, whose init container `migrate` applies the migrations
   before the backend starts. Follow it:

   ```bash
   timeout 300 sh -c 'until cexec iac kubectl -n argocd-prd get application pilot-dev -o name; do sleep 5; done'
   git -C ../PilotDeploy fetch -q
   timeout 900 track_build.py --deploy PilotDeploy main "$(git -C ../PilotDeploy rev-parse origin/main)"
   ```

   Exit `0` is `pilot-dev` `Synced` at that commit and no longer `Progressing`. Read the hook's
   apply at once, while its pod is still there to read:

   ```bash
   cexec iac kubectl -n argocd-hooks logs job/tf-presync-pilot-dev | grep -E 'Creation complete|Apply complete'
   ```

   On the first sync `module.db`'s role, database and Secret are among the resources it created; a
   later sync applies `0 added`. The site's name and certificate follow the sync (step 4.5).
5. **PilotApp**, last, now that the stage runs, so that its build's pin commit rolls `pilot-dev`
   under the roll check, as every later build's does. Follow `PilotApp/Build-Main` and
   `AaC/PilotApp` to green as above; then `git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy
   show origin/main:config/dev/values.yaml` pins both images to `:dev-<n>` and `config/prd/values.yaml`
   to `:prd-<n>`, `<n>` the build's number. Bring the local PilotDeploy up to it
   (`git -C ../PilotDeploy rebase origin/main`).

## 4. The deployed checks

After every push that deployed to `pilot-dev` (a roll, a PilotDeploy sync, a first deploy), all of
them. A first deploy's run after its step 5: until PilotApp's build pins `dev-<n>`, the stage runs
the seed pins and the registry holds no `dev-*` tag for step 2 to find. Steps 1 to 5 and 8 only
read, through the read-only kubeconfig (`cexec iac kubectl`), which cannot read Secrets, exec,
port-forward or proxy; step 6 signs in, and step 7 may write.

Once any roll check has ended the old pod is gone, so the label names one pod, the one the push
produced (`tmp/roll/new`):

```bash
POD=$(cexec iac kubectl -n pilot-dev get pods -l app.kubernetes.io/name=pilot -o name | cut -d/ -f2)
```

1. **The Applications.** `pilot-dev`'s revision is the head of PilotDeploy's `origin/main`, which
   carries the latest green build's pins, `Synced` and `Healthy`; the namespace is the chart's, as
   Argo CD tracks it (`pilot-dev:/Namespace:pilot-dev/pilot-dev`), not Terraform's. `pilot-prd` is
   where the pushes found it: on `prd`, `Synced` at `origin/prd`'s tip, its pod and images the ones
   recorded before the first push:

   ```bash
   git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy log -1 --format='%H %s' origin/main
   cexec iac kubectl -n argocd-prd get application pilot-dev \
     -o jsonpath='{.status.sync.revision} {.status.sync.status} {.status.health.status}{"\n"}'
   cexec iac kubectl get namespace pilot-dev -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/tracking-id}{"\n"}'
   git -C ../PilotDeploy rev-parse origin/prd
   cexec iac kubectl -n argocd-prd get application pilot-prd \
     -o jsonpath='{.spec.source.targetRevision} {.status.sync.revision} {.status.sync.status} {.status.health.status}{"\n"}'
   cexec iac kubectl -n pilot-prd get pods -l app.kubernetes.io/name=pilot \
     -o jsonpath='{range .items[*]}{.metadata.name} {.spec.containers[*].image}{"\n"}{end}' | diff tmp/prd/before - && echo "pilot-prd unchanged"
   ```

2. **The pod and its images.** One pod, `2/2 Running`; `migrate` terminated `Completed`; `backend`
   and `ui` ready with no restarts; `pilot` and `pilot-ui` at the tag `origin/main`'s
   `config/dev/values.yaml` pins, `:dev-<n>`, `<n>` the latest green `PilotApp/Build-Main` build,
   and each `imageID` the digest the registry holds for that tag. The build pushed `pilot-sync`
   too, and each image's `dev-latest` is its `dev-<n>`:

   ```bash
   cexec iac kubectl -n pilot-dev get pod $POD -o wide
   cexec iac kubectl -n pilot-dev get pod $POD -o jsonpath='{range .status.initContainerStatuses[*]}{.name} {.state.terminated.reason}{"\n"}{end}{range .status.containerStatuses[*]}{.name} {.ready} {.restartCount} {.image} {.imageID}{"\n"}{end}'
   curl -fsS -u "$JENKINS_USER:$JENKINS_TOKEN" "$JENKINS_URL/job/PilotApp/job/Build-Main/lastSuccessfulBuild/api/json?tree=number"; echo
   for img in pilot pilot-ui pilot-sync; do for tag in dev-<n> dev-latest; do
     echo "$img:$tag $(curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' http://registry:5000/v2/$img/manifests/$tag | grep -i docker-content-digest)"
   done; done
   cexec iac kubectl -n pilot-dev logs $POD -c migrate    # the migrations, run before the backend served
   ```

   The backend's log is the pod's: `cexec iac kubectl -n pilot-dev logs $POD -c backend`. Once
   step 6 has signed in, it holds the test account's username, because every signed-in request logs
   the caller's email, and the realm signs in by email: from then on it is read only through a
   `grep` for the lines a check wants, never whole, and no line of a signed-in request is printed.

3. **The backend's readiness, on the pod's IP, its controller and its fleet stream.** `200` with
   `"status": "ok"`: `checks.database` `ok` (connected, no migration pending) and
   `checks.controller` `ok` (the controller's `/readyz` answers, verified against the homelab root
   the chart mounts). The `controller` check is not critical: a controller that does not answer
   reads `"status": "degraded"`, still `200`, and is a finding here. The controller is
   `kubecoder-dev`'s, never the operator's fleet:

   ```bash
   IP=$(cexec iac kubectl -n pilot-dev get pod $POD -o jsonpath='{.status.podIP}')
   curl -s -m 10 -w '\n%{http_code}\n' "http://$IP:3501/health/readyz"
   cexec iac kubectl -n pilot-dev get pod $POD \
     -o jsonpath='{.spec.containers[?(@.name=="backend")].env[?(@.name=="CONTROLLER_URL")].value}{"\n"}'   # https://kubecoder-dev.home
   ```

   Never through `https://pilot-dev.home/health/readyz`: `/health/` is registered at the app root,
   outside `/api/`, and the UI's nginx answers every such path with `index.html` and `200`, ready
   backend or not (ElectronicsInventory's `https://parts.ginbov.nl/health/readyz` does today:
   `200`, `text/html`). This pod reaches pod IPs directly.

   The controller's `/readyz` asks for no token. What shows the token works is the fleet
   consumer's connect line in the backend's log, `Fleet stream connected; <n> environments listed`,
   `<n>` `kubecoder-dev`'s environments: its list of them is authenticated. A `Loop fleet raised;
   restarting in <n> s` after it is the stream dropping and the supervisor reopening it; one that
   keeps coming is a finding:

   ```bash
   cexec iac kubectl -n pilot-dev logs $POD -c backend | grep -E 'Fleet stream connected|Loop fleet'
   ```

4. **The secrets.** Five ExternalSecrets, each `SecretSynced` and ready: `pilot-oidc`,
   `pilot-kubecoder` and `pilot-sync` (from `openbao-prd`, `eso/prd/pilot/dev/oidc`,
   `eso/prd/pilot/dev/kubecoder` and `eso/prd/pilot/dev/sync`) and the generated `pilot-secret-key`
   and `pilot-drain-auth`:

   ```bash
   cexec iac kubectl -n pilot-dev get externalsecrets
   cexec iac kubectl -n pilot-dev get externalsecrets -o jsonpath='{range .items[*]}{.metadata.name} {.spec.data[*].remoteRef.key}{"\n"}{end}'
   ```

   The Secrets themselves are unreadable here: the running backend (step 3's database connection and
   fleet stream, step 6's sign-in, the store's sync calls answered with no `401`) is what shows they
   reached it.

5. **The site and its certificate.** `200`, curl exit `0`, against the homelab root alone; the
   certificate the homelab CA's (issuer `homelab-ca Intermediate CA`), for `pilot-dev.home`; the
   Service carries `nginx.webathome.org/server-name: pilot-dev.home`,
   `nginx.webathome.org/is-public: "false"` and `nginx.webathome.org/enable-ssl: "yes"`, from which
   the homelab DNS publishes the name and the front door serves it with that certificate:

   ```bash
   mkdir -p tmp/ca-none
   curl -s -m 10 --cacert /usr/local/share/ca-certificates/homelab-root.crt --capath tmp/ca-none -o /dev/null -w '%{http_code}\n' https://pilot-dev.home/; echo "exit $?"
   echo | openssl s_client -connect pilot-dev.home:443 -servername pilot-dev.home 2>/dev/null | openssl x509 -noout -issuer -subject -ext subjectAltName -enddate
   cexec iac kubectl -n pilot-dev get service pilot -o jsonpath='{.metadata.annotations}{"\n"}'
   ```

   Not plain `curl`: the system bundle holds the public CAs beside the homelab root, and curl reads
   `/etc/ssl/certs` as its CA path even beside `--cacert`, hence the empty `--capath`. Exit `60` is
   a certificate the homelab root does not vouch for, or one for another name: the front door serves
   its default certificate for a host it has no certificate for. Exit `6` is a name that does not
   resolve yet. After the first sync the homelab DNS publishes the name, and the front door's
   manager (`nginx-prd`, Deployment `nginxmanager`) requests the site's first certificate from the
   homelab step-ca, so retry for ten minutes; past that it is a finding, with `cexec iac kubectl -n
   nginx-prd logs deploy/nginxmanager --all-containers` beside it. `pilot-dev.home` is internal: it
   resolves on the LAN alone, and there is no outside path to check.

6. **Sign-in, as the test account.** `scripts/dev-sign-in.py` walks the app's sign-in as a browser
   does, through Keycloak's real login page, with the test account's username and password from
   `PILOT_DEV_TEST_USERNAME` and `PILOT_DEV_TEST_PASSWORD`, which this environment projects from its
   secret catalog (`.kubecoder/config.yaml`):

   ```bash
   scripts/dev-sign-in.py          # https://pilot-dev.home; exit 0 signed in as an editor
   ```

   It prints a line a step: an anonymous `/api/auth/self` answers `401`; the login route answers
   `302` to `auth.ginbov.nl`'s authorization endpoint in realm `homelab`, with `redirect_uri`
   `https://pilot-dev.home/api/auth/callback`; Keycloak answers `200` with its login form; the
   form's post answers `302` to the app's callback with a code; the callback answers `302` to `/`
   and sets `access_token`, `refresh_token` and `id_token`; the signed-in `/api/auth/self` answers
   `200` with `editor` among its roles. The test account holds the dev client's `editor` role alone,
   so that role shows the backend signs in on dev's own client (`eso/prd/pilot/dev/oidc`). A step
   that answers otherwise ends the script with exit `1` and a `FAIL:` line naming it, a Keycloak
   page by what it asks (refused credentials, a required action). Exit `2` is the two variables
   unset, which leaves every signed-in check *not verified*, never passed.

   Neither credential is printed, nor anything that carries one: the script never prints Keycloak's
   pages, which echo the username back, nor `/api/auth/self`'s `email` and `name`, the email being
   the username; a check that reads `/api/auth/self` itself prints `roles` alone. Neither credential
   goes into a file, a commit or the close-out. The session is the app's cookies, which the script
   writes to `tmp/dev-session/`, readable by this user alone: `cookies.txt` for curl and
   `state.json` for Playwright (step 7).

7. **The slice's own checks on dev**: every acceptance criterion in `verification.json` that only
   the deployment can show, exercised against `https://pilot-dev.home` as the test account, through
   the API or the UI. A check may write; what it writes is invented, as on the dev stack. Nothing in
   the app creates a project yet, so a check makes its record through the record's testing
   endpoints, which answer on dev to the signed-in test account ([`projects.md`](projects.md)): a
   project with its opening, its items of each kind, an agent's save of one. Through the API, curl
   sends the session and keeps the cookies a refresh replaces:

   ```bash
   S=tmp/dev-session/cookies.txt
   curl -s -m 10 -b $S -c $S https://pilot-dev.home/api/auth/self | python3 -c 'import json, sys; print(json.load(sys.stdin)["roles"])'
   ```

   The access token lasts minutes; the backend refreshes it from `refresh_token` on the next
   request, and `-c` keeps the new pair. A `401` once the refresh token has expired too is the
   session's end: run `scripts/dev-sign-in.py` again.

   Through the UI, a Playwright script loads the session as its context's `storageState`. It runs in
   the `modern-app` container, whose Chromium does not trust the homelab root that curl does, so
   `ignoreHTTPSErrors` stands in for it, step 5 having checked the certificate; `NODE_PATH` lets a
   script under `tmp/` resolve `@playwright/test`:

   ```bash
   mkdir -p tmp/dev-ui && cat > tmp/dev-ui/check.cjs <<'EOF'
   const { chromium } = require('@playwright/test');
   (async () => {
     const browser = await chromium.launch();
     const context = await browser.newContext({ storageState: 'tmp/dev-session/state.json', ignoreHTTPSErrors: true });
     const page = await context.newPage();
     await page.goto('https://pilot-dev.home/');
     // The check's own steps; its screenshots go into tmp/dev-ui/.
     await browser.close();
   })();
   EOF
   cexec modern-app env NODE_PATH=frontend/node_modules timeout 300 node tmp/dev-ui/check.cjs
   ```

   The UI shows the signed-in person, so a check reads what it checks, never a page's text whole.
   When the phase ends, `rm -rf tmp/dev-session tmp/dev-ui`: the cookies are a live session.

   **The dev stage's store**, `pvginkel-pilotprojects-d75970` on `kubecoder-dev`
   ([`deployment.md`](deployment.md)), is the slices' own, as `pilot-dev` is. A check that needs it
   reads its sidecar's log, and stops, starts or resets it through `kubecoder-dev`'s API with
   Pilot's dev credential. A reset, of a stopped store, clones PilotProjects' `main` again and
   empties the sidecar's data, so a push to PilotProjects reaches the store that way. A session
   there whose working directory is `/work/PilotProjects` gets the hook ([`sync.md`](sync.md)).
   Production's store is never touched:

   ```bash
   STORE=pvginkel-pilotprojects-d75970
   cexec iac kubectl -n kubecoder-dev logs $STORE -c pilot-sync --tail=50
   curl -s -m 15 -o /dev/null -w '%{http_code}\n' -X POST -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" \
     "https://kubecoder-dev.home/environments/$STORE/stop"   # or start, or reset once stopped; 200 or 202
   ```

8. **The builds.** Each of `PilotApp/Build-Main` and `AaC/PilotApp` has a green latest build, and
   `AaC/PilotDeploy` too where the phase pushed `prd` (a first deploy's step 2). `PilotApp/Promote-PRD`
   has no build the phase started: its last build, if it has one, is older than the phase:

   ```bash
   for j in job/PilotApp/job/Build-Main job/AaC/job/PilotApp job/AaC/job/PilotDeploy; do
     curl -fsS -u "$JENKINS_USER:$JENKINS_TOKEN" "$JENKINS_URL/$j/lastBuild/api/json?tree=fullDisplayName,result"; echo
   done
   curl -fsS -u "$JENKINS_USER:$JENKINS_TOKEN" "$JENKINS_URL/job/PilotApp/job/Promote-PRD/api/json?tree=lastBuild%5Bnumber,timestamp%5D"; echo
   ```

## 5. Check off `verification.json`

Mark each acceptance criterion with the evidence that settled it: the command run and what it
returned, or the call made and what it answered. A criterion nothing in steps 1–4 exercised has not
passed by inspection. It is either an untested criterion (a finding) or a check this doc is missing.

## Findings

Blocking findings come back as appended phases. Findings below the bar go in the close-out report
for the operator to triage. A check that cannot run at all (no credential, a port already held, a
service unreachable) is reported as *not verified*, never as passed. The phase may end with a
criterion unproven if it says so. It may not end with one assumed.

## The operator gate

The operator's gate is the close-out report, after the run, and the promotion is theirs. A slice
whose push reached `pilot-dev` appends an `action` entry to its close-out that names the promotion
as the operator's: start `PilotApp/Promote-PRD` once dev holds what they want in production, the
PilotDeploy commit that carries the slice and the build `<n>` it pins named in it. Its Consequence:
production goes on running the release before it, and the slice's change is on dev alone. What
production then shows its users is the operator's to see; nothing here signs in to
`https://pilot.ginbov.nl`.
