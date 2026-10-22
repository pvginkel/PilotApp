# The deployment

Pilot has two stages, each an Argo CD Application on the prd cluster, registered in
`pvginkel/ArgoCDDeploy`'s `releases/values.yaml`, that renders the chart in `pvginkel/PilotDeploy`
with the stage's `config/<stage>/`:

- **dev**, `pilot-dev`, at `https://pilot-dev.home`, internal. Every green build of PilotApp's
  `main` deploys it, with no hand step. Its sessions and environments are `kubecoder-dev`'s, a
  KubeCoder with a fleet of its own, never the operator's.
- **prd**, `pilot-prd`, production, at `https://pilot.ginbov.nl`. It moves only when the operator
  promotes a commit, by starting the Jenkins job `PilotApp/Promote-PRD` by hand.

The chart is the same; what differs is each Application and its values (`<n>` is a PilotApp build
number):

| | dev | prd |
|---|---|---|
| Application and namespace | `pilot-dev` | `pilot-prd` |
| Follows PilotDeploy's | `main` | `prd` |
| Site | `https://pilot-dev.home`, internal | `https://pilot.ginbov.nl`, public |
| Images | `:dev-<n>` | `:prd-<n>` |
| `STAGE` | `dev` | `prd` |
| The record's testing endpoints ([`projects.md`](projects.md)) | answer a signed-in editor | refused, `400` |
| KubeCoder | `https://kubecoder-dev.home` | `https://kubecoder.home` |
| OpenBao leaves | `eso/prd/pilot/dev/{oidc,kubecoder}` | `eso/prd/pilot/prd/{oidc,kubecoder}` |
| Database | `pilot_dev_db` | `pilot_prd_db` |

## How a change gets to dev

A push to PilotApp's `main` starts two Jenkins jobs, each triggered by GitHub's push hook:

- **`PilotApp/Build-Main`** runs the `Jenkinsfile`: the backend and frontend suites through the
  pipeline library's `modernApp.test`, then `Test sidecar`, `go vet` and `go test -race` of
  `sidecar/` in a `golang` container on the image this environment's `go` tool runs. Then the
  images `registry:5000/pilot` (the backend), `registry:5000/pilot-ui` (the UI) and
  `registry:5000/pilot-sync` (the store's sync sidecar), each tagged `dev-<n>` and `dev-latest`,
  `<n>` the build number. Last, one commit to PilotDeploy's `main` pins the first two for both
  stages, as `images.pilot` and `images.pilotUI`: `:dev-<n>` in `config/dev/values.yaml` and
  `:prd-<n>` in `config/prd/values.yaml`, tags that exist only once a promotion has made them
  (below). The pin step edits those lines in place and never creates a key, so the four keys stay
  in their files. A new build aborts one still running.
- **`AaC/PilotApp`** runs `Jenkinsfile.architecture` (below).

The build job and the promotion job (below) sit together in the Jenkins folder `PilotApp`, named
as KubeCoder's pair is, `KubeCoder/Build-Main` and `KubeCoder/Promote-PRD` (D022).

`pilot-dev` follows PilotDeploy's `main` and syncs on its own, pruning what the chart no longer
renders, so a pin commit rolls dev's pod (below). A PilotDeploy commit to `main` that changes the
chart or the values deploys to dev the same way, and reaches production only when a promotion
carries it.

## How a change gets to production

`pilot-prd` follows PilotDeploy's `prd` branch, which nothing moves but `PilotApp/Promote-PRD`. The
job has no trigger: the operator starts it whenever dev holds what they want in production. It
runs PilotDeploy's `Jenkinsfile.promote`, with one parameter, `commit`: the commit on PilotDeploy's
`main` to promote, its tip when empty. Its steps run in order, each only once the one before it
succeeded, so `prd` never pins a tag that does not exist:

1. **Retag.** The commit's `config/prd/values.yaml` pins `pilot` and `pilot-ui` to `:prd-<n>`, both
   of one build, or the job refuses. `pilot`, `pilot-ui` and `pilot-sync` of that build are tagged
   `prd-<n>` in `registry:5000` from its `dev-<n>`. A `prd-<n>` an earlier promotion made is left as
   it is.
2. **Advance `prd`.** `prd` fast-forwards to the commit, in a push with no force, which is refused
   unless it fast-forwards. `pilot-prd` syncs it and rolls its pod (below).
3. **Tag the release.** An annotated tag `release-<m>`, `<m>` the job's build number, goes on the
   commit, its message naming the three images.

Production therefore runs only commits of `main`, which dev follows, and images retagged from a
build's `dev-<n>`. A re-run for the commit `prd` already names finishes a promotion whose tag
failed, or changes nothing when a release tag records it. A run with `commit` empty that would move
`prd` refuses while no release tag records `prd`'s tip, so a stuck promotion is never passed over;
the one tip it admits unrecorded is the commit `prd` was created at by hand before the first
promotion, whose `config/prd` pins bare build numbers. A second run waits for the first: an abort
between its pushes would leave a promotion half made.

**A rollback is a revert on PilotDeploy's `main`, promoted** like any other commit: the job has no
rollback parameter and never moves `prd` backwards. The revert of a pin commit pins the build
before it again, which the promotion retags unless an earlier one already has, and rolls dev back
first, as every commit on `main` does. The next green PilotApp build pins its own images over the
revert. A revert cannot take production back past its first promotion: the commit before it pins
bare build numbers, which the job refuses.

## The roll

A sync that changes the pod starts the new pod beside the old one (`RollingUpdate`, `maxSurge: 1`,
`maxUnavailable: 0`), which is retired once the new one is ready.

The old pod's containers go on serving for 15 s once its termination starts, while the Service
drops it from its endpoints. Then the backend's preStop calls `/health/drain`, waiting 40 s at
most, and the drain stops the server's jobs within `GRACEFUL_SHUTDOWN_TIMEOUT`, which the chart
sets to 20 s. Nothing drains to completion: every job resumes from its rows on the new pod, and the
two pods' overlap is safe, each job's writes being conditional on rows it reads under their lock
([`jobs.md`](jobs.md)).
`terminationGracePeriodSeconds` is 70 (15 + 40 + 15), so the old pod is gone within 70 s.

## What runs

PilotDeploy's chart `pilot`, on the estate's `homelab-shared` library chart, renders the same
objects into each stage's namespace:

- **Deployment `pilot`**, one pod. Its init container `migrate` applies the database migrations
  (`python -m app.cli upgrade-db`) to completion before the pod's containers start: `backend` (the
  Flask API and the SSE stream, port 3501) and `ui` (the SPA's nginx, port 3500, which proxies
  `/api/` to the backend). `migrate` and `backend` run with the stage's `STAGE` and with
  `HOMELAB_INTERNAL` true in both stages.
  The backend serves the store's sync routes, `/api/sync/` ([`sync.md`](sync.md)), and refuses
  every call to them: the chart sets neither `SYNC_TOKEN` nor `STORE_ENVIRONMENT_ID`, and either
  one empty refuses all (D007).
  The backend's link settings ([`ui.md`](ui.md)) come from `links` in the values:
  `ticketUrlTemplate` as `TICKET_URL_TEMPLATE` and `environmentLinkBaseUrl` as
  `ENVIRONMENT_LINK_BASE_URL`, each left unset where the values say nothing. Both stages' ticket
  links are `https://issues.webathome.org/issue/{id}`; each stage's environment links open through
  its own KubeCoder (the table above). The ticket id pattern is the app's default.
  The backend reaches its stage's KubeCoder controller ([`controller.md`](controller.md)) at
  `controller.url` in the values, as `CONTROLLER_URL`, with `CONTROLLER_TOKEN` from the Secret
  `pilot-kubecoder`. Its `CONTROLLER_CA_FILE` is the homelab root CA, against which both
  controllers' certificates verify and which the image does not trust: the chart renders
  `chart/files/homelab-root.crt` into the ConfigMap `homelab-root-ca` and mounts it read-only at
  `/etc/ssl/homelab`. `migrate` sets none of the three. The backend refuses to start without the
  URL and the token; with them it holds the controller's fleet stream open and keeps the
  Environment rows current. Neither stage starts, sends to or stops an environment: no route
  outside testing mode starts a session ([`sessions.md`](sessions.md)), and the shutdown timer
  stops only an environment Pilot started.
- **Service `pilot`**, port 80 to the UI, its annotation `nginx.webathome.org/server-name` the
  stage's host. Production's `nginx.webathome.org/is-public: "true"` has the estate's front door
  serve it as a public site, over HTTPS with a Let's Encrypt certificate. Dev's `is-public: "false"`
  and `enable-ssl: "yes"` have the front door serve `pilot-dev.home` as an internal site, over HTTPS
  with a certificate from the homelab step-ca (D023), and the homelab DNS publish the name, with no
  hand step. Prometheus scrapes the backend's `/metrics` on port 3501.
- The secrets below.

`pilot-sync`, the third image, is built for the store environment's pod, which KubeCoder composes
from its catalog; nothing PilotDeploy renders runs it, and nothing pins it (D007). Each build tags
it `dev-<n>` and `dev-latest`, and a promotion tags it `prd-<n>` with the two pinned images.

## The database

PostgreSQL on the estate's shared `postgres-pas` cluster, one database per stage. Before every sync,
Argo CD's PreSync hook applies PilotDeploy's `terraform/` with the stage's
`config/<stage>/terraform.tfvars` and `rotation.tfvars`, in a Terraform state of the stage's own. It
makes the login role and database named after the namespace, `pilot_dev_db` or `pilot_prd_db`, and
writes their connection details into the namespace's Secret `pilot-db` (keys `database`,
`username`, `password`). `migrate` and `backend` compose `DATABASE_URL` from it, against the pooler
at `postgres-pooler-rw.postgres-pas-prd.svc.cluster.local`. Nothing about the database is made by
hand.

Production's state also owns PilotDeploy's GitHub webhook, which delivers the repository's pushes
to Argo CD (`terraform/webhook.tf`): the webhook is one per repository, so `manage_webhook` is true
in `config/prd/terraform.tfvars` alone.

## Secrets

PilotApp and PilotDeploy are public repositories, so no secret is committed to either. Each stage
reads its own OpenBao leaves, under `eso/prd/pilot/<stage>/`, through the `openbao-prd` store.

- **The Keycloak client's id and secret** are the operator's to write, to the stage's `oidc` leaf
  (`client_id`, `client_secret`). The ExternalSecret `pilot-oidc` brings them into the namespace.
- **The KubeCoder controller's token**, Pilot's named client credential on the stage's KubeCoder,
  is the operator's to write, to the stage's `kubecoder` leaf (`token`): production's is for
  `https://kubecoder.home`, dev's for `https://kubecoder-dev.home`. The ExternalSecret
  `pilot-kubecoder` brings it into the namespace.
- **Flask's `SECRET_KEY` and the drain endpoint's `DRAIN_AUTH_KEY`** are generated in each
  namespace, once, by External Secrets `Password` generators, into the Secrets `pilot-secret-key`
  and `pilot-drain-auth`.
- **The database password** is Terraform's (above).

A secret a later feature needs comes the same way: a value from outside the cluster is an OpenBao
leaf per stage that the operator writes, read through `externalSecrets` in each
`config/<stage>/values.yaml`; one nothing outside the pod reads is a generator.

## Sign-in

Keycloak at `https://auth.ginbov.nl`, realm `homelab`. Production's client is `pilot-app`; dev has
a client of its own in the same realm, which registers `https://pilot-dev.home/*` as a redirect URI
and `https://pilot-dev.home` as a web origin, and whose `editor` role is granted apart from
production's. Who gets in is in [`sign-in.md`](sign-in.md). The test phase signs in on dev as a
test account that holds dev's `editor` role alone; its credentials are catalog secrets, in no
commit ([`slice-test-plan.md`](slice-test-plan.md)).

## The architecture model

Three producers publish Pilot into the estate's architecture model, all registered in
`pvginkel/Architecture`'s `pipeline-producers.yaml`:

- **`pilot-app`** is this repo's hand-authored `docs/architecture/architecture.yaml`: the products
  `app:pilot` and `app:pilot-ui`, the services they expose and what the backend consumes. `kc
  project lint` validates it; `AaC/PilotApp` validates and archives it on every push to `main`. A
  change to what the app exposes or consumes updates it. Both products carry `logo: pilot`, the
  Pilot mark from the Architecture repo's logo library, which the model stamps onto every instance,
  service and interface behind them.
- **`pilot-deploy`** is production's, generated from PilotDeploy's chart with `config/prd/` by
  `AaC/PilotDeploy`, with the judgment layer in PilotDeploy's `architecture.yaml`. The job builds
  PilotDeploy's `prd`, so it runs on every promotion that moves `prd`, and a change on `main` to
  the judgment layer or `Jenkinsfile.architecture` publishes once a promotion carries it.
- **`pilot-dev-deploy`** is the dev stage's, generated the same way with `config/dev/` by
  `AaC/PilotDeployDev`, which runs PilotDeploy's `Jenkinsfile.architecture-dev` on `main`, so every
  pin commit republishes it.

Both stages are published (D025), each as a producer of its own, as Keycloak's two are: a pipeline
publishes one stage, from the branch Argo CD syncs it from. The judgment layer is the stages' one
file, and marks each stage's host a web UI, `pilot.ginbov.nl` and `pilot-dev.home`, so the Home
launcher shows Pilot as two tiles under the Pilot mark, one tagged PRD and one DEV. PilotDeploy's
`kc project test` generates both and reads this repo's model, so it needs PilotApp checked out
beside it.

`AaC/Architecture` collects the model after every green build of any of the three jobs.

## Checking it

[`slice-test-plan.md`](slice-test-plan.md): the order of the pushes, following a build into
`pilot-dev`, and the checks against the running app there. Nothing checks production after a
promotion.
