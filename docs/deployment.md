# The deployment

Pilot has one deployment, production, at `https://pilot.ginbov.nl`. There is no dev or staging
instance: what reaches PilotApp's `main` and builds green is what its users run. The chart and its
configuration are in `pvginkel/PilotDeploy`; Argo CD deploys it.

## How a change gets there

A push to PilotApp's `main` starts two Jenkins jobs, each triggered by GitHub's push hook:

- **`PilotApp`** runs the `Jenkinsfile`: the backend and frontend suites through the pipeline
  library's `modernApp.test`, then the images `registry:5000/pilot` (the backend) and
  `registry:5000/pilot-ui` (the UI), each tagged with the build number, then a commit to
  PilotDeploy's `main` that pins both in `config/prd/values.yaml` as `images.pilot` and
  `images.pilotUI` (`:<build number>`). The pin step edits those lines in place and never creates a
  key, so both keys stay in that file. A new build aborts one still running.
- **`AaC/PilotApp`** runs `Jenkinsfile.architecture` (below).

Argo CD's Application `pilot-prd`, registered in `pvginkel/ArgoCDDeploy`'s `releases/values.yaml`,
follows PilotDeploy's `main` and syncs on its own, pruning what the chart no longer renders. A pin
commit therefore rolls the pod: the new pod starts beside the old one, which is retired once the new
one is ready. A PilotDeploy commit that changes the chart or its values deploys the same way.

Until PilotDeploy drops them, the chart still renders the retired SSE gateway: an `sse-gateway`
container, its hand-pinned image `images.sseGateway` and its generated callback secret
`pilot-sse-callback`. Nothing routes to it since the backend serves the SSE stream (backend
template v0.16.0), and they go from PilotDeploy, step 11 of that release's sync in
ModernAppTemplate's `changelog.md`. The rest of this page describes the chart without them.

## What runs

PilotDeploy's chart `pilot`, on the estate's `homelab-shared` library chart, renders into the
namespace `pilot-prd`:

- **Deployment `pilot`**, one pod. Its init container `migrate` applies the database migrations
  (`python -m app.cli upgrade-db`) to completion before the pod's containers start: `backend` (the
  Flask API and the SSE stream, port 3501) and `ui` (the SPA's nginx, port 3500, which proxies
  `/api/` to the backend).
- **Service `pilot`**, port 80 to the UI. Its annotations `nginx.webathome.org/server-name:
  pilot.ginbov.nl` and `nginx.webathome.org/is-public: "true"` have the estate's front door serve it
  as a public site, over HTTPS with a Let's Encrypt certificate. Prometheus scrapes the backend's
  `/metrics` on port 3501.
- The secrets below.

## The database

PostgreSQL on the estate's shared `postgres-pas` cluster. Before every sync, Argo CD's PreSync hook
applies PilotDeploy's `terraform/`, which makes the login role and database `pilot_prd_db` and
writes their connection details into the Secret `pilot-db` (keys `database`, `username`,
`password`). `migrate` and `backend` compose `DATABASE_URL` from it, against the pooler at
`postgres-pooler-rw.postgres-pas-prd.svc.cluster.local`. Nothing about the database is made by hand.

## Secrets

PilotApp and PilotDeploy are public repositories, so no secret is committed to either.

- **The Keycloak client's id and secret** are the operator's to write, to OpenBao at
  `eso/prd/pilot/prd/oidc` (`client_id`, `client_secret`). The ExternalSecret `pilot-oidc` brings
  them into the namespace through the `openbao-prd` store.
- **Flask's `SECRET_KEY` and the drain endpoint's `DRAIN_AUTH_KEY`** are generated in the
  cluster, once, by External Secrets `Password` generators, into the Secrets `pilot-secret-key` and
  `pilot-drain-auth`.
- **The database password** is Terraform's (above).

A secret a later feature needs comes the same way: a value from outside the cluster is an OpenBao
leaf the operator writes, read through `externalSecrets` in `config/prd/values.yaml`; one nothing
outside the pod reads is a generator.

## Sign-in

Keycloak at `https://auth.ginbov.nl`, realm `homelab`, client `pilot-app`. Who gets in is in
[`sign-in.md`](sign-in.md).

## The architecture model

Two producers publish Pilot into the estate's architecture model, both registered in
`pvginkel/Architecture`'s `pipeline-producers.yaml`:

- **`pilot-app`** is this repo's hand-authored `docs/architecture/architecture.yaml`: the products
  `app:pilot` and `app:pilot-ui`, the services they expose and what the backend consumes. `kc
  project lint` validates it; `AaC/PilotApp` validates and archives it on every push to `main`. A
  change to what the app exposes or consumes updates it.
- **`pilot-deploy`** is generated from PilotDeploy's chart by `AaC/PilotDeploy`, on every push to
  PilotDeploy's `main`, pin commits included, with the judgment layer in PilotDeploy's
  `architecture.yaml`. PilotDeploy's `kc project test` reads this repo's model, so it needs PilotApp
  checked out beside it.

`AaC/Architecture` collects the model after every green build of either job.

## Checking it

[`slice-test-plan.md`](slice-test-plan.md) §3 and §4: the order of the pushes, following the
builds and the roll, and the checks against the running app.
