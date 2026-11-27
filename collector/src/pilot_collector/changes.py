"""What a tool call changed of a Repository (F152.11, F158.4; P-348, P-349):
the commits a Bash command made, read off its command and its output, and
the lines a successful Edit or Write changed of its file.

**A command** is read as the shell reads it, so far as it is words: its
simple commands in order, each its words with their quotes and escapes
taken, a here-document's body the input of the command that names it, and a
comment none of it. A word holding an expansion the shell makes, a variable
or a command's output, is one the collector does not know, and so is the
body of a here-document whose delimiter is not quoted where it holds one; a
command substitution that is a `cat` of a here-document alone is that body,
as `git commit -m "$(cat <<'EOF' … EOF)"` gives a message.

- **A `git commit`** among them is a commit the command makes, in the
  directory a `-C` of its `git` names, else the one the last `cd` before it
  went to, each from the directory before it; else the call's working
  directory. A `cd` to a word the collector does not know, or to none,
  leaves the directory unknown.
- **Its subject** is its message's, as git's `%s` gives it: the first
  paragraph, past the blank lines that open it, its lines cut of their
  trailing white space and joined by a space. The message is the first `-m`
  or `--message`, or with `-F -` the here-document the command names; none
  where it is a file's, another commit's, or a word the collector does not
  know.
- **A `git log`** and **a `git rev-parse`** are read for the hash a commit
  before them in the command made: the log in a directory as a commit's is.

**What the output shows.** Git prints a commit it made as its own line, the
branch and the hash in brackets before the subject; a command run quiet
prints none. A commit takes the first such line of its subject, one of
unknown subject the first whose subject no commit of the command names, and
from it its subject where the command did not give one. Where the command
makes one commit and no line shows it: the hash Claude Code records of the
call, where that is a hash; else, where a `git rev-parse` follows it, the
last line of the output that is a hash alone. A `git log`'s line is the hash
and the subject, `%h %s`, its refs between them where it names them.

**An edit's lines** (`dispatch-work.md` §5): an Edit whose result carries
the patch counts the patch's `+` and `-` lines; one with no result object a
line diff of its old and new text. A Write of a new file counts its
content's lines as added; one over a file the patch's lines, and with no
result object its content's lines as added and none removed.
"""

import difflib
import posixpath
import re
from dataclasses import dataclass
from typing import Any

EDIT = "Edit"
WRITE = "Write"

_HASH = re.compile(r"[0-9a-f]{7,64}")
"""A commit's hash as git prints it, whole or abbreviated to its shortest,
seven characters: Claude Code's record of a quiet commit can hold a number
in its place."""

_MADE = re.compile(r"^\[[^\]\n]* ([0-9a-f]{7,64})\] (.*)$", re.MULTILINE)
"""The line git prints of a commit it made: `[<branch> <hash>] <subject>`,
the branch `detached HEAD` or followed by `(root-commit)`."""

_LOGGED = re.compile(r"^([0-9a-f]{7,64}) (.*)$", re.MULTILINE)
"""A line of `git log --oneline`: the hash, and the subject, the refs that
name it before it where the log decorates."""

_BARE = re.compile(r"^[0-9a-f]{7,64}$", re.MULTILINE)
"""A line that is a hash alone, as `git rev-parse` prints one."""

_OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
"""What ends a simple command, the longest first; a newline does too."""

_RESERVED = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "time"}
)
"""The shell's words that open a simple command before its own."""

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
"""A variable a simple command sets for itself, before its own words."""

_VARIABLE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|.)?")
"""A variable's expansion, by its name or a special one's character."""

_EXPANDED = ("$", "`", "\\")
"""What the shell expands in a here-document whose delimiter is not
quoted."""

_VALUED = frozenset(
    {
        "--author",
        "--date",
        "--cleanup",
        "--trailer",
        "--template",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--pathspec-from-file",
    }
)
"""The long options of `git commit` that take a value as their next word."""

_REUSED = frozenset({"--reuse-message", "--reedit-message", "--fixup", "--squash"})
"""The options that take a commit's message from another commit."""

_SHORT_VALUED = "mFCct"
"""The short options of `git commit` that take a value: the rest of their
word, else the next."""


@dataclass
class _Simple:
    """A simple command: its words, none for one the collector does not
    know, and the body of the first here-document it names."""

    words: list[str | None]
    stdin: str | None = None
    quoted: bool = True
    """Whether that here-document's delimiter was quoted, which keeps its
    body as written."""

    @property
    def given(self) -> str | None:
        """Its input as the shell gives it: none where it is no
        here-document's, or one the shell expands."""
        stdin = self.stdin
        if stdin is None or self.quoted:
            return stdin
        return None if any(each in stdin for each in _EXPANDED) else stdin


@dataclass(frozen=True)
class Making:
    """A commit a command makes: the directory it runs in, none where the
    collector does not know it, its subject, none where the command does not
    give it, and its simple command's place in the command."""

    directory: str | None
    subject: str | None
    place: int


@dataclass(frozen=True)
class Command:
    """What a Bash command says of the commits it makes and of where their
    hashes show."""

    makings: tuple[Making, ...] = ()
    logs: tuple[tuple[int, str | None], ...] = ()
    """Each `git log`'s place in the command and its directory."""
    parses: tuple[int, ...] = ()
    """Each `git rev-parse`'s place in the command."""


@dataclass(frozen=True)
class Made:
    """A commit a call made: its directory, its subject, and its hash where
    its own line, Claude Code's record or a `git rev-parse` shows it."""

    directory: str
    subject: str
    sha: str | None
    place: int


class _Words:
    """A command's text read into its simple commands, from `start`; a
    command substitution's up to the parenthesis that closes it."""

    def __init__(self, text: str, start: int = 0, nested: bool = False) -> None:
        self.text = text
        self.at = start
        self.nested = nested
        self.commands: list[_Simple] = []
        self._current = _Simple([])
        self._documents: list[tuple[_Simple, str, bool, bool]] = []
        """The here-documents named on the line being read, whose bodies
        follow it: the command each is the input of, its delimiter, whether
        its body's lines are cut of their leading tabs and whether the
        delimiter was quoted."""
        self._depth = 0
        self._read()

    def _read(self) -> None:
        text = self.text
        while self.at < len(text):
            char = text[self.at]
            if char in " \t":
                self.at += 1
            elif text.startswith("\\\n", self.at):
                self.at += 2
            elif char == "\n":
                self.at += 1
                self._ended()
                self._bodies()
            elif char == "#":
                ended = text.find("\n", self.at)
                self.at = len(text) if ended < 0 else ended
            elif text.startswith("<<", self.at) and not text.startswith("<<<", self.at):
                self._document()
            elif char in "<>":
                self._redirected()
            elif self.nested and char == ")" and not self._depth:
                self.at += 1
                self._ended()
                return
            elif (operator := _operator(text, self.at)) is not None:
                self.at += len(operator)
                self._depth += (operator == "(") - (operator == ")")
                self._ended()
            else:
                self._current.words.append(self._word())
        self._ended()

    def _ended(self) -> None:
        if self._current.words:
            self.commands.append(self._current)
        self._current = _Simple([])

    def _document(self) -> None:
        """A here-document's redirection: its body follows the line."""
        self.at += 2
        strip = self.text.startswith("-", self.at)
        self.at += strip
        while self.text.startswith((" ", "\t"), self.at):
            self.at += 1
        begun = self.at
        delimiter = self._word()
        quoted = any(char in "'\"\\" for char in self.text[begun : self.at])
        if delimiter is not None:
            self._documents.append((self._current, delimiter, strip, quoted))

    def _redirected(self) -> None:
        """A redirection, from its `<` or `>`: its target is no word of the
        command's."""
        while self.text.startswith(("<", ">", "&"), self.at):
            self.at += 1
        while self.text.startswith((" ", "\t"), self.at):
            self.at += 1
        if self.at < len(self.text) and self.text[self.at] != "\n":
            if _operator(self.text, self.at) is None:
                self._word()

    def _bodies(self) -> None:
        """The bodies of the here-documents the line named, in order."""
        for command, delimiter, strip, quoted in self._documents:
            lines: list[str] = []
            while self.at < len(self.text):
                ended = self.text.find("\n", self.at)
                ended = len(self.text) if ended < 0 else ended
                line = self.text[self.at : ended]
                self.at = ended + 1
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break
                lines.append(line.lstrip("\t") if strip else line)
            if command.stdin is None:
                command.stdin = "".join(f"{line}\n" for line in lines)
                command.quoted = quoted
        self._documents = []

    def _word(self) -> str | None:
        """The word that starts here, none where it holds an expansion."""
        text = self.text
        parts: list[str] = []
        known = True
        while self.at < len(text):
            char = text[self.at]
            if char in " \t\n<>" or _operator(text, self.at) is not None:
                break
            if self.nested and char == ")":
                break
            if char == "'":
                ended = text.find("'", self.at + 1)
                ended = len(text) if ended < 0 else ended
                parts.append(text[self.at + 1 : ended])
                self.at = ended + 1
            elif char == '"':
                said = self._quoted()
                known = known and said is not None
                parts.append(said or "")
            elif char == "\\":
                if text.startswith("\\\n", self.at):
                    self.at += 2
                    continue
                parts.append(text[self.at + 1 : self.at + 2])
                self.at += 2
            elif char == "$" or char == "`":
                self._expansion()
                known = False
            else:
                parts.append(char)
                self.at += 1
        return "".join(parts) if known else None

    def _quoted(self) -> str | None:
        """A double-quoted string, from its opening quote: none where it
        holds an expansion other than a here-document's `cat`."""
        text = self.text
        self.at += 1
        parts: list[str] = []
        known = True
        while self.at < len(text) and text[self.at] != '"':
            char = text[self.at]
            if char == "\\" and text[self.at + 1 : self.at + 2] in (
                '"',
                "\\",
                "$",
                "`",
            ):
                parts.append(text[self.at + 1])
                self.at += 2
            elif text.startswith("\\\n", self.at):
                self.at += 2
            elif text.startswith("$(", self.at) and not text.startswith("$((", self.at):
                said = self._substituted()
                known = known and said is not None
                parts.append(said or "")
            elif char == "$" or char == "`":
                self._expansion()
                known = False
            else:
                parts.append(char)
                self.at += 1
        self.at += 1
        return "".join(parts) if known else None

    def _substituted(self) -> str | None:
        """A command substitution, from its `$(`: what it gives where it is a
        `cat` of a here-document, the shell cutting the newlines that end it;
        none for any other."""
        inner = _Words(self.text, self.at + 2, nested=True)
        self.at = inner.at
        (command, *others) = inner.commands or [_Simple([])]
        given = command.given
        if others or command.words != ["cat"] or given is None:
            return None
        return given.rstrip("\n")

    def _expansion(self) -> None:
        """Pass an expansion, from its `$` or backquote."""
        text = self.text
        if text.startswith("$(", self.at):
            inner = _Words(text, self.at + 2, nested=True)
            self.at = inner.at
        elif text.startswith("${", self.at):
            ended = text.find("}", self.at)
            self.at = len(text) if ended < 0 else ended + 1
        elif text[self.at] == "`":
            ended = text.find("`", self.at + 1)
            self.at = len(text) if ended < 0 else ended + 1
        elif text.startswith("$'", self.at):
            ended = text.find("'", self.at + 2)
            self.at = len(text) if ended < 0 else ended + 1
        else:
            named = _VARIABLE.match(text, self.at)
            self.at = self.at + 1 if named is None else named.end()


def _operator(text: str, at: int) -> str | None:
    """The operator that starts at `at`, none where none does."""
    return next((each for each in _OPERATORS if text.startswith(each, at)), None)


def _moved(directory: str | None, to: str | None) -> str | None:
    """The directory a path names from `directory`: none where the path is
    none or a home's, or is relative to a directory the collector does not
    know."""
    if to is None or to in ("", "-") or to.startswith("~"):
        return None
    if not posixpath.isabs(to):
        if directory is None:
            return None
        to = posixpath.join(directory, to)
    return posixpath.normpath(to)


def subject(message: str) -> str | None:
    """A message's subject, as git's `%s` gives it: none where it has
    none."""
    lines = [line.rstrip() for line in message.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    paragraph: list[str] = []
    for line in lines:
        if not line:
            break
        paragraph.append(line)
    return " ".join(paragraph) or None


def _message(arguments: list[str | None], stdin: str | None) -> str | None:
    """The message a `git commit` of those arguments is given, none where
    the collector does not know it."""
    messages: list[str | None] = []
    filed: str | None = None
    reused = False
    place = 0
    while place < len(arguments):
        word = arguments[place]
        place += 1
        if word is None or not word.startswith("-") or word == "-":
            continue
        if word == "--":
            break
        if word.startswith("--"):
            name, given, attached = word.partition("=")
            value: str | None = attached
            if not given and name in ("--message", "--file", *_VALUED):
                value = (arguments[place : place + 1] or [None])[0]
                place += 1
            if name == "--message":
                messages.append(value)
            elif name == "--file":
                filed = value
            reused = reused or name in _REUSED
            continue
        for at, letter in enumerate(word[1:], start=2):
            if letter not in _SHORT_VALUED:
                continue
            value = word[at:] or None
            if value is None:
                value = (arguments[place : place + 1] or [None])[0]
                place += 1
            if letter == "m":
                messages.append(value)
            elif letter == "F":
                filed = value
            reused = reused or letter in "Cc"
            break
    if messages:
        return messages[0]
    if filed == "-" and not reused:
        return stdin
    return None


def command(text: str, directory: str | None) -> Command:
    """What a Bash command of that text, run in `directory`, says of the
    commits it makes."""
    makings: list[Making] = []
    logs: list[tuple[int, str | None]] = []
    parses: list[int] = []
    here = directory
    for place, simple in enumerate(_Words(text).commands):
        words = simple.words
        while (
            words
            and words[0] is not None
            and (words[0] in _RESERVED or _ASSIGNMENT.match(words[0]))
        ):
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd":
            here = _moved(here, words[1] if len(words) > 1 else None)
            continue
        if words[0] != "git":
            continue
        at, runs = 1, here
        while at < len(words) and (words[at] or "").startswith("-"):
            if words[at] in ("-C", "-c"):
                if words[at] == "-C":
                    runs = _moved(runs, words[at + 1] if at + 1 < len(words) else None)
                at += 1
            at += 1
        named = words[at] if at < len(words) else None
        if named == "commit":
            message = _message(words[at + 1 :], simple.given)
            makings.append(
                Making(runs, None if message is None else subject(message), place)
            )
        elif named == "log":
            logs.append((place, runs))
        elif named == "rev-parse":
            parses.append(place)
    return Command(tuple(makings), tuple(logs), tuple(parses))


def _recorded(record: Any) -> str | None:
    """The hash Claude Code records of a commit the call made, where it
    records one that is a hash."""
    operation = record.get("gitOperation") if isinstance(record, dict) else None
    committed = operation.get("commit") if isinstance(operation, dict) else None
    sha = committed.get("sha") if isinstance(committed, dict) else None
    return sha if isinstance(sha, str) and _HASH.fullmatch(sha) else None


def made(read: Command, output: str, record: Any) -> list[Made]:
    """The commits a call made, as its command says them and its output and
    Claude Code's record show them: those whose directory and subject are
    known."""
    shown = [(named[1], named[2]) for named in _MADE.finditer(output)]
    taken = [False] * len(shown)
    known = {making.subject for making in read.makings if making.subject}
    commits: list[Made] = []
    for making in read.makings:
        sha, said = None, making.subject
        for place, (hashed, subjected) in enumerate(shown):
            if taken[place]:
                continue
            if (subjected == said) if said else (subjected not in known):
                taken[place] = True
                sha, said = hashed, said or subjected
                break
        if sha is None and len(read.makings) == 1:
            sha = _recorded(record)
            if sha is None and any(place > making.place for place in read.parses):
                bare = _BARE.findall(output)
                sha = bare[-1] if bare else None
        if making.directory is not None and said:
            commits.append(Made(making.directory, said, sha, making.place))
    return commits


def logged(output: str) -> list[tuple[str, str]]:
    """Each line of the output that reads as a `git log --oneline`'s: its
    hash and what follows it, in the output's order."""
    return [(named[1], named[2]) for named in _LOGGED.finditer(output)]


def names(line: str, subject: str) -> bool:
    """Whether what follows a log line's hash is that subject, past the
    refs a decorated log names before it."""
    return line == subject or (line.startswith("(") and line.endswith(f") {subject}"))


def _counted(text: str) -> int:
    """The lines of a text, a last one with no newline among them."""
    return text.count("\n") + (not text.endswith("\n")) if text else 0


def _split(text: str) -> list[str]:
    """A text's lines, each without its newline."""
    lines = text.split("\n")
    return lines[:-1] if text.endswith("\n") else lines


def _patched(patch: list[dict[str, Any]]) -> tuple[int, int]:
    """The `+` and `-` lines of a patch's hunks."""
    lines = [line for hunk in patch for line in hunk["lines"]]
    added = sum(line.startswith("+") for line in lines)
    removed = sum(line.startswith("-") for line in lines)
    return added, removed


def _diffed(old: str, new: str) -> tuple[int, int]:
    """The lines a line diff of two texts adds and removes."""
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, _split(old), _split(new), autojunk=False)
    for kind, first, last, begun, ended in matcher.get_opcodes():
        if kind in ("replace", "delete"):
            removed += last - first
        if kind in ("replace", "insert"):
            added += ended - begun
    return added, removed


def edited(tool: str, given: dict[str, Any], record: Any) -> tuple[int, int]:
    """The lines a successful Edit or Write of that input added and removed,
    `record` Claude Code's record of its result."""
    patch = record.get("structuredPatch") if isinstance(record, dict) else None
    if tool == EDIT:
        if isinstance(patch, list):
            return _patched(patch)
        return _diffed(given["old_string"], given["new_string"])
    if isinstance(patch, list) and record.get("type") == "update":
        return _patched(patch)
    return _counted(given["content"]), 0
