"""A refusal of a view's state (F154.2), built here alone so that the screen
and a tool read one text: every fault at once, each with its part as
written, what is wrong, the nearest names and what is allowed there, and at
its end a correct example of each kind of part refused
(`tools/cost-dashboard/brain-tools.md` §3.5). The texts are a contract: the
suite pins them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.exceptions import StateRefusedException

NEAREST = 3
"""The most names "Did you mean" offers."""

MOST_EDITS = 3
"""The most edits a near name is away, whatever the word's length."""


@dataclass(frozen=True)
class Fault:
    """One fault of a state: `part` as written, `kind` the part's key, which
    picks the example the refusal ends on; `wrong` and `allowed` sentences
    without their full stop."""

    part: str
    kind: str
    wrong: str
    nearest: tuple[str, ...] = ()
    allowed: str | None = None

    def line(self) -> str:
        text = f"- {self.part}: {self.wrong}."
        if self.nearest:
            text += f" Did you mean {listed(quoted(self.nearest), 'or')}?"
        if self.allowed:
            text += f" {self.allowed}."
        return text


FORMS: dict[str, tuple[str, str, str]] = {
    "part": (
        "A state",
        "<part>=<value>&…, its parts t, by, p, m, dr, c, b, col, o, d, sel, "
        "ig, it, call, f, rel, mk, dw, roll, lit, ev and z",
        "t=qw&by=project&m=cost.sum",
    ),
    "t": (
        "A time",
        "t=<range>, t=wk,<week's key>,… or t=c,<from>,<to>",
        "t=qw or t=c,2026-11-01,2026-11-07",
    ),
    "by": ("A By", "by=<dimension>", "by=project"),
    "p": (
        "A presentation",
        "p=order[,<order dimension>], p=time,<grain>, p=lanes or p=table",
        "p=time,day",
    ),
    "m": (
        "A measure",
        "m=<figure>.<aggregate>[.<grain>][(<filter>;…)], m=r:<ratio> or "
        "m=r:<name>:<measure>/<measure>",
        "m=cost.median.conversation or m=cost.sum(miss=1)",
    ),
    "dr": (
        "A drill level",
        "dr=<part>:<value>@<dimension it was drilled from>",
        "dr=project:<id>@project",
    ),
    "c": (
        "A chip",
        "c=[~][!]<dimension>:<value>,…, c=[~]@rows,<op>,<number>,<measure>, "
        "c=[~][!]@items,<op>,<number>,<measure> or c=[~]@outliers",
        "c=miss:1 or c=@items,gt,1,cost.sum",
    ),
    "col": ("A color", "col=<dimension>, col=token_kind or col=none", "col=model"),
    "o": ("A sort", "o=<asc|desc>,<column>", "o=desc,cost.sum"),
    "d": ("The drawer", "d=items", "d=items"),
    "sel": ("A selected row", "sel=<a value of the By>", "sel=~"),
    "ig": ("The items' grain", "ig=<grain>", "ig=conversation"),
    "it": ("An item", "it=<grain>,<its key>", "it=conversation,<id>"),
    "call": (
        "A selected call",
        "call=<call>, with it=conversation,<id>",
        "it=conversation,<id>&call=<call>",
    ),
    "f": ("A focus", "f=<dimension>:<key>", "f=project:<id>"),
    "rel": ("Relative", "rel=1", "rel=1"),
    "mk": ("A list of markers", "mk=<kind>,… or mk=none", "mk=none"),
    "dw": (
        "A series' drawing",
        "dw=<part>:<value>,…, its parts dots:all|out|none, cols:off, med:off "
        "and band:off",
        "dw=dots:out,band:off",
    ),
    "roll": (
        "The band's length",
        "roll=<items it reads>,<items before it draws>",
        "roll=5,5",
    ),
    "lit": ("A list of values lit", "lit=<value of the color>,…", "lit=~"),
    "ev": ("A list of event kinds", "ev=[-]<event kind>,…", "ev=-cache_miss"),
    "z": ("A window", "z=<from>,<to>, in epoch seconds", "z=1763600000,1763686400"),
}
"""Each kind of part: its name, its form and a correct example of it."""


def refused(faults: Sequence[Fault]) -> StateRefusedException:
    """The refusal of a state with `faults`, in the order they stand."""
    return StateRefusedException(refusal(faults), tuple(faults))


def refusal(faults: Sequence[Fault]) -> str:
    """The refusal's text: every fault, each on a line, then a correct
    example of each kind of part refused."""
    count = len(faults)
    head = (
        "Cannot read the view because its state has "
        f"{count} fault{'' if count == 1 else 's'}."
    )
    kinds = [kind for kind in FORMS if any(fault.kind == kind for fault in faults)]
    examples = [
        f"{FORMS[kind][0]} reads {FORMS[kind][1]}, as in {FORMS[kind][2]}."
        for kind in kinds
    ]
    return "\n".join([head, *(fault.line() for fault in faults), *examples])


def listed(words: Sequence[str], last: str = "and") -> str:
    """`a`, `a and b`, `a, b and c`."""
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} {last} {words[-1]}"


def quoted(words: Iterable[str]) -> list[str]:
    return [f'"{word}"' for word in words]


def distance(one: str, other: str) -> int:
    """The edits from one to the other, a swap of two neighbouring letters
    counting as one (the optimal string alignment distance)."""
    rows = [list(range(len(other) + 1))]
    for i, mine in enumerate(one, start=1):
        row = [i]
        for j, theirs in enumerate(other, start=1):
            cost = mine != theirs
            best = min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + cost)
            if i > 1 and j > 1 and mine == other[j - 2] and one[i - 2] == theirs:
                best = min(best, rows[-2][j - 2] + 1)
            row.append(best)
        rows.append(row)
    return rows[-1][-1]


def nearest(written: str, names: Iterable[str]) -> tuple[str, ...]:
    """The names nearest the one written, at most `NEAREST`, nearest first
    and then in their own order, its case aside: those a third of its length
    away or nearer, one edit at least and `MOST_EDITS` at most, and fewer
    edits than the longer of the two has letters."""
    allowed = min(MOST_EDITS, max(1, len(written) // 3))
    found = []
    for place, name in enumerate(dict.fromkeys(names)):
        edits = distance(written.lower(), name.lower())
        if edits <= allowed and edits < max(len(written), len(name)):
            found.append((edits, place, name))
    return tuple(name for _, _, name in sorted(found)[:NEAREST])
