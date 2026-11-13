"""The path glob of the tree's file search (F150.5), KubeCoder's `find_files`
syntax, its automaton ported from KubeCoder's controller.

`*` matches any characters but `/`, `**` any characters including `/` (`**/`
any whole directories, none included), `?` one character but `/`, and `{a,b}`
either alternative, with `*`, `**` and `?` working inside and no nesting. Any
other glob syntax, a `[...]` class, a `\\` escape, a nested or unbalanced
brace, is a `GlobSyntaxError` naming it, never a pattern that matches nothing.
"""

from dataclasses import dataclass, field

SUPPORTED = "supported: *, **, ?, {a,b}"

# Edge kinds: one literal character, any character but `/`, any character.
_LITERAL = 0
_NOT_SLASH = 1
_ANY = 2


class GlobSyntaxError(ValueError):
    """The pattern uses glob syntax the search does not support; the message
    names it and where."""


def _unsupported(what: str, char: str, index: int) -> GlobSyntaxError:
    return GlobSyntaxError(
        f"Invalid glob pattern: {what} '{char}' at index {index} is not supported"
        f" ({SUPPORTED})"
    )


@dataclass
class _Builder:
    edges: list[list[tuple[int, str, int]]] = field(default_factory=list)
    eps: list[list[int]] = field(default_factory=list)

    def state(self) -> int:
        self.edges.append([])
        self.eps.append([])
        return len(self.edges) - 1

    def edge(self, src: int, kind: int, char: str = "") -> int:
        dst = self.state()
        self.edges[src].append((kind, char, dst))
        return dst

    def loop(self, src: int, kind: int) -> int:
        """A state looping on `kind` entered from `src` without input: zero or
        more."""
        state = self.state()
        self.eps[src].append(state)
        self.edges[state].append((kind, "", state))
        return state


class PathGlob:
    """A compiled pattern, a nondeterministic automaton read a character at a
    time. `advance` memoizes on its state sets, so matching many paths with
    few distinct prefixes stays linear in the characters read."""

    def __init__(self, pattern: str) -> None:
        """
        Raises:
            GlobSyntaxError: the pattern uses syntax that is not supported.
        """
        self.pattern = pattern
        builder = _Builder()
        start = builder.state()
        self._accept = self._compile(pattern, builder, start)
        self._edges = builder.edges
        self._eps = builder.eps
        self._steps: dict[tuple[frozenset[int], str], frozenset[int]] = {}
        self._start = self._closure([start])

    def matches(self, path: str) -> bool:
        """Whether the pattern matches `path` whole."""
        return self._accept in self._advance(self._start, path)

    def _advance(self, states: frozenset[int], text: str) -> frozenset[int]:
        """The state set after reading `text` from `states`; empty once no
        match can follow."""
        for char in text:
            if not states:
                break
            key = (states, char)
            nxt = self._steps.get(key)
            if nxt is None:
                nxt = self._closure(
                    [
                        dst
                        for src in states
                        for kind, literal, dst in self._edges[src]
                        if kind == _ANY
                        or (kind == _NOT_SLASH and char != "/")
                        or (kind == _LITERAL and char == literal)
                    ]
                )
                self._steps[key] = nxt
            states = nxt
        return states

    def _closure(self, states: list[int]) -> frozenset[int]:
        seen = set(states)
        todo = list(states)
        while todo:
            for nxt in self._eps[todo.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return frozenset(seen)

    @staticmethod
    def _compile(pattern: str, builder: _Builder, start: int) -> int:
        """Build the automaton for `pattern` from `start`; return its accept
        state."""
        current = start
        # Inside a brace group: where it opened, the state it branches from,
        # and each closed alternative's end state, joined to the group's exit
        # at the closing brace.
        brace_at = -1
        branch_from = start
        branch_ends: list[int] = []
        i = 0
        while i < len(pattern):
            char = pattern[i]
            if char in "[]":
                raise _unsupported("character class", char, i)
            if char == "\\":
                raise _unsupported("backslash escape", char, i)
            if char == "{":
                if brace_at >= 0:
                    raise _unsupported("nested braces", char, i)
                brace_at, branch_from, branch_ends = i, current, []
                current = builder.state()
                builder.eps[branch_from].append(current)
            elif char == "}":
                if brace_at < 0:
                    raise _unsupported("unbalanced", char, i)
                branch_ends.append(current)
                current = builder.state()
                for end in branch_ends:
                    builder.eps[end].append(current)
                brace_at = -1
            elif char == "," and brace_at >= 0:
                branch_ends.append(current)
                current = builder.state()
                builder.eps[branch_from].append(current)
            elif char == "*" and pattern.startswith("**", i):
                if pattern.startswith("**/", i):
                    # `(.*/)?`: zero or more whole directories.
                    exit_ = builder.state()
                    builder.eps[current].append(exit_)
                    inner = builder.loop(current, _ANY)
                    builder.edges[inner].append((_LITERAL, "/", exit_))
                    current = exit_
                    i += 3
                    continue
                current = builder.loop(current, _ANY)
                i += 2
                continue
            elif char == "*":
                current = builder.loop(current, _NOT_SLASH)
            elif char == "?":
                current = builder.edge(current, _NOT_SLASH)
            else:
                current = builder.edge(current, _LITERAL, char)
            i += 1
        if brace_at >= 0:
            raise _unsupported("unbalanced", "{", brace_at)
        return current
