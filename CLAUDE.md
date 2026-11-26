# PilotApp

The application behind **Pilot**, the project manager: it owns multi-step work front to end across
the KubeCoder fleet, and the operator decides and does only what their hands must. One append-only
timeline per managed project shows its work, its decision documents and their asks; a side chat
talks to Pilot's brain, a headless Claude Code session in a store environment.

Every green build of `main` deploys itself to the dev stage at `https://pilot-dev.home`, and
production at `https://pilot.ginbov.nl` runs what the operator promotes from there
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
  shared `Procfile.dev` dev stack and its `scripts/dev.py` launcher, the `Jenkinsfile`, the
  `Jenkinsfile.architecture` that publishes the hand-authored model in `docs/architecture/`, and
  the `.dockerignore` of the collector's image, the one built with the root as its context.
- **`backend/`** — the Flask API (Python, uv), on PostgreSQL; `pilot_mcp/`, Pilot's MCP server,
  the image's second entry point (`python -m pilot_mcp`); `packages/pilot-dsl/`, the block DSL,
  a package the backend takes by path and PilotProjects pins from git
  ([`docs/block-dsl.md`](docs/block-dsl.md)); `packages/pilot-scenario/`, the invented scenario
  and its builder, taken by path too ([`docs/collection.md`](docs/collection.md)); and
  `packages/pilot-collection/`, the publication's, the inventory's and the reading's shapes, which
  the collector takes by path as well.
- **`collector/`** — the collector (Python, uv), app-owned, the image `pilot-collector`: it walks a
  fleet's home, publishes its transcripts to the backend and serves their readings
  ([`docs/collector.md`](docs/collector.md)); its walk's proof against the backend runs in the
  backend's suite, `backend/tests/collector/`.
- **`frontend/`** — the React + Vite SPA (TypeScript, pnpm) with TanStack Router/Query, an
  OpenAPI-generated client, and a Playwright E2E suite that boots the backend per worker.
- **`sidecar/`** — `pilot-sync`, the store environment's sync sidecar (Go), app-owned.

Everything builds through `kc project build|test|lint|setup`, run **from the repo root** — those
verbs are cwd-bound. The toolchain lives in the `modern-app` sidecar, so ad-hoc `uv`/`pnpm`
commands need `cexec modern-app`, and `go` ones `cexec go`. The root, `backend/` and `collector/`
are three uv projects, each with its own `uv.lock`, and every lock is committed, because CI and the
images sync `--locked`; the backend's lock names the collector's dependencies too, so a dependency
the collector gains is locked in both. `scripts/dev.py` starts the dev stack and `scripts/dev.py stop` stops it from another
shell. After a backend API change, `scripts/regenerate-openapi.py --frontend` refreshes the
OpenAPI cache, the backend's file in `backend/openapi-cache/` that the frontend reads through the
symlink `frontend/openapi-cache`, and the client; a backend test fails while the committed cache is stale.
`cexec modern-app python3 scripts/check_updates.py` reports the dependencies with a newer release,
major, minor and patch, in every component it finds.

Other repos the work touches, checked out beside this one:

- **`../PilotAppSpecs`**: the spec repo, private: the design record, the decision index
  (`decisions.md`) and the slices. A separate git
  repo and a working tree shared by parallel sessions: commit there separately, and stage files by
  name, never `git add -A`.
- **`../PilotDeploy`**: the deploy chart and its per-stage values.
- **`../PilotProjects`**: the store environment's repo: the brain's map, skills and scripts, and no
  data.
- **`../AIWorkflow`**: the `dev` plugin marketplace, the AI workflow Pilot drives, re-envisioned
  for Pilot running it by the plan's stage 5 (P-111) and on its `main` since 0.10. A change there
  keeps that repo's own `CLAUDE.md`: a plugin version and a changelog entry with every change, and
  a running loop takes it only once pushed and the plugin updated. Its spec repo is `../AIWorkflowSpecs`, a shared tree as this one's is.
- **`../KubeCoderConfig`**: the `kubecoder` plugin marketplace, the host conventions the `dev`
  plugin's skills load; every change bumps its plugin version.

## Template ownership

The root, `backend/` and `frontend/` are each generated from a ModernAppTemplate Copier template
(`.copier-answers.yml` in each). Files are either **template-owned** (overwritten by
`copier update`) or **app-owned** (generated once, never overwritten). Never modify a
template-owned file to add app behaviour; use the extension points instead:

| Need | Put it in |
|------|-----------|
| New API endpoints | `backend/app/api/`, registered in `register_blueprints()` in `backend/app/startup.py` |
| New services | `backend/app/services/`, wired in `backend/app/services/container.py` |
| New screens | a route under `frontend/src/routes/_shell/`; tokens in `frontend/src/styles/app-theme.css` ([`docs/ui.md`](docs/ui.md)) |
| Side effects after a request's commit | `after_commit()` from `backend/app/utils/after_commit.py` |
| CLI commands, post-migration logic | `backend/app/startup.py` |
| Listeners on the app's engine | `configure_engine()` in `backend/app/startup.py` |
| Test fixtures | `backend/tests/conftest.py`, `frontend/tests/support/fixtures.ts` |
| Sidecars CI must wait for | `backend/scripts/wait-for-services.py` (the suite runner calls it) |
| Vite plugins | `loadAppPlugins()` in `frontend/vite-plugin-extensions.ts` |
| Settings of the Playwright backends | `loadAppBackendEnv()` in `frontend/tests/support/backend-env-extensions.ts` |
| Steps of the Playwright run's setup | `loadAppGlobalSetup()` in `frontend/tests/support/global-setup-extensions.ts` |

Template-owned code is improved in this repo, not in the template repos (D018): where the template
gets something wrong, or does less well than the work needs, the file is changed here, with no need
to stay backwards compatible, in a commit of its own that says why. Nothing tracks those edits, in
this file or any other (D283). The sync with ModernAppTemplate has an agent read every
template-owned file against the template at the version `.copier-answers.yml` names, and `git log`
and `git diff` on the file give the why; that is also how a `copier update` that conflicts on one
is resolved.

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

**A correction is not a change to the plan** (D015). An edit after which no later slice would be
built or planned differently — a wrong citation, a stale cross-reference, a typo, a passage that
describes a part already built otherwise than it was built — is made in the design record directly,
committed with a message that says what it corrects, with no proposal and no row. A plain error
anyone corrects; a passage the build departed from without a ruling is corrected on the operator's
word, which a close-out report asks for. A standing page states its rule and never a live
snapshot — a count of what is open, "none since <date>" — and a clause of that kind, met anywhere
in the record, is dropped as a correction, never refreshed. In doubt, it is a proposal.

**Every other decision is a row in the spec repo's `decisions.md`**, whose head has the rules: a
ruling made inside a slice's triage, planning or run (the slice's doc phase lands it), one on an
item of `understanding.md` §5, one taken in a session of its own.

## The dev pipeline

Code changes go through the `dev` plugin's slice workflow. A slice is filed by `/dev:triage`, the
operator's own chat skill, or in Pilot by a project's definition chat; its planning,
`/dev:plan-slice`, and its run, `/dev:run-slice`, are stages Pilot runs as work items, each putting
its asks to the operator as documents in the app (the plugin's `docs/pilot.md`). The project's half
of that contract is `.aiworkflowrc` and `.kubecoder/project.yaml`; nothing the pipeline reads by
machine belongs in this file. A finding against the workflow itself — a loop's read-back, a
document the plugin writes, a skill's wording — is a card in `AIWF`, the workflow's own project,
never a P card or a Pilot slice, and is worked from a session started in `../AIWorkflow`.

Issue tracking follows the host convention: this project is **`PilotApp`** on the tracker, key
**`P`**.

## Key documentation

- [`docs/change-discipline.md`](docs/change-discipline.md): the rules every change obeys.
- [`docs/slice-test-plan.md`](docs/slice-test-plan.md): how a slice is verified.
- [`docs/slice-doc-plan.md`](docs/slice-doc-plan.md): which doc surfaces a shipped slice updates.
- [`docs/deployment.md`](docs/deployment.md): the dev and prd stages and how a change reaches each.
- [`docs/sign-in.md`](docs/sign-in.md): who can use Pilot and how they sign in.
- [`docs/ui.md`](docs/ui.md): the UI's shell, tokens, motion and shared pieces.
- [`docs/projects.md`](docs/projects.md): the projects, their list, head and screens.
- [`docs/timeline.md`](docs/timeline.md): a project's timeline.
- [`docs/documents.md`](docs/documents.md): a project's documents, its tabs and the side panel.
- [`docs/record.md`](docs/record.md): the record's schema and the dev seed.
- [`docs/block-dsl.md`](docs/block-dsl.md): the block DSL.
- [`docs/projection.md`](docs/projection.md): the store's tree and its files.
- [`docs/engine.md`](docs/engine.md): the engine between the record and the store's tree.
- [`docs/sync.md`](docs/sync.md): the sync protocol and `pilot-sync`, the store's sidecar.
- [`docs/collection.md`](docs/collection.md): the transcripts a collector publishes.
- [`docs/collector.md`](docs/collector.md): the collector.
- [`docs/jobs.md`](docs/jobs.md): the supervisor of the server's long-lived jobs.
- [`docs/controller.md`](docs/controller.md): the KubeCoder controller's client and its fake.
- [`docs/sessions.md`](docs/sessions.md): the sessions Pilot runs and the gate they pass.
- [`docs/work.md`](docs/work.md): the work items and Pilot's own work.
- [`docs/mcp.md`](docs/mcp.md): Pilot's MCP server and its projects surface.
- [`docs/round-trip.md`](docs/round-trip.md): a registered document's round trip.
- [`docs/chats.md`](docs/chats.md): a project's chat and a draft's definition chat.
- [`docs/conversations.md`](docs/conversations.md): a conversation with Pilot from outside it.
- [`docs/notifications.md`](docs/notifications.md): the notifications through web push.
- [`docs/usage.md`](docs/usage.md): the usage limits and each turn's tokens and cost.
- [`docs/store-update.md`](docs/store-update.md): the store's update.
- [`docs/dashboard.md`](docs/dashboard.md): the dashboard's query engine.
- [`docs/waits.md`](docs/waits.md): the brain's card and timed waits.
