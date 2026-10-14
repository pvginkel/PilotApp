# Slice testing strategy

How a slice is proven once its phases are merged. This is the doc `.aiworkflowrc` names as
`test_phase.strategy`: the run loop's test phase is "read this and execute it", and nothing else
names it. Read it top to bottom and do what it says.

## What this phase proves, and what it does not

**There is one deployment, and it is production.** A push to `main` runs the `PilotApp` Jenkins job
(the suites, the `pilot` and `pilot-ui` images), which pins the images in `pvginkel/PilotDeploy`, from
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
LAN (step 4.5), a signed-in session, and anything that needs the real fleet (a KubeCoder controller,
a store environment, a worker session, YouTrack) until a slice wires it into the deployment.

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

`kc project test` prints one `[ OK ]` per suite and no counts. Run the two suites once directly and
read the counts, so that a suite that collected nothing is not taken for a green one:

```bash
cexec modern-app sh -c 'cd backend && uv run pytest -q' 2>&1 | tail -1
cexec modern-app sh -c 'cd frontend && pnpm playwright test' 2>&1 | tail -3
```

Then the same verbs from the root of every other repo the slice touched, each where it declares
them: `../PilotDeploy`, whose `test` reads `../PilotApp/docs/architecture/architecture.yaml` and so
needs this checkout beside it, and a registry repo the slice changed in `/work/scratch/`
(ArgoCDDeploy, Architecture).

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
not settle and that the stack can show, exercised against it through the API, or through the UI
with Playwright. The data a check writes is invented and goes into this environment's own dev
database, which nothing else reads.

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
| PilotApp | `PilotApp` (`Jenkinsfile`: the suites, both images, the pin commit) and `AaC/PilotApp` (`Jenkinsfile.architecture`: validates and archives `docs/architecture/*.yaml`) |
| PilotDeploy, the build's pin commits included | `AaC/PilotDeploy` (generates and publishes the `pilot-deploy` model) |
| Architecture | `AaC/Architecture` |
| ArgoCDDeploy | `AaC/ArgoCDDeploy` |

Once `pilot-app` and `pilot-deploy` are registered, `AaC/Architecture` also runs after every green
`AaC/PilotApp` and `AaC/PilotDeploy` build (an upstream trigger, after a 90 s quiet period);
`track_build.py` waits for it as their downstream build.

```bash
timeout 1200 track_build.py PilotApp --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
timeout 900 track_build.py AaC/PilotApp --hash "$(git rev-parse HEAD)" --appear-timeout 120 --diagnose
timeout 900 track_build.py AaC/PilotDeploy --hash <the PilotDeploy commit> --appear-timeout 120 --diagnose
```

It needs `JENKINS_TOKEN`, which this environment projects, and the deploy repo's clone
(`../PilotDeploy`), which it fetches to follow the pin commit. Once `PilotApp`'s build is green it
reads the pin line from the console (`pvginkel/PilotDeploy <sha> pins config/prd/values.yaml.`)
and waits until `pilot-prd` has rolled that commit: the build takes a few minutes, the roll about
one more, and the roll deadline is ten minutes, hence the `timeout`. The pin commit started
`AaC/PilotDeploy`: follow that build too, by the commit the pin line names. While no Application
follows PilotDeploy (before the first deploy below), pass `--no-follow-argocd`: the pins have
nothing to roll them yet. Its exit status says where it stopped:

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
containers goes on serving for 15 s after its termination starts, then the backend drains (its
`preStop` calls `/health/drain`); its termination grace is 90 s, so it is gone within 90 s. This
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

1. **PilotDeploy**, with `images.pilot`, `images.pilotUI` and `images.sseGateway` in
   `config/prd/values.yaml`. Follow its `AaC/PilotDeploy` build to green. Until
   `AaC/Architecture` has collected `pilot-app`, that build's console carries two `gap:` lines
   (`app:pilot` and `app:pilot-ui` resolve to no producer); they are expected, and the model is
   whole from the first `AaC/PilotDeploy` build after that collection, which only a later
   PilotDeploy push starts.
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

2. **The pod and its images.** One pod, `3/3 Running`; `migrate` terminated `Completed`; `backend`,
   `ui` and `sse-gateway` ready with no restarts; `pilot` and `pilot-ui` at `:<n>`, `<n>` the
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

3. **The backend's readiness, on the pod's IP.** `200` with `"ready": true`, the database
   connected with no migration pending, and the SSE gateway reachable:

   ```bash
   IP=$(cexec iac kubectl -n pilot-prd get pod $POD -o jsonpath='{.status.podIP}')
   curl -s -m 10 -w '\n%{http_code}\n' "http://$IP:3501/health/readyz"
   ```

   Never through `https://pilot.ginbov.nl/health/readyz`: `/health/` is registered at the app
   root, outside `/api/`, and the UI's nginx answers every such path with `index.html` and `200`,
   ready backend or not (ElectronicsInventory's `https://parts.ginbov.nl/health/readyz` does today:
   `200`, `text/html`). This pod reaches pod IPs directly.

4. **The secrets.** Four ExternalSecrets, each `SecretSynced` and ready: `pilot-oidc` (from
   `openbao-prd`, `eso/prd/pilot/prd/oidc`) and the generated `pilot-secret-key`,
   `pilot-drain-auth` and `pilot-sse-callback`:

   ```bash
   cexec iac kubectl -n pilot-prd get externalsecrets
   ```

   The Secrets themselves are unreadable here: the running backend (step 3's database connection,
   step 6's sign-in redirect) is what shows they reached it.

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

   The login route builds its redirect from configuration alone, without asking Keycloak (and
   answers `400` without its `redirect` parameter), so the `302` proves the configuration and only
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
