# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: version 1 is being built, and none of it is reachable yet. The record's schema and the
engine behind it are in: the block DSL, the parse gate and the merge by ownership, the record's own
writes, and the rendered `timeline.json`, `reference.json` and `plan.json`
([`docs/engine.md`](docs/engine.md)). So is the sync that keeps the store environment's tree in step
with the record: the `/api/sync` routes and `pilot-sync`, the Go sidecar
([`docs/sync.md`](docs/sync.md)), which production does not switch on yet. No screen serves the
record yet. The rest is the ModernAppTemplate skeleton (Flask on PostgreSQL, React + Vite,
Playwright), which CI builds and Argo CD deploys to production at `https://pilot.ginbov.nl`
([`docs/deployment.md`](docs/deployment.md)).
