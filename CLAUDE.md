# PilotApp

The application behind **Pilot**, the project manager: it owns multi-step work front to end across
the KubeCoder fleet, and the operator decides and does only what their hands must. One append-only
timeline per managed project shows its work, its decision documents and their asks; a side chat
talks to Pilot's brain, a headless Claude Code session in a store environment.

**No screen of Pilot's own exists yet**: the app is the ModernAppTemplate skeleton with the record's
schema, the engine behind it (`backend/app/engine/`) and the sync of the store's tree, live in
production at `https://pilot.ginbov.nl`, where every green build of `main` deploys itself
([`docs/deployment.md`](docs/deployment.md)). Version 1 is built from the design record in
`../PilotAppSpecs/design/` (start at its README), along the steps of its `implementation-plan.md`.
Its `features.md` is the version-1 scope, and
[`docs/change-discipline.md`](docs/change-discipline.md) says how the record binds a change. A
decision it leaves open is the operator's to rule, not something to settle in code. Delivery is
tracked per feature in the record's `feature-ledger.md`, and that is not optional: every slice's doc
phase ticks it ([`docs/slice-doc-plan.md`](docs/slice-doc-plan.md) §6), and an edit to it, to
`features.md` or to the plan's §3 ends with `design/tools/check_ledger.py` green.

## Repo structure

- **Root** — the `run-suite` orchestrator (`tools/suite_runner/`, CI's single entry point), the
  shared `Procfile.dev` dev stack and its `scripts/dev.py` launcher, the `Jenkinsfile`, and the
  `Jenkinsfile.architecture` that publishes the hand-authored model in `docs/architecture/`.
- **`backend/`** — the Flask API (Python, uv), on PostgreSQL.
- **`frontend/`** — the React + Vite SPA (TypeScript, pnpm) with TanStack Router/Query, an
  OpenAPI-generated client, and a Playwright E2E suite that boots the backend per worker.
- **`sidecar/`** — `pilot-sync`, the store environment's sync sidecar (Go), app-owned.

Everything builds through `kc project build|test|lint|setup`, run **from the repo root** — those
verbs are cwd-bound. The toolchain lives in the `modern-app` sidecar, so ad-hoc `uv`/`pnpm`
commands need `cexec modern-app`, and `go` ones `cexec go`. The root and `backend/` are two uv
projects, each with its own `uv.lock`, and both locks are committed, because CI and the image sync
`--locked`. `scripts/dev.py` starts the dev stack and `scripts/dev.py stop` stops it from another
shell. After a backend API change, `scripts/regenerate-openapi.py --frontend` refreshes the
frontend's OpenAPI cache and client; a backend test fails while the committed cache is stale.
`cexec modern-app python3 scripts/check_updates.py` reports the dependencies with a newer release,
major, minor and patch, in every component it finds.

Other repos the work touches, checked out beside this one:

- **`../PilotAppSpecs`**: the spec repo, private: the design record, the decision index
  (`decisions.md`), the decisions taken for now (`considerations.md`) and the slices. A separate git
  repo and a working tree shared by parallel sessions: commit there separately, and stage files by
  name, never `git add -A`.
- **`../PilotDeploy`**: the deploy chart and its per-stage values.
- **`../PilotProjects`**: the store environment's repo, the brain's skills and no data.

## Template ownership

The root, `backend/` and `frontend/` are each generated from a ModernAppTemplate Copier template
(`.copier-answers.yml` in each). Files are either **template-owned** (overwritten by
`copier update`) or **app-owned** (generated once, never overwritten). Never modify a
template-owned file to add app behaviour; use the extension points instead:

| Need | Put it in |
|------|-----------|
| New API endpoints | `backend/app/api/`, registered in `register_blueprints()` in `backend/app/startup.py` |
| New services | `backend/app/services/`, wired in `backend/app/services/container.py` |
| Side effects after a request's commit | `after_commit()` from `backend/app/utils/after_commit.py` |
| CLI commands, post-migration logic | `backend/app/startup.py` |
| Test fixtures | `backend/tests/conftest.py`, `frontend/tests/support/fixtures.ts` |
| Sidecars CI must wait for | `backend/scripts/wait-for-services.py` (the suite runner calls it) |

The template repos are not edited from here: what the template gets wrong is fixed in this repo, in
a commit of its own, and listed here as a standing edit, so that a `copier update` that conflicts on
it resolves to this repo's side. One stands today (D008), an addition rather than a fix: the
`Jenkinsfile`'s sidecar, its `golang` container and its `Test sidecar` and `Build pilot-sync image`
stages, which the template, rendering no `sidecar/`, has no place for. uv, the migration that keeps
the app's loggers, the masked database URL in `backend/app/cli.py` and the declarative `Jenkinsfile`
on the library's `modernApp.test` are the template's own since root v0.2.0 and backend v0.14.0, and
`backend/scripts/init-dev-database.py` (production's locale) since backend v0.15.0.

## Architecture model

PilotApp is a producer in the estate's federated architecture model. Its model is hand-authored in
`docs/architecture/*.yaml`. `Jenkinsfile.architecture`, the job `AaC/PilotApp`, validates it
against the architecture service on every push and archives it for AaC/Architecture to collect;
`kc project lint` validates it too (`arch-validate`, in the `aac-tools` sidecar).

The model is kept current centrally, not from here: the central architecture update in
`pvginkel/Architecture` (`tooling/fleet.py update`) reads the commits since the model last changed
and commits what they change in it. Nothing needs to run here after a change.

`Jenkinsfile.architecture` is the app's own, and `copier update` leaves it alone.

## Working rules

**Commit straight to `main`, small and often**, in this repo and the spec repo alike.

**This repo is public; the spec repo is private.** No secret or token, and no excerpt of a real
project, chat or decision document, goes into a commit here. Test fixtures are invented.

**A change to the plan starts as a proposal**, for as long as version 1 is built. The plan is the
design record in `../PilotAppSpecs/design/`, the implementation plan included, and it is not
updated ad hoc: the change is first written up as a proposal in `design/proposals/`, and
`implementation-plan.md` is updated to say when, at the latest, the proposal is handled — before
the step that would otherwise read the old plan. Handling a proposal means, in order: a pass
under the `kubecoder:data-modelling` skill, if it touches the data model; an arch design
(`/dev:arch-design`), if it raises an architectural question; then absorbing it into the plan,
the feature ledger with it. Once absorbed, the proposal is deleted, and the plan's line naming it
goes with it.

**Every other decision is a row in the spec repo's `decisions.md`**, whose head has the rules: a
ruling made inside a slice's triage, planning or run (the slice's doc phase lands it), one on an
item of `understanding.md` §5, one taken in a session of its own. A decision taken for now goes into
`considerations.md` beside it instead, until the plan's step 15 rules it for good.

## The dev pipeline

Code changes go through the `dev` plugin's slice workflow (`/dev:triage` → `/dev:plan-slice` →
`/dev:run-slice`), which the operator drives. The project's half of that contract is `.aiworkflowrc`
and `.kubecoder/project.yaml`; nothing the pipeline reads by machine belongs in this file.

Issue tracking follows the host convention: this project is **`PilotApp`** on the tracker, key
**`P`**.

## Key documentation

- [`docs/change-discipline.md`](docs/change-discipline.md): the rules every change obeys.
- [`docs/slice-test-plan.md`](docs/slice-test-plan.md): how a slice is verified.
- [`docs/slice-doc-plan.md`](docs/slice-doc-plan.md): which doc surfaces a shipped slice updates.
- [`docs/deployment.md`](docs/deployment.md): how a change reaches production, and what runs there.
- [`docs/sign-in.md`](docs/sign-in.md): who can use Pilot: the `editor` role the API requires, a
  signed-in test's session included.
- [`docs/record.md`](docs/record.md), [`docs/block-dsl.md`](docs/block-dsl.md),
  [`docs/projection.md`](docs/projection.md), [`docs/engine.md`](docs/engine.md): the record's
  schema and the dev seed, the block DSL, the store's tree and its files, and the engine between
  them.
- [`docs/sync.md`](docs/sync.md): the sync protocol and `pilot-sync`, the sidecar that keeps the
  store's tree in step with the record.
