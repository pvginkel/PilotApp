# Slice testing strategy

How a slice is proven once its phases are merged. This is the doc `.aiworkflowrc` names as
`test_phase.strategy`: the run loop's test phase is "read this and execute it", and nothing else
names it. Read it top to bottom and do what it says.

## What this phase proves, and what it does not

**There is one deployment, and it is production.** A push to `main` runs the `PilotApp` Jenkins job
(the suites, the sidecar's tests, the `pilot`, `pilot-ui` and `pilot-sync` images), which pins
`pilot` and `pilot-ui` in `pvginkel/PilotDeploy`, from
which Argo CD rolls the Application `pilot-prd`: the pod behind `https://pilot.ginbov.nl`, which the
operator and their wife use. There is no dev instance. So this phase proves the slice **locally
first** (the suites, then the dev stack running here), pushes only what that proved, confirms the
rollout, and then checks the deployment for what only it can show.

Two things follow from production being the only instance:

- **What a check writes there is real.** Every deployed check below only reads, and the sign-in
  check stops at Keycloak's login form. No check here signs in: no agent holds an account with the
  `editor` role, so whether a signed-in user reaches the app is the operator's to confirm. Their
  own first sign-in is the last check of a go-live (ruling D1), and the close-out report names it
  as theirs.
- There is no `devlock`: nothing is occupied for the length of a check. Two slices that push close
  together both deploy, and the later image holds both.

What the checks cannot show from here is reported as *not verified*: the site from outside the
LAN (step 4.5), a signed-in session, and anything that needs a part of the fleet no slice has wired
into the deployment yet (a store environment, YouTrack). The KubeCoder controller is wired: what
Pilot does with it is proven on a real turn against KubeCoder's dev stage (§2, the fleet's live
check), and production shows only that its backend reaches its controller (step 4.3), since no
check there starts anything.

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
controller's client, the fleet stream, an environment's start or stop, a session's start, send or
relay: [`controller.md`](controller.md), [`sessions.md`](sessions.md)) proves it on one real turn against KubeCoder's dev stage, `https://kubecoder-dev.home`, with
the stack up; a check of the slice's own that needs the fleet rides on the same turn. The dev stage
is a KubeCoder instance of its own, not production, and its `pvginkel/KubeCoderTestRepo`
environments are there for checks like this one: the check starts one, and Pilot stops it. Its
waits come to 25 minutes at most (the environment's start and the turn 20, the timer's stop 5), so
a slice that runs it starts the stack with `timeout 2700` rather than `timeout 900`. Without the
token in this environment, or with the dev controller down, nothing below runs, and everything it
would prove is *not verified*:

```bash
[ -n "$PILOT_DEV_CONTROLLER_TOKEN" ] && echo "token present"
curl -s -m 10 -o /dev/null -w '%{http_code}\n' https://kubecoder-dev.home/readyz     # 200
```

Every step keeps what the next one reads in `tmp/fleet/`, since a shell variable does not outlive
its command:

1. **The dev backend in testing mode, on the dev controller**, by the switch the sync's live proof
   makes (`scripts/sync-live-proof.py`), not a second one: settings appended to `backend/.env`,
   which the backend restarts on (`backend/scripts/dev-watch.sh`) and whose last line for a key wins
   (python-dotenv), and the file's original bytes written back in step 6, whatever happened before
   it. A step 1 run again before step 6 keeps the copy the first one saved, the only copy of the
   original, and step 6 clears `tmp/fleet/` once the original is back. `FLASK_ENV=testing` opens the
   testing routes. The token is `PILOT_DEV_CONTROLLER_TOKEN`, which this environment projects from
   its secret catalog (`.kubecoder/config.yaml`) and the backend never reads by that name: it goes
   into the file as `CONTROLLER_TOKEN` and is never printed; the backend's start logs its settings
   with the token as `***`.
   `ENVIRONMENT_STOP_AFTER_SECONDS=60` shortens the shutdown timer to fit the check.
   `CONTROLLER_CA_FILE` stays unset: the `modern-app` container's `REQUESTS_CA_BUNDLE` is the system
   bundle, which holds the homelab root. The dev seed goes in first, for a project to start the
   session for:

   ```bash
   cexec modern-app sh -c 'cd backend && uv run cli load-test-data --yes-i-am-sure'
   mkdir -p tmp/fleet && find tmp/fleet -type f ! -name env.orig ! -name no-env -delete
   if [ ! -e tmp/fleet/env.orig ] && [ ! -e tmp/fleet/no-env ]; then
     if [ -e backend/.env ]; then cp backend/.env tmp/fleet/env.orig; else touch tmp/fleet/no-env; fi
   fi
   DB=$(sed -n 's/^DATABASE_URL=postgresql+psycopg:/postgresql:/p' tmp/fleet/env.orig 2>/dev/null | tail -1)
   echo "${DB:-postgresql://postgres:postgres@localhost:5432/pilot}" > tmp/fleet/db
   { echo; echo FLASK_ENV=testing; echo CONTROLLER_URL=https://kubecoder-dev.home
     printf 'CONTROLLER_TOKEN=%s\n' "$PILOT_DEV_CONTROLLER_TOKEN"; echo ENVIRONMENT_STOP_AFTER_SECONDS=60; } >> backend/.env
   SECONDS=0; until curl -s -m 5 http://localhost:3501/health/readyz | grep -q '"controller"' || [ $SECONDS -ge 90 ]; do sleep 1; done
   curl -s -m 10 http://localhost:3501/health/readyz                                   # checks.controller.status "ok"
   curl -s -m 10 http://localhost:3501/metrics | grep '^pilot_fleet_stream_connected'  # 1.0
   grep 'Fleet stream connected' logs/backend.log | tail -1                            # "<n> environments listed"
   ```

   The `controller` check appears once the backend has restarted with a controller; its `ok` is the
   controller's `/readyz`, which asks for no token. The connect line and the gauge at `1` are what
   show the token works: the fleet consumer's list of the controller's environments is
   authenticated.

2. **An environment**: one of `pvginkel/KubeCoderTestRepo` that the controller lists `stopped` and
   not exempt (`capabilities.capacityExempt.enabled` false), since Pilot's timer never stops an
   exempt one. None listed is *not verified*:

   ```bash
   curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" https://kubecoder-dev.home/environments |
     python3 -c 'import json, sys; print(*[e["envId"] for e in json.load(sys.stdin)["items"] if e["repo"] == "pvginkel/KubeCoderTestRepo" and e["status"] == "stopped" and not e["capabilities"]["capacityExempt"]["enabled"]][:1])' > tmp/fleet/env-id
   cat tmp/fleet/env-id
   ```

3. **A session there, started by Pilot and watched.** The SSE stream is held first, as a browser
   holds it. The testing route `POST /api/testing/sessions` starts a `work` Session for an existing
   Project the way the server does: the Session `starting`, the environment's start (answered `202`,
   so `server_started_at` is set), the headless create in `cwd`, then the brief as Turn 1. No route
   lists projects, so the id comes from the database. The subscribe follows the route's `201`:

   ```bash
   timeout 1500 curl -sN 'http://localhost:3501/api/sse/stream?request_id=fleet-check' > tmp/fleet/sse &
   timeout 30 sh -c 'until grep -q "^event: ready" tmp/fleet/sse; do sleep 0.5; done'
   psql "$(cat tmp/fleet/db)" -Atc 'select id from projects order by number limit 1' > tmp/fleet/project
   printf '{"project_id": "%s", "environment_id": "%s", "cwd": "/work/KubeCoderTestRepo", "brief": "%s"}' \
     "$(cat tmp/fleet/project)" "$(cat tmp/fleet/env-id)" \
     "List the files at the root of this repository, then say in one sentence how many there are." > tmp/fleet/start.json
   curl -s -m 30 -w '\n%{http_code}\n' -X POST http://localhost:3501/api/testing/sessions \
     -H 'Content-Type: application/json' -d @tmp/fleet/start.json | tee tmp/fleet/started   # {"id": ...} 201
   sed -n 's/.*"id": *"\([^"]*\)".*/\1/p' tmp/fleet/started > tmp/fleet/session
   curl -s -m 10 -o /dev/null -w '%{http_code}\n' -X POST "http://localhost:3501/api/sessions/$(cat tmp/fleet/session)/stream" \
     -H 'Content-Type: application/json' -d '{"request_id": "fleet-check", "view": "fleet-check"}'   # 204
   ```

   Then the current line, read once a second until the turn has ended. It runs as long as the
   environment's start and the turn, up to 20 minutes, so it goes in the background:

   ```bash
   SID=$(cat tmp/fleet/session); SECONDS=0
   until psql "$(cat tmp/fleet/db)" -Atc "select state_code, current_line from sessions where id = '$SID'" | tee -a tmp/fleet/lines |
     grep -Eq '^(idle|stopped|failed|ended)\|' || [ $SECONDS -ge 1200 ]; do sleep 1; done
   uniq tmp/fleet/lines
   ```

   It moves through `starting` lines whose `text` is `Starting <environment name>…`, then
   `Creating the session…`, then `running` with `thinking`, `working` (with the `step` of a tool call) and
   `writing`, and ends `idle|` with nothing after the bar: `current_line` null at the turn's end. A
   Session that ends `failed` failed the check; its `server` records say why (step 4).

4. **The records, read back and seen live.** The records route pages them from `seq` 1; the SSE
   stream carried the ones written after the subscribe as `record` frames, and the main thread's
   block starts and text deltas as `partial` frames:

   ```bash
   curl -s -m 10 "http://localhost:3501/api/sessions/$(cat tmp/fleet/session)/records?limit=1000" > tmp/fleet/records.json
   python3 - <<'EOF'
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
   EOF
   ```

   Every `True`, `ended` false; the kinds `server` (the start's phases), `claude` and one `result`,
   and no `send`, since the brief has no author; no `stream_event` line stored; partials above `0`;
   no `end`, since an `idle` Session's stream goes on.

5. **Pilot's shutdown timer stops the environment.** The turn's end arms it (`Armed the shutdown
   of environment <id>, due <iso>`), and the first scheduler tick past the due time
   (`SCHEDULER_TICK_SECONDS`, 10) stops it (`Stopped environment <id>, due <iso>`), clearing
   `server_started_at` and `stop_due_at`. The controller then reports it `stopping` or `stopped`:

   ```bash
   ENV=$(cat tmp/fleet/env-id); SECONDS=0
   until grep -q "Stopped environment $ENV" logs/backend.log || [ $SECONDS -ge 300 ]; do sleep 2; done
   grep -E "(Armed the shutdown of|Stopped) environment $ENV" logs/backend.log
   psql "$(cat tmp/fleet/db)" -Atc "select server_started_at, stop_due_at, last_state from environments where id = '$ENV'"   # ||stopping or ||stopped
   curl -s -m 15 -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" "https://kubecoder-dev.home/environments/$ENV" |
     python3 -c 'import json, sys; print(json.load(sys.stdin)["status"])'
   ```

   No `Stopped environment` line within the 5 minutes fails this step, a finding. The environment
   is then stopped through the controller, as cleanup only, never as the step's pass:

   ```bash
   curl -s -m 15 -o /dev/null -w '%{http_code}\n' -X POST -H "Authorization: Bearer $PILOT_DEV_CONTROLLER_TOKEN" \
     "https://kubecoder-dev.home/environments/$(cat tmp/fleet/env-id)/stop"   # 200 or 202
   ```

6. **The backend put back**, whatever happened before, once the environment the check started is
   stopped: `backend/.env`'s original bytes written back, the backend restarted on them (which ends
   the SSE stream), and the token found in none of the logs and files the check wrote:

   ```bash
   if [ -e tmp/fleet/no-env ]; then rm -f backend/.env; else cp tmp/fleet/env.orig backend/.env && cmp backend/.env tmp/fleet/env.orig && echo "backend/.env restored"; fi
   SECONDS=0; until r=$(curl -s -m 5 http://localhost:3501/health/readyz) && [ -n "$r" ] && ! printf '%s' "$r" | grep -q '"controller"' || [ $SECONDS -ge 90 ]; do sleep 1; done
   echo "$r"                                                                                # no controller check
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
   (no client secret, no generated value, no fallback for one), and no excerpt of a real project,
   chat or decision document. One found comes out of the history before the push; it is never
   pushed.
2. **PilotDeploy first when it adds a pin key the PilotApp build writes.** The build's last stage,
   `cicd.writeVersionPins`, edits `images.pilot` and `images.pilotUI` in PilotDeploy's
   `config/prd/values.yaml` in place, and fails on a key that file on `origin/main` does not
   already hold. Every green build pins, so the rule is about a key the PilotDeploy change adds,
   not about pinning as such. Otherwise push the chart first when the new image needs what the
   chart adds, the image first when the chart needs the new image, and either when neither does.
3. **Rebase, never force.** Every green PilotApp build commits its pins to PilotDeploy's `main`, so
   before a PilotDeploy push, `git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy rebase
   origin/main`. A rejected push means a pin commit landed first: fetch and rebase again. The same
   holds for ArgoCDDeploy and Architecture, which the whole estate pushes to: rebase onto
   `origin/main`, run their gate again from their root, then push.
4. **A registry entry only once what it names has built green.** A producer's entry in
   Architecture's `pipeline-producers.yaml` once its `AaC/<Repo>` job has a green build: a
   registered producer with no artifact fails `AaC/Architecture`'s collector. Pilot's entry in
   ArgoCDDeploy's `releases/values.yaml` once PilotDeploy's `origin/main` pins both images to a
   green build's (`:0`, the seed, names no image): the Application syncs as soon as it exists.
   ArgoCDDeploy and Architecture are the estate's, and a push there needs the operator's ruling in
   the plan (the deploy slice's D1 is one).
5. **The plan's `## Ordering constraints`**, where they say more.

### Following a build

Each push starts its repo's jobs, and each is followed to its end:

| Push to | Starts |
|---------|--------|
| PilotApp | `PilotApp` (`Jenkinsfile`: the suites, the sidecar's tests, three images, the pin commit of two) and `AaC/PilotApp` (`Jenkinsfile.architecture`: validates and archives `docs/architecture/*.yaml`) |
| PilotDeploy, the build's pin commits included | `AaC/PilotDeploy` (generates and publishes the `pilot-deploy` model) |
| Architecture | `AaC/Architecture` |
| ArgoCDDeploy | `AaC/ArgoCDDeploy` |

Once `pilot-app` and `pilot-deploy` are registered, `AaC/Architecture` also runs after every green
`AaC/PilotApp` and `AaC/PilotDeploy` build (an upstream trigger, after a 90 s quiet period);
`track_build.py` waits for it as their downstream build.

```bash
timeout 1800 track_build.py PilotApp --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
timeout 900 track_build.py AaC/PilotApp --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
timeout 900 track_build.py AaC/PilotDeploy --hash <the PilotDeploy commit> --appear-timeout 120 --diagnose
```

It needs `JENKINS_TOKEN`, which this environment projects, and the deploy repo's clone
(`../PilotDeploy`), which it fetches to follow the pin commit. Once `PilotApp`'s build is green it
reads the pin line from the console (`pvginkel/PilotDeploy <sha> pins config/prd/values.yaml.`)
and waits until `pilot-prd` has rolled that commit. The `timeout` sits above the build (the first
`PilotApp` build took 270 s, the model app's run near ten minutes), the 120 s Argo CD may take to
see the pin commit and the ten-minute roll deadline after that, so that a slow roll ends in
`track_build.py`'s own exit `6` with its diagnosis rather than in `timeout`'s `124` with none. The
pin commit started `AaC/PilotDeploy`: follow that build too, by the commit the pin line names.
While no Application follows PilotDeploy (before the first deploy below), pass
`--no-follow-argocd`: the pins have nothing to roll them yet. Its exit status says where it
stopped:

| Exit | Meaning | What to do |
|------|---------|------------|
| `0` | Every build is green and `pilot-prd` rolled the pin commit (or nothing was followed into Argo CD). | Wait for the roll check to end, then go on to the deployed checks. The Application is `Healthy` once the old pod's termination has started, not once the pod is gone. |
| `1` | A build failed; nothing was followed into Argo CD. | `--diagnose` printed the console tail; the full log's path is in the summary. A finding. |
| `3` | An operational problem: Jenkins or Kubernetes auth, a build that never appeared, a failed fetch; with `--deploy`, a repo and branch no Application follows. | Fix the cause and run it again; the build is not re-run. |
| `4` | The builds are green, but there is no clone of the deploy repo they pushed to. | The summary gives the `git clone` line. This environment declares PilotDeploy, so this is an environment fault, not a slice finding. |
| `5` | The roll failed: the sync failed, an error condition, or the Application settled `Degraded` or `Missing`. | A finding; the diagnosis written beside the logs names the failing resources and holds the PreSync hook's log. |
| `6` | The Application had not rolled the commit ten minutes after Argo CD saw it. | A finding; the diagnosis is on disk as for `5`. |
| `7` | Argo CD will not roll the commit on its own: it never saw it (a lost webhook), or the sync is not automated. | A finding, except where a step below expects it. This kubeconfig cannot sync or refresh an Application, and waiting longer does not help. |

A PilotDeploy push that no build made is followed into Argo CD by its commit, once it is on
`origin/main`, beside its `AaC/PilotDeploy` build:

```bash
timeout 900 track_build.py --deploy PilotDeploy main "$(git -C ../PilotDeploy rev-parse HEAD)"
```

### The roll check

**Every roll of a running pod is watched from before its push until the old pod is gone.**
`pilot-prd` rolls by starting the new pod beside the old one (`RollingUpdate`, `maxSurge: 1`,
`maxUnavailable: 0`), and retires the old pod only once the new one is ready. Each of the old pod's
containers goes on serving for 15 s after its termination starts, then the backend drains: its
`preStop` calls `/health/drain` and waits for it 40 s at most, and the drain stops the backend's
long-lived jobs (the fleet stream, the relays, the timers) within `GRACEFUL_SHUTDOWN_TIMEOUT`,
20 s. Nothing drains to completion: a relay cut mid-turn is resumed by the new pod. The termination
grace is 70 s (15 + 40 + 15), so the old pod is gone within 70 s. This
environment reads prd but cannot roll it (its kubeconfig is read-only outside `development`), so
the check rides the roll a push causes: a PilotApp push, whose build pins new images, and a
PilotDeploy push that changes the pod template (`chart/templates/deployment.yaml`, or a value it
reads). A PilotDeploy push that leaves the pod template alone rolls nothing and has no roll check.
Start the check in the background, before the push:

```bash
SECONDS=0
mkdir -p tmp/roll && rm -f tmp/roll/*
cexec iac kubectl -n pilot-prd get pods -l app.kubernetes.io/name=pilot -o name | cut -d/ -f2 > tmp/roll/old
[ "$(wc -l < tmp/roll/old)" -eq 1 ] || { echo "tmp/roll/old names $(wc -l < tmp/roll/old) pods, not one: no check"; exit 1; }
probe() { while :; do echo "$(date -u +%T.%3N) $(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1") $1"; sleep 0.5; done >> tmp/roll/probes; }
probe https://pilot.ginbov.nl/ & probe https://pilot.ginbov.nl/api/auth/self &
until [ $SECONDS -ge 1800 ] || { cexec iac kubectl -n pilot-prd get pods -l app.kubernetes.io/name=pilot --no-headers --request-timeout=10s > tmp/roll/now &&
    sed "s/^/$(date -u +%T) /" tmp/roll/now >> tmp/roll/pods && ! grep -qwFf tmp/roll/old tmp/roll/now; }; do sleep 5; done
kill $(jobs -p)
grep -vwFf tmp/roll/old tmp/roll/now | cut -d' ' -f1 > tmp/roll/new
grep -qwFf tmp/roll/old tmp/roll/now && echo "the old pod outlived the check"
awk '{ print $3, $2 }' tmp/roll/probes | sort | uniq -c
```

`tmp/roll/old` names the one pod that runs before the push, and the check stops at once unless it
names exactly one: none means the listing failed, or Pilot is not deployed yet (the first deploy
below has no roll check); two, a roll already under way, so wait for it to end and start again. The
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

### The first deploy

While Argo CD has no `pilot-prd` (`cexec iac kubectl -n argocd-prd get application pilot-prd`
answers `NotFound`), a slice's push takes Pilot live, and the order is fixed. Steps 1 to 3 of the
order above decide it; this is how each push is followed.

1. **PilotDeploy**, with `images.pilot` and `images.pilotUI` in `config/prd/values.yaml`. Follow
   its `AaC/PilotDeploy` build to green. Until `AaC/Architecture` has collected `pilot-app`, that
   build's console carries two `gap:` lines (`app:pilot` and `app:pilot-ui` resolve to no
   producer); they are expected, and the model is whole from the first `AaC/PilotDeploy` build
   after that collection, which only a later PilotDeploy push starts.
2. **PilotApp.** Follow `PilotApp` with `--no-follow-argocd` and `AaC/PilotApp` to green, then the
   pin commit: `git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy show
   origin/main:config/prd/values.yaml` pins both images to `:<n>`, `<n>` the build's number, and
   that commit's `AaC/PilotDeploy` build is green too. Bring the local PilotDeploy up to it
   (`git -C ../PilotDeploy rebase origin/main`).
3. **Architecture**, the slice's producer entries, now that both `AaC/` jobs have a green build.
   Follow `AaC/Architecture` by the pushed commit (`--appear-timeout` stays at its default 300 s,
   above the job's 90 s quiet period). It is green with `pilot-deploy`'s references to
   `app:pilot` and `app:pilot-ui` reported as tolerated `dangling-reference` warnings until
   `pilot-deploy` is regenerated after this collection.
4. **ArgoCDDeploy**, Pilot's entry, now that the pins name a green build's images. Follow
   `AaC/ArgoCDDeploy` by the pushed commit, and the registry's sync:

   ```bash
   timeout 900 track_build.py --deploy ArgoCDDeploy main "$(git -C /work/scratch/ArgoCDDeploy rev-parse HEAD)"
   ```

   The Application `releases` rolls the commit, and that creates `pilot-prd`. `argocd-prd`, Argo
   CD's own Application, follows the same repo and branch and is synced by hand on purpose, so the
   run ends `7` with `argocd-prd` the one Application reported as having no automated sync policy,
   or `0` if it had compared the commit already. Either is the expected end when the summary lists
   `releases` as rolled; anything else is a finding.
5. **The first sync**, which has no pod before it and so no roll check. `pilot-prd` syncs on its
   own: Argo applies the chart's Namespace `pilot-prd` first, before it creates the hook Job; then
   the PreSync hook (Job `tf-presync-pilot-prd` in `argocd-hooks`) applies PilotDeploy's
   Terraform, which makes Pilot's role and database on `postgres-pas` and writes the Secret
   `pilot-db` into `pilot-prd`; then the secret generators and the ExternalSecrets; then the
   Deployment, whose init container `migrate` applies the migrations before the backend starts.
   Follow it:

   ```bash
   timeout 300 sh -c 'until cexec iac kubectl -n argocd-prd get application pilot-prd -o name; do sleep 5; done'
   git -C ../PilotDeploy fetch -q
   timeout 900 track_build.py --deploy PilotDeploy main "$(git -C ../PilotDeploy rev-parse origin/main)"
   ```

   Exit `0` is `pilot-prd` `Synced` at that commit and no longer `Progressing`. Read the hook's
   apply at once, while its pod is still there to read:

   ```bash
   cexec iac kubectl -n argocd-hooks logs job/tf-presync-pilot-prd | grep -E 'Creation complete|Apply complete'
   ```

   On the first sync `module.db`'s role, database and Secret are among the resources it created; a
   later sync applies `0 added`.

## 4. The deployed checks

After every push that deployed (a roll, a PilotDeploy sync, the first deploy), all of them. Each
only reads, and each runs through the read-only kubeconfig (`cexec iac kubectl`), which cannot
read Secrets, exec, port-forward or proxy.

Once any roll check has ended the old pod is gone, so the label names one pod, the one the push
produced (`tmp/roll/new`):

```bash
POD=$(cexec iac kubectl -n pilot-prd get pods -l app.kubernetes.io/name=pilot -o name | cut -d/ -f2)
```

1. **The Application.** Its revision is the head of PilotDeploy's `origin/main`, which carries the
   latest green build's pins, `Synced` and `Healthy`; the namespace is the chart's, as Argo CD
   tracks it (`pilot-prd:/Namespace:pilot-prd/pilot-prd`), not Terraform's:

   ```bash
   git -C ../PilotDeploy fetch -q && git -C ../PilotDeploy log -1 --format='%H %s' origin/main
   cexec iac kubectl -n argocd-prd get application pilot-prd \
     -o jsonpath='{.status.sync.revision} {.status.sync.status} {.status.health.status}{"\n"}'
   cexec iac kubectl get namespace pilot-prd -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/tracking-id}{"\n"}'
   ```

2. **The pod and its images.** One pod, `2/2 Running`; `migrate` terminated `Completed`; `backend`
   and `ui` ready with no restarts; `pilot` and `pilot-ui` at `:<n>`, `<n>` the
   latest green `PilotApp` build, and each `imageID` the digest the registry holds for that tag:

   ```bash
   cexec iac kubectl -n pilot-prd get pod $POD -o wide
   cexec iac kubectl -n pilot-prd get pod $POD -o jsonpath='{range .status.initContainerStatuses[*]}{.name} {.state.terminated.reason}{"\n"}{end}{range .status.containerStatuses[*]}{.name} {.ready} {.restartCount} {.image} {.imageID}{"\n"}{end}'
   curl -fsS -u "$JENKINS_USER:$JENKINS_TOKEN" "$JENKINS_URL/job/PilotApp/lastSuccessfulBuild/api/json?tree=number"; echo
   for img in pilot pilot-ui; do
     curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' http://registry:5000/v2/$img/manifests/<n> | grep -i docker-content-digest
   done
   cexec iac kubectl -n pilot-prd logs $POD -c migrate    # the migrations, run before the backend served
   ```

   The backend's log is the pod's: `cexec iac kubectl -n pilot-prd logs $POD -c backend`.

3. **The backend's readiness, on the pod's IP, and its fleet stream.** `200` with `"status":
   "ok"`: `checks.database` `ok` (connected, no migration pending) and `checks.controller` `ok` (the
   controller's `/readyz` answers, verified against the homelab root the chart mounts). The
   `controller` check is not critical: a controller that does not answer reads `"status":
   "degraded"`, still `200`, and is a finding here:

   ```bash
   IP=$(cexec iac kubectl -n pilot-prd get pod $POD -o jsonpath='{.status.podIP}')
   curl -s -m 10 -w '\n%{http_code}\n' "http://$IP:3501/health/readyz"
   ```

   Never through `https://pilot.ginbov.nl/health/readyz`: `/health/` is registered at the app
   root, outside `/api/`, and the UI's nginx answers every such path with `index.html` and `200`,
   ready backend or not (ElectronicsInventory's `https://parts.ginbov.nl/health/readyz` does today:
   `200`, `text/html`). This pod reaches pod IPs directly.

   The controller's `/readyz` asks for no token. What shows the token works is the fleet
   consumer's connect line in the backend's log, `Fleet stream connected; <n> environments listed`,
   `<n>` the production controller's environments: its list of them is authenticated. A `Loop fleet
   raised; restarting in <n> s` after it is the stream dropping and the supervisor reopening it; one
   that keeps coming is a finding:

   ```bash
   cexec iac kubectl -n pilot-prd logs $POD -c backend | grep -E 'Fleet stream connected|Loop fleet'
   ```

4. **The secrets.** Four ExternalSecrets, each `SecretSynced` and ready: `pilot-oidc` and
   `pilot-kubecoder` (from `openbao-prd`, `eso/prd/pilot/prd/oidc` and
   `eso/prd/pilot/prd/kubecoder`) and the generated `pilot-secret-key` and `pilot-drain-auth`:

   ```bash
   cexec iac kubectl -n pilot-prd get externalsecrets
   ```

   The Secrets themselves are unreadable here: the running backend (step 3's database connection and
   fleet stream, step 6's sign-in redirect) is what shows they reached it.

5. **The public site and its certificate.** `200`, curl exit `0`, against a bundle of the public
   CAs alone; the certificate a public CA's (Let's Encrypt), for `pilot.ginbov.nl`; the Service
   carries `nginx.webathome.org/server-name: pilot.ginbov.nl` and
   `nginx.webathome.org/is-public: "true"`:

   ```bash
   mkdir -p tmp/public-ca/none && cat /usr/share/ca-certificates/mozilla/*.crt > tmp/public-ca/bundle.pem
   curl -s -m 10 --cacert tmp/public-ca/bundle.pem --capath tmp/public-ca/none -o /dev/null -w '%{http_code}\n' https://pilot.ginbov.nl/; echo "exit $?"
   echo | openssl s_client -connect pilot.ginbov.nl:443 -servername pilot.ginbov.nl 2>/dev/null | openssl x509 -noout -issuer -subject -ext subjectAltName -enddate
   cexec iac kubectl -n pilot-prd get service pilot -o jsonpath='{.metadata.annotations}{"\n"}'
   ```

   Not plain `curl`: the system bundle holds the homelab's private root
   (`/usr/local/share/ca-certificates/homelab-root.crt`), and curl reads `/etc/ssl/certs` as its
   CA path even beside `--cacert`, so either accepts a `homelab-ca` certificate. Exit `60` is a
   certificate the public CAs do not vouch for, or one for another name: the front door serves its
   default certificate for a host it has no certificate for. After the first sync the front door's
   manager (`nginx-prd`, Deployment `nginxmanager`) requests the site's first certificate and
   retries every minute until it is issued, so retry for ten minutes; past that it is a finding,
   with `cexec iac kubectl -n nginx-prd logs deploy/nginxmanager --all-containers` beside it.

   From here `pilot.ginbov.nl` resolves to the front door's inside address, and the public address
   it has on the internet does not answer from inside the LAN: the site from outside, the phone's
   path, is *not verified* here.

6. **Sign-in.** With no session, `/api/auth/self` answers `401`. The login route answers `302` to
   `auth.ginbov.nl`'s authorization endpoint in realm `homelab`, with `client_id=pilot-app` and
   `redirect_uri=https%3A%2F%2Fpilot.ginbov.nl%2Fapi%2Fauth%2Fcallback`; Keycloak answers that
   request `200` with its login form (`id="kc-form-login"`):

   ```bash
   curl -s -m 10 -o /dev/null -w '%{http_code}\n' https://pilot.ginbov.nl/api/auth/self
   LOGIN=$(curl -s -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' 'https://pilot.ginbov.nl/api/auth/login?redirect=/')
   echo "$LOGIN"
   curl -s -m 10 -o tmp/kc-login.html -w '%{http_code}\n' "${LOGIN#* }"
   grep -o 'id="kc-form-login"\|kc-error-message\|Client not found\.\|Invalid parameter: [a-z_]*' tmp/kc-login.html | sort -u
   ```

   The login route builds its redirect from configuration and the origin the request came in on
   (the `redirect_uri` is that origin's callback), without asking Keycloak (and answers `400`
   without its `redirect` parameter), so the `302` proves the configuration and only
   Keycloak's answer proves the client: a client that does not exist, or a redirect URI it does not
   register, answers `400` with `kc-error-message` ("Client not found.", "Invalid parameter:
   redirect_uri"). The page title, "Sign in to Homelab", is the same on both, so it is no marker.
   Nothing is entered in the form.

7. **The builds.** Each of `PilotApp`, `AaC/PilotApp` and `AaC/PilotDeploy` has a green latest
   build, the pin commits' `AaC/PilotDeploy` builds included:

   ```bash
   for j in job/PilotApp job/AaC/job/PilotApp job/AaC/job/PilotDeploy; do
     curl -fsS -u "$JENKINS_USER:$JENKINS_TOKEN" "$JENKINS_URL/$j/lastBuild/api/json?tree=fullDisplayName,result"; echo
   done
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

The operator's gate is the close-out report, after the run; at a go-live, their own first sign-in
to `https://pilot.ginbov.nl` is part of it.
