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

### 2. The decisions and the design record

A decision the operator ruled in the slice's triage, planning or run, an item of
`understanding.md` §5's open list settled among them, is a row in `../PilotAppSpecs/decisions.md`,
per the rules at its head: its text in the topic doc here that describes what the slice built, the
row pointing there, and a passage of the design record it overrules marked `(→ DNNN)`. A pending
row the slice built moves the same way, its text out of *Pending decisions*. **Take the id by
reading `decisions.md` at append time**, never from a number the plan or the slice folder names:
the spec repo is one working tree shared by parallel sessions, and a duplicate id is not
self-correcting. A doc here cites a decision by its bare id, with no link, and states what it rules
in its own words.

Beyond those markers and a correction, the design record changes through a proposal, not here. What
this pass owes it besides is the settled item off §5, and `features.md` brought in line where the
slice delivers something it names differently. Only what the operator ruled goes in; a divergence
nobody ruled on is named in the close-out report instead. A correction (D015, `CLAUDE.md`) this pass
makes itself only where it is a plain error — a wrong citation, a stale cross-reference, a typo; a
passage the build departed from is such a divergence, and the operator's word on it in the close-out
corrects it.

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

### 6. The feature ledger

`../PilotAppSpecs/design/feature-ledger.md` is where the delivery of every feature in `features.md`
stands: a row per feature and sub-feature, the slices of `implementation-plan.md` §3 that build it,
its status. **Every slice owes this surface**, whatever else it changed. From the diff and the
slice's acceptance criteria, for each row that names the slice: shipped in full and this was its
last slice, `delivered <date>`; shipped, with other slices still to come, `partial`. A feature the
slice planned but did not ship is never left `planned` under a closed slice and never ticked: take
it out of the slice's Features cell in §3 (`(not …)`), set the row `unplanned`, and say in its note
which slice left it out and that the close-out report names it, so the close-out session can place
or drop it. `python3 ../PilotAppSpecs/design/tools/check_ledger.py` lists what is owed and what
disagrees; it is a gate below.

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
python3 ../PilotAppSpecs/design/tools/check_ledger.py   # 0 errors but the rows this slice ticked: the feature ledger agrees with the record
```

The ledger check counts a slice as shipped once its folder is in `slices/completed/`, where the
run moves it when the slice completes, after this phase. Until then, its only errors are the rows
the slice ticked, each saying that the slice has not shipped.

Check that relative links resolve. Then commit. If the design record or the slice's own folder in
`../PilotAppSpecs` needs anything, commit there separately: it is a separate git repo, and a working
tree shared by parallel sessions, so stage files by name.

## When there is little to do

A slice that changed no design, no convention and no reader-facing surface owes nothing here but
the feature ledger, and saying so plainly is the correct outcome. Do not invent doc work to fill
the phase.
