# Slice testing strategy

How a slice is proven once its phases are merged. This is the doc `.aiworkflowrc` names as
`test_phase.strategy`: the run loop's test phase is "read this and execute it", and nothing else
names it. Read it top to bottom and do what it says.

## What this phase proves, and what it does not

**Nothing is deployed yet.** There is no production and no dev instance: the deploy chart, the
Jenkins job and the database come with the deploy slice, which rewrites this doc with the push, the
rollout and the deployed checks. Until then `.aiworkflowrc` sets `[push] enabled = false`, so a
slice's commits stay in this environment, and this phase proves the slice **here**: the suites, then
the dev stack running in this environment.

What that cannot show, it says so: anything that needs the real fleet (a KubeCoder controller, a
store environment, a worker session, YouTrack) is reported as *not verified* until a deployment
exists to check it against.

## 0. Preconditions

The driver has ff-merged every code phase into the base branch. Confirm the tree is clean
(`git status --short`) before starting. A dirty tree here means an earlier phase left something
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

`kc project test` prints one `[ OK ]` per suite and no counts. Run the two suites once directly and
read the counts, so that a suite that collected nothing is not taken for a green one:

```bash
cexec modern-app sh -c 'cd backend && uv run pytest -q' 2>&1 | tail -1
cexec modern-app sh -c 'cd frontend && pnpm playwright test' 2>&1 | tail -3
```

## 2. The local live check

The dev stack is the backend (Flask, debug mode) on 3501, the Vite dev server on 3500 and the SSE
gateway on 3502, all in the `modern-app` tool container, against the `pilot` database on the
environment's PostgreSQL sidecar. `scripts/dev.py` starts all three; it runs until stopped, so start
it in the background under a timeout:

```bash
timeout 900 scripts/dev.py > /tmp/pilot-dev.log 2>&1 &
```

Wait for the three ports with a socket connect, not with `curl`: the gateway's stream never ends,
and a `curl` against it burns its whole timeout.

```bash
for i in $(seq 1 60); do
  python3 -c "import socket; [socket.create_connection(('localhost', p), 1).close() for p in (3500, 3501, 3502)]" 2>/dev/null && break
  sleep 1
done
```

Then the stack's own checks, each expected to answer `200`:

```bash
curl -s -m 10 http://localhost:3501/health/readyz      # "ready": true, database connected, sse_gateway ok
curl -s -m 10 -o /dev/null -w '%{http_code}\n' http://localhost:3500/
curl -s -m 10 http://localhost:3500/api/auth/self      # through the Vite proxy; the dev stack runs without OIDC, as "Local Admin"
curl -s -m 10 http://localhost:3502/readyz             # the SSE gateway
```

The frontend is also published at the `frontend` URL `kc env describe` lists
(`https://frontend.<environment id>.home`); a check that needs the page as a browser on another
machine sees it uses that URL.

Then the slice's own checks: every acceptance criterion in `verification.json` that the suites did
not settle, exercised against the running stack through the API, or through the UI with
Playwright. The data a check writes is invented and goes into this environment's own dev database,
which nothing else reads.

**Stop the stack** from another shell, and confirm it is down:

```bash
scripts/dev.py stop          # prints "dev stack stopped"
python3 -c "import socket; print([p for p in (3500, 3501, 3502) if socket.socket().connect_ex(('localhost', p)) == 0])"   # []
cexec modern-app ps -eo pid,ppid,etime,args --no-headers   # read it: no honcho, flask, vite or ssegateway left
```

Never stop it by killing the background job or the `cexec` client: the services run in sessions of
their own in the tool container and keep their ports. Read the process table rather than grepping
it, since the pod is one PID namespace and a `grep` matches its own command line.

To leave the dev database empty for the next slice, recreate it from the migrations:

```bash
cexec modern-app sh -c 'cd backend && uv run cli upgrade-db --recreate --yes-i-am-sure'
```

## 3. No push

`[push] enabled = false`: the driver lands the slice on the local base branch and checks no push.
Do not push from this phase.

## 4. Check off `verification.json`

Mark each acceptance criterion with the evidence that settled it: the command run and what it
returned, or the call made and what it answered. A criterion nothing in steps 1 and 2 exercised has
not passed by inspection. It is either an untested criterion (a finding) or a check this doc is
missing.

## Findings

Blocking findings come back as appended phases. Findings below the bar go in the close-out report
for the operator to triage. A check that cannot run at all (no credential, a port already held, a
service that does not exist yet) is reported as *not verified*, never as passed. The phase may end
with a criterion unproven if it says so. It may not end with one assumed.

## The operator gate

The operator's gate is the close-out report, after the run.
