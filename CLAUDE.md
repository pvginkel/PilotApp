# PilotApp

The application behind **Pilot**, the project manager: it owns multi-step work front to end across
the KubeCoder fleet, and the operator decides and does only what their hands must. One append-only
timeline per managed project shows its work, its decision documents and their asks; a side chat
talks to Pilot's brain, a headless Claude Code session in a store environment.

**Its first screens are in**: the handle step, the project list, a project's head and its timeline,
its work items, its documents in the overlay and the side panel, on the record's schema, the engine
behind it (`backend/app/engine/`), the sync of the store's tree, the server's jobs on the KubeCoder
controller, Pilot's MCP server with the worker's round trip, the project's chat in the side panel,
with the brain's tools, a new project: the plus, its definition chat and draft, Create project and
its setup, Pilot's jobs after a worker's turn and an item of its own done, the pass's claims and its
questions to the writer, the switch's dialog and the archive question, and the phone's
notifications through the bridge, a project's and the alarms, with the profile's token and switch,
and the usage limits: the halts, the overrule, the halt file, the hard stop, the nudge and each
turn's tokens.
Every green build of
`main` deploys itself to the dev stage at `https://pilot-dev.home`, and production at
`https://pilot.ginbov.nl` runs what the operator promotes from there
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
- **`backend/`** — the Flask API (Python, uv), on PostgreSQL; `pilot_mcp/`, Pilot's MCP server,
  the image's second entry point (`python -m pilot_mcp`); and `packages/pilot-dsl/`, the block DSL,
  a package the backend takes by path and PilotProjects pins from git
  ([`docs/block-dsl.md`](docs/block-dsl.md)).
- **`frontend/`** — the React + Vite SPA (TypeScript, pnpm) with TanStack Router/Query, an
  OpenAPI-generated client, and a Playwright E2E suite that boots the backend per worker.
- **`sidecar/`** — `pilot-sync`, the store environment's sync sidecar (Go), app-owned.

Everything builds through `kc project build|test|lint|setup`, run **from the repo root** — those
verbs are cwd-bound. The toolchain lives in the `modern-app` sidecar, so ad-hoc `uv`/`pnpm`
commands need `cexec modern-app`, and `go` ones `cexec go`. The root and `backend/` are two uv
projects, each with its own `uv.lock`, and both locks are committed, because CI and the image sync
`--locked`. `scripts/dev.py` starts the dev stack and `scripts/dev.py stop` stops it from another
shell. After a backend API change, `scripts/regenerate-openapi.py --frontend` refreshes the
OpenAPI cache, the backend's file in `backend/openapi-cache/` that the frontend reads through the
symlink `frontend/openapi-cache`, and the client; a backend test fails while the committed cache is stale.
`cexec modern-app python3 scripts/check_updates.py` reports the dependencies with a newer release,
major, minor and patch, in every component it finds.

Other repos the work touches, checked out beside this one:

- **`../PilotAppSpecs`**: the spec repo, private: the design record, the decision index
  (`decisions.md`), the decisions taken for now (`considerations.md`) and the slices. A separate git
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
| Test fixtures | `backend/tests/conftest.py`, `frontend/tests/support/fixtures.ts` |
| Sidecars CI must wait for | `backend/scripts/wait-for-services.py` (the suite runner calls it) |
| Vite plugins | `loadAppPlugins()` in `frontend/vite-plugin-extensions.ts` |
| Settings of the Playwright backends | `loadAppBackendEnv()` in `frontend/tests/support/backend-env-extensions.ts` |

Template-owned code is improved in this repo, not in the template repos (D018): what the template
gets wrong, or does less well than the work needs, is changed here, with no need to stay backwards
compatible, in a commit of its own, and listed here as a standing edit, so that a `copier update`
that conflicts on it resolves to this repo's side; an agent merges it into ModernAppTemplate.
Eleven stand today: the `Jenkinsfile`, the app's own as a whole, which tags its images `dev-<n>` and
`dev-latest` and pins `dev-<n>` into PilotDeploy's `config/dev` and `prd-<n>` into its `config/prd`
in one commit, where the template's tags `<n>` and `latest` and pins production alone, and which
carries the sidecar's `golang` container and its `Test sidecar` and `Build pilot-sync image` stages,
which the template, rendering no `sidecar/`, has no place for (D008), and which copies the
backend's OpenAPI cache into the `pilot-ui` build context, where `frontend/openapi-cache` is a
symlink to `backend/openapi-cache`; the page head of
`frontend/index.html`, which links the PWA's `/manifest.json`, sets `theme-color`, and gives the
viewport `interactive-widget=resizes-content`, so that a phone's keyboard shrinks the app rather
than panning it, which no app-owned file can; the cache rule of `frontend/nginx.conf`, which keeps the year-long immutable
cache to the build's hashed `/assets/` and has the root's files — the icons, the logo, the manifest,
the worker — revalidated on every load, so that a changed icon shows under its name; the `/api/`
location of `frontend/nginx.conf`, a `^~` prefix, so that nginx tries no regex location on an
`/api/` path, where the template's plain prefix let the cache rule's regex answer an `/api/` path
ending in `.js` or `.png`, and this repo's `.json`, from the static root
(`tests/infrastructure/nginx.spec.ts` pins it); the Playwright dev servers' dependency caches,
one per server: `frontend/tests/support/process/servers.ts` gives each its own `VITE_CACHE_DIR`,
`node_modules/.tmp/vite-playwright/<port>`, removed when it stops, and `frontend/vite.config.ts`
reads it as `cacheDir`, where the template's `scripts/testing-server.sh` set a variable nothing
read, so that its servers shared `node_modules/.vite` and swapped its `deps/` under each other's
first pages on a cold start (`tests/infrastructure/dev-server.spec.ts` pins it); the app's Vite
plugins, which `frontend/vite.config.ts` appends from `loadAppPlugins()` in the app-owned
`frontend/vite-plugin-extensions.ts`, as it merges the proxies of `vite-proxy-extensions.ts`, where
the template gives an app no place for a plugin; the Playwright backends' own settings, which
`frontend/tests/support/process/servers.ts` merges over the template's from `loadAppBackendEnv()`
in the app-owned `frontend/tests/support/backend-env-extensions.ts`, given the backend's URL, where
the template gives an app no place for a backend setting under Playwright: this app's points each
backend's controller at the fake it serves itself, and its chats at a store environment in that
fake, and its notification bridge at the bridge's fake it serves too; `run-suite`'s Playwright worker count,
which `tools/suite_runner/local.py` reads from `PLAYWRIGHT_WORKERS` when no `--workers` is given,
where the library's `modernApp.test` fixes run-suite's flags and so left CI on the Playwright
config's count; the completion of `useSSETask` in `frontend/src/hooks/use-sse-task.ts`, which
takes a `task_completed` as the task's result unless the result says it failed, with `success` false
or an `error_message`, where the template's took one without `success: true` as failed, and so
failed every task whose result is a plain model, as the backend's `TaskService` sends one; the
app's height, `h-dvh` on the root layout of `frontend/src/routes/__root.tsx` and on the auth gate's
screens in `frontend/src/components/auth/auth-gate.tsx`, where the template's `h-screen`, `100vh`,
which a phone's Chrome measures with its URL bar hidden, cut off the app's foot by the bar's
height, the app scrolling inside itself so that the bar never hides; and the
docstring of `scoped_session` in `backend/app/database.py`, which says that a nested call on the
same thread hands back the outer session and commits and closes it, where the template's warns only
of a request's session. uv, the migration that keeps the app's loggers,
the masked database URL in `backend/app/cli.py` and the declarative `Jenkinsfile` on the library's
`modernApp.test` are the template's own since root v0.2.0 and backend v0.14.0, and
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
item of `understanding.md` §5, one taken in a session of its own. A decision taken for now goes into
`considerations.md` beside it instead, until the plan's step 15 rules it for good.

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
- [`docs/deployment.md`](docs/deployment.md): the dev and prd stages, how a change reaches each,
  and what runs there.
- [`docs/sign-in.md`](docs/sign-in.md): who can use Pilot: the `editor` role the API requires, a
  signed-in test's session included, and the person on the record, with the handle they choose.
- [`docs/ui.md`](docs/ui.md), [`docs/projects.md`](docs/projects.md),
  [`docs/timeline.md`](docs/timeline.md), [`docs/documents.md`](docs/documents.md): the UI's shell,
  tokens, shared pieces and links in text; the projects' API and screens, the plus and Create
  project; the timeline's API, live event and screens; a document read alone, a draft's asks, the
  attachments, the overlay and the side panel with a draft's Draft tab.
- [`docs/record.md`](docs/record.md), [`docs/block-dsl.md`](docs/block-dsl.md),
  [`docs/projection.md`](docs/projection.md), [`docs/engine.md`](docs/engine.md): the record's
  schema and the dev seed, the block DSL, the store's tree and its files, and the engine between
  them.
- [`docs/sync.md`](docs/sync.md): the sync protocol and `pilot-sync`, the sidecar that keeps the
  store's tree in step with the record, and its write lock, through which each save is a session's.
- [`docs/jobs.md`](docs/jobs.md), [`docs/controller.md`](docs/controller.md),
  [`docs/sessions.md`](docs/sessions.md), [`docs/work.md`](docs/work.md): the supervisor that runs
  the server's long-lived jobs; the KubeCoder controller's client, its outage, its fleet stream,
  environments on demand and Pilot's own, with its fake; the sessions, the gate, its slot and the
  jobs' queue, their records, relay and live stream, Stop, Resume and Retry; a work item's status,
  its line and its session log, and Pilot's own work: its jobs, their briefs, Retry.
- [`docs/mcp.md`](docs/mcp.md), [`docs/round-trip.md`](docs/round-trip.md),
  [`docs/chats.md`](docs/chats.md): Pilot's MCP server, handed to every session it creates, the
  worker's tools and the brain's; a registered document's read at the run's end, a claimed action,
  the clarification run, its write-back and the run's continuation; a project's chat and a draft's
  definition chat, its start in the store, its brief, its Stop, its close, `chat.md`, and its Chat
  tab, composer, Discuss and *In the chat*.
- [`docs/notifications.md`](docs/notifications.md): the phone's notifications through the bridge, a
  project's per member and the alarms per condition, their reconcile and retry, the profile's
  token and alarms switch, and the bridge's fake.
- [`docs/usage.md`](docs/usage.md): the usage limits: the reading, the week's and the five-hour
  halts and their settings, the overrule, the halt file, the hard stop, a run halted at its turn's
  end, the nudge, the quota wall, and each turn's tokens and cost.
