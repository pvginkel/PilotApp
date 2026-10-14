# Change discipline

The rules every code change in this repo obeys. This is the doc `.aiworkflowrc` names as
`design_philosophy`: it is handed to every `code-writer`, `code-reviewer`, `plan-writer` and
`plan-reviewer` the pipeline dispatches, and it is what a reviewer cites when sending work back.

The design is not here. It is the design record in the spec repo, `../PilotAppSpecs/design/`, which
is private; start at its README. As the code that builds it lands, the design as built goes into
topic docs beside this one.

## The design record is binding

- **`features.md` is the version-1 scope.** Once the operator signs it off, version 1 is built from
  that list without coming back for scope. A feature that is not on it, or one it lists under
  *Decided out*, is not built, and neither is the groundwork for one because it looked cheap while
  passing: it is a question for the operator.
- **The rulings are decisions, not suggestions**: `understanding.md` §2, `feed-model.md`,
  `tech-design-options.md` §7 and `ui-conventions.md`. A plan or an implementation that disagrees
  with one is wrong, however convenient.
- **An open item is the operator's to rule.** `understanding.md` §5 is the one open list. A slice
  that meets one of its items stops and asks; it does not settle the question in code.

## The mockup is the screens

The React app is the mockup in `../PilotAppSpecs/design/mockup/`, converted: its layout, its
controls and its styling carry over as they are, and `ui-conventions.md` holds the rulings on what
shows and what a control does. No styling rule is written down anywhere else; where the mockup and
a habit of this template disagree, the mockup wins.

## The server decides when; the brain decides what

The judgment, which is how to route a finding, what counts as impact and where work runs, is the
brain's: a headless Claude Code session in the store environment, whose skills live in
`pvginkel/PilotProjects`. The server's own jobs are deterministic: the record, ingest and
projection, the turn and response streams, waits firing, push checks, the resume recipe, the block
DSL's parser and renderer, and starting environments on demand. A change that moves judgment into
the server is the wrong change, however convenient.

## PostgreSQL is the one record

Everything Pilot owns, the content of every document included, lives in PostgreSQL. The store
environment's tree of Markdown and JSON files is a projection of the record, kept live in both
directions by the sync sidecar, and is disposable: deleting it must cost a re-materialisation and
nothing else. No data lives in Git, and no state that matters lives only in a process's memory. The
engine (parsing, ownership, splicing, the projection, the sidecar protocol) is a module of the
server, not a separate app; only the sidecar is Go.

Ids are minted by the server: an item's and an attachment's are GUIDs, and a block's is composed
from its item's id and its local id. Every surface addresses by them.

## The surfaces are contracts

Pilot's MCP tools, the sidecar protocol and the REST endpoints are what other code is written
against: the brain's skills in `pvginkel/PilotProjects`, the sessions Pilot injects its tools into,
the Go sidecar and the UI. A running session keeps the tool definitions it loaded when it started.
So a change to any of them is deliberate:

- A test pins each surface, so a change to it is a visible diff in the slice that makes it, never a
  side effect.
- A slice that changes a surface says so in its close-out report, because what depends on it lives
  in another repo and has to follow.

Behind the surfaces, internal interfaces change cleanly: change the code and fix the callers, with
no shim, adapter or compatibility parameter.

## The template is generated code

The root, `backend/` and `frontend/` are generated from ModernAppTemplate; `CLAUDE.md` says which
files are the template's and where app code goes instead. App behaviour never goes into a
template-owned file. The template family itself is not edited from here: what it gets wrong is fixed
in this repo, in its own commit that says so, so that a `copier update` merges it knowingly.

## No tombstones

Delete replaced code completely: no "moved to X" comments, forwarding stubs, deprecated aliases,
commented-out blocks or helpers kept in case they come back. The same holds for prose: when a
convention changes, rewrite the doc rather than appending a note that the old rule no longer holds.

## Validate at the boundary, nowhere else

No `try`/`except` that swallows an error, no silent fallback, no retry or cache without an observed
failure to point at, and no guard for a condition the types already rule out.

The boundaries are where checking is the feature: tool and endpoint input, a document the brain or a
worker session wrote (the block DSL and its front matter, the ownership of an `answer:` line), and
what the sidecar reports. An error in what an agent wrote is answered to that agent, so it can fix
it; an input validated at the boundary is not checked again further in.

## Testability is critical

Every change ships with a test. A feature without one is incomplete, and "verified by hand" is no
substitute: the point of a test is that it runs again next time.

`kc project test` is hermetic. It reaches no KubeCoder controller, no Claude session, no YouTrack
and no GitHub: the server's jobs are tested against a fake controller and a fake sidecar, the block
DSL as a pure library, and the UI through the Playwright suite against the backend it boots per
worker. It is green from any environment with no credentials. Checks that need the real fleet belong
to the test phase ([`slice-test-plan.md`](slice-test-plan.md)), not to the suite.

## Public code, private specs

This repo is public; the spec repo is not. No secret or token, and no excerpt of a real project,
chat, transcript or decision document, goes into a commit here: the mockup replays real projects,
and its data stays in the spec repo. Test fixtures and examples are invented.
