# Slice documentation plan

Which documentation surfaces a shipped slice brings up to date, and the rules for each. This is the
doc `.aiworkflowrc` names as `doc_phase.plan`: the run loop's doc phase is "read this and execute
it", working from the whole slice's merged diff.

Work the diff, not a checklist. A surface below is owed an update only when the slice's changes
actually reached it.

## The surfaces

### 1. `docs/`

Small topic docs, one subject each. The design record in `../PilotAppSpecs/design/` is the input
the application is built from, not its documentation: as slices build what it describes, the design
*as built* lands in topic docs here (the record and its schema, the block DSL, the MCP tools, the
sidecar protocol, the server's jobs, the deployment), and a topic doc never points a reader at the
design record for how something works. This repo is public and the spec repo is not, so a doc here
has to stand on its own.

The change discipline, this plan and the slice testing strategy live here too. A slice that changes
what they describe (a service that is now runnable, a live check that is now written, a deployment
that now exists) updates them.

### 2. The design record

A slice that changes a ruling, settles an item on `understanding.md` §5's open list, or delivers
something `features.md` names differently from how it is written there, updates the design record
in `../PilotAppSpecs/design/`: the ruling into `understanding.md` or `feed-model.md`, the open item
off §5, `features.md` brought in line. Only what the operator ruled goes in; a divergence nobody
ruled on is named in the close-out report instead.

### 3. `README.md`

The public face: what Pilot is, its shape and its status. A slice that changes any of those three
(above all the status line, and later how to run or deploy it) keeps it true.

### 4. `CLAUDE.md`

Loaded every turn by every agent the pipeline spawns, so it stays at about one screen and states
each fact once. When a new standing rule belongs there, something else moves out to a `docs/` topic
doc so that the file does not grow. Nothing the pipeline reads by machine goes in it; that is
`.aiworkflowrc`'s job.

### 5. Consumers in other repos

The brain's skills live in `pvginkel/PilotProjects`, the deploy chart in `pvginkel/PilotDeploy`,
and the dev workflow Pilot drives in the AIWorkflow repo. This phase edits none of them. A slice
that changed a surface they depend on, or anything a deployment has to follow, names it in the
close-out report so the operator can file the change against its owner.

## What "up to date" means here

**State the design as it is**, as implemented, not as the slice planned it. Where the
implementation diverged from the plan or from the design record, the doc describes what shipped,
and the close-out report names the divergence. No changelog entries, no "as of slice NNN", no
tombstones for superseded conventions: rewrite the doc instead, per
[`change-discipline.md`](change-discipline.md).

**Ground every claim in the shipped source.** A doc sentence that cannot be checked against the
merged tree does not go in.

**Nothing private goes in.** No excerpt of a real project, chat, transcript or decision document,
and no secret: examples are invented.

## Gates

```bash
kc project build      # unchanged and green: the doc phase must not have moved code
```

Check that relative links resolve. Then commit. If the design record or the slice's own folder in
`../PilotAppSpecs` needs anything, commit there separately: it is a separate git repo, and a working
tree shared by parallel sessions, so stage files by name.

## When there is little to do

A slice that changed no design, no convention and no reader-facing surface owes nothing here, and
saying so plainly is the correct outcome. Do not invent doc work to fill the phase.
