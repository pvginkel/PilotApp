"""The collector's clones of the mirror (F152.11, F158.4): a bare clone of
each Repository Pilot holds, cloned with no credential from the first owner
on the mirror that holds it and fetched once held, and the commits of its
history Pilot lacks, with their lines per file under git's rename detection,
proved against git repositories the test makes and serves from a folder of
its own."""

import os
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pilot_collection.repositories import (
    HeldRepositorySchema,
    ReadCommitSchema,
    ReadFileChangeSchema,
)

from pilot_collector.mirror import Clones, Unread, commits, reads
from tests.support import settings

PANTRY = "Pantry"
"""The name of a Repository Pilot holds."""
OWNERS = ["larder", "kitchen"]
"""The mirror's owners, in the order the settings name them."""
AT = datetime(2026, 11, 12, 9, 0, tzinfo=timezone(timedelta(hours=1)))
"""When the first commit was authored."""

_ALONE = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "A cook",
    "GIT_AUTHOR_EMAIL": "cook@pantry.invalid",
    "GIT_COMMITTER_NAME": "A cook",
    "GIT_COMMITTER_EMAIL": "cook@pantry.invalid",
}
"""What the test's own git calls run under: no config of the host's, and an
invented author."""


def _git(tree: Path | None, *arguments: str, at: datetime | None = None) -> str:
    """What the test's git wrote, run in `tree`, at `at` where given."""
    dated = (
        {}
        if at is None
        else {"GIT_AUTHOR_DATE": at.isoformat(), "GIT_COMMITTER_DATE": at.isoformat()}
    )
    return subprocess.run(
        ["git", *([] if tree is None else ["-C", str(tree)]), *arguments],
        capture_output=True,
        check=True,
        text=True,
        env=os.environ | _ALONE | dated,
    ).stdout.strip()


class _Kept:
    """A Repository on the mirror under one owner, and the working tree its
    commits are made in and pushed from."""

    def __init__(self, tmp: Path, owner: str, name: str = PANTRY) -> None:
        self.bare = tmp / "mirror" / owner / f"{name}.git"
        self.tree = tmp / "trees" / owner / name
        _git(None, "init", "--quiet", "--bare", "-b", "main", str(self.bare))
        _git(None, "init", "--quiet", "-b", "main", str(self.tree))
        _git(self.tree, "remote", "add", "origin", str(self.bare))

    def commit(
        self, message: str, at: datetime, files: dict[str, str | bytes | None]
    ) -> str:
        """Commit `files` at `at`, each written as given or removed where
        none, under `message`; its whole hash."""
        for path, content in files.items():
            file = self.tree / path
            if content is None:
                file.unlink()
                continue
            file.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                file.write_bytes(content)
            else:
                file.write_text(content)
        _git(self.tree, "add", "--all")
        _git(self.tree, "commit", "--quiet", "-m", message, at=at)
        return _git(self.tree, "rev-parse", "HEAD")

    def moved(self, old: str, new: str) -> None:
        (self.tree / new).parent.mkdir(parents=True, exist_ok=True)
        _git(self.tree, "mv", old, new)

    def pushed(self) -> None:
        _git(self.tree, "push", "--quiet", "origin", "--all")


def _lines(count: int, word: str = "salt") -> str:
    return "".join(f"{word} {n}\n" for n in range(count))


def _clones(tmp: Path, owners: list[str] = OWNERS) -> Clones:
    """The collector's clones of the mirror the test serves from its folder,
    kept in a folder of their own."""
    return Clones(
        settings(
            COLLECTOR_MIRROR_URL=f"file://{tmp / 'mirror'}/",
            COLLECTOR_MIRROR_OWNERS=owners,
            COLLECTOR_CLONES=tmp / "clones",
        )
    )


def _held(*read: str, name: str = PANTRY) -> HeldRepositorySchema:
    return HeldRepositorySchema(name=name, read=sorted(read))


def _read(clones: Clones, held: HeldRepositorySchema) -> list[ReadCommitSchema]:
    """The commits one read of the clone gave, every part of it."""
    return [commit for part in clones.read(held) for commit in part.commits]


def _change(path: str, added: int, removed: int) -> ReadFileChangeSchema:
    return ReadFileChangeSchema(path=path, lines_added=added, lines_removed=removed)


class TestARead:
    def test_one_pilot_holds_none_of_is_cloned_and_read_whole_oldest_first(
        self, tmp_path: Path
    ) -> None:
        kept = _Kept(tmp_path, "larder")
        first = kept.commit(
            "Stock the shelves",
            AT,
            {"shelves/flour.md": _lines(3), "pantry.txt": _lines(2)},
        )
        second = kept.commit(
            "Thicken the soup\nwith barley\n\nThe soup was thin.",
            AT + timedelta(minutes=5),
            {"shelves/flour.md": _lines(3) + "barley\n", "pantry.txt": _lines(1)},
        )
        kept.pushed()
        began = datetime.now(UTC)

        (part,) = _clones(tmp_path).read(_held())

        assert part.repository == PANTRY
        assert began <= part.read_at <= datetime.now(UTC)
        assert part.commits == [
            ReadCommitSchema(
                sha=first,
                made_at=AT,
                subject="Stock the shelves",
                files=[_change("pantry.txt", 2, 0), _change("shelves/flour.md", 3, 0)],
            ),
            ReadCommitSchema(
                sha=second,
                made_at=AT + timedelta(minutes=5),
                subject="Thicken the soup with barley",
                files=[_change("pantry.txt", 0, 1), _change("shelves/flour.md", 1, 0)],
            ),
        ]
        assert len(first) == 40
        assert part.commits[0].made_at.utcoffset() == timedelta(hours=1)
        assert (tmp_path / "clones" / f"{PANTRY}.git" / "HEAD").is_file()

    def test_a_moved_file_counts_the_lines_changed_in_it_on_its_new_path(
        self, tmp_path: Path
    ) -> None:
        """A moved file's change is the new File's, with the lines changed
        in it and none where it only moved; a deleted file's lines are
        removed; a binary file has no lines (`dispatch-work.md` §5, rule 3)."""
        kept = _Kept(tmp_path, "larder")
        kept.commit(
            "Stock the shelves",
            AT,
            {
                "jars/jam.md": _lines(5),
                "jars/honey.md": _lines(4, "honey"),
                "crates/apples.md": _lines(4, "apple"),
            },
        )
        kept.moved("jars/jam.md", "shelves/jam.md")
        kept.moved("jars/honey.md", "shelves/honey.md")
        moved = kept.commit(
            "Move the jars",
            AT + timedelta(minutes=1),
            {
                "shelves/jam.md": _lines(4) + "plum 4\n",
                "crates/apples.md": None,
                "labels/jam.png": b"\x89PNG\x00\x01\x02",
            },
        )
        kept.pushed()

        read = _read(_clones(tmp_path), _held())

        assert [commit.sha for commit in read][1:] == [moved]
        assert sorted(read[1].files, key=lambda change: change.path) == [
            _change("crates/apples.md", 0, 4),
            _change("labels/jam.png", 0, 0),
            _change("shelves/honey.md", 0, 0),
            _change("shelves/jam.md", 1, 1),
        ]

    def test_a_merge_commit_has_no_change(self, tmp_path: Path) -> None:
        kept = _Kept(tmp_path, "larder")
        kept.commit("Stock the shelves", AT, {"pantry.txt": _lines(2)})
        _git(kept.tree, "checkout", "--quiet", "-b", "spices")
        spiced = kept.commit(
            "Add the spices", AT + timedelta(minutes=1), {"spices.md": _lines(3)}
        )
        _git(kept.tree, "checkout", "--quiet", "main")
        kept.commit("Add the oil", AT + timedelta(minutes=2), {"oil.md": _lines(1)})
        _git(
            kept.tree,
            "merge",
            "--quiet",
            "--no-edit",
            "spices",
            at=AT + timedelta(minutes=3),
        )
        merged = _git(kept.tree, "rev-parse", "HEAD")
        kept.pushed()

        read = {commit.sha: commit for commit in _read(_clones(tmp_path), _held())}

        assert len(read) == 4
        assert read[merged].files == []
        assert read[merged].subject == "Merge branch 'spices'"
        assert read[spiced].files == [_change("spices.md", 3, 0)]

    def test_a_path_is_read_as_git_holds_it(self, tmp_path: Path) -> None:
        kept = _Kept(tmp_path, "larder")
        kept.commit(
            "Label the jars",
            AT,
            {"jars/crème brûlée.md": _lines(2), "jars/two\tjars.md": _lines(1)},
        )
        kept.moved("jars/two\tjars.md", "jars/three\tjars.md")
        kept.commit("Add a jar", AT + timedelta(minutes=1), {})
        kept.pushed()

        read = _read(_clones(tmp_path), _held())

        assert read[0].files == [
            _change("jars/crème brûlée.md", 2, 0),
            _change("jars/two\tjars.md", 1, 0),
        ]
        assert read[1].files == [_change("jars/three\tjars.md", 0, 0)]


class TestPilotIsTheCursor:
    def test_only_the_commits_pilot_lacks_are_read(self, tmp_path: Path) -> None:
        kept = _Kept(tmp_path, "larder")
        first = kept.commit("Stock the shelves", AT, {"pantry.txt": _lines(2)})
        second = kept.commit(
            "Add the oil", AT + timedelta(minutes=1), {"oil.md": _lines(1)}
        )
        kept.pushed()

        read = _read(_clones(tmp_path), _held(first))

        assert [commit.sha for commit in read] == [second]

    def test_one_pilot_holds_every_commit_of_gives_no_read(
        self, tmp_path: Path
    ) -> None:
        kept = _Kept(tmp_path, "larder")
        first = kept.commit("Stock the shelves", AT, {"pantry.txt": _lines(2)})
        kept.pushed()

        assert _clones(tmp_path).read(_held(first)) == []

    def test_an_empty_repository_gives_no_read(self, tmp_path: Path) -> None:
        _Kept(tmp_path, "larder")

        assert _clones(tmp_path).read(_held()) == []

    def test_a_clone_held_is_fetched_every_branch_as_the_mirror_has_it(
        self, tmp_path: Path
    ) -> None:
        kept = _Kept(tmp_path, "larder")
        first = kept.commit("Stock the shelves", AT, {"pantry.txt": _lines(2)})
        kept.pushed()
        clones = _clones(tmp_path)
        clones.read(_held())
        later = kept.commit(
            "Add the oil", AT + timedelta(minutes=1), {"oil.md": _lines(1)}
        )
        _git(kept.tree, "checkout", "--quiet", "-b", "spices")
        spiced = kept.commit(
            "Add the spices", AT + timedelta(minutes=2), {"spices.md": _lines(3)}
        )
        kept.pushed()

        read = _read(clones, _held(first))

        assert [commit.sha for commit in read] == [later, spiced]


class TestTheMirrorsOwners:
    def test_the_first_owner_that_holds_it_is_cloned(self, tmp_path: Path) -> None:
        larder, kitchen = _Kept(tmp_path, "larder"), _Kept(tmp_path, "kitchen")
        kept = kitchen.commit("Stock the kitchen", AT, {"stove.md": _lines(1)})
        kitchen.pushed()
        larder.commit("Stock the larder", AT, {"pantry.txt": _lines(1)})
        larder.pushed()

        read = _read(_clones(tmp_path, ["kitchen", "larder"]), _held())

        assert [commit.sha for commit in read] == [kept]

    def test_one_the_first_owner_lacks_is_cloned_from_the_next(
        self, tmp_path: Path
    ) -> None:
        kitchen = _Kept(tmp_path, "kitchen")
        kept = kitchen.commit("Stock the kitchen", AT, {"stove.md": _lines(1)})
        kitchen.pushed()

        read = _read(_clones(tmp_path), _held())

        assert [commit.sha for commit in read] == [kept]

    def test_one_no_owner_holds_is_unread_until_one_does(self, tmp_path: Path) -> None:
        clones = _clones(tmp_path)

        with pytest.raises(Unread) as unread:
            clones.read(_held())

        said = str(unread.value)
        assert said.startswith(
            "no owner on the mirror holds it: larder: `git clone` exited 128: "
        )
        assert "; kitchen: `git clone` exited 128: " in said
        assert sorted(path.name for path in (tmp_path / "clones").iterdir()) == []
        larder = _Kept(tmp_path, "larder")
        kept = larder.commit("Stock the larder", AT, {"pantry.txt": _lines(1)})
        larder.pushed()

        assert [commit.sha for commit in _read(clones, _held())] == [kept]

    def test_a_clone_left_unfinished_is_made_again(self, tmp_path: Path) -> None:
        larder = _Kept(tmp_path, "larder")
        kept = larder.commit("Stock the larder", AT, {"pantry.txt": _lines(1)})
        larder.pushed()
        unfinished = tmp_path / "clones" / f"{PANTRY}.git.partial"
        unfinished.mkdir(parents=True)
        (unfinished / "HEAD").write_text("ref: refs/heads/stale\n")

        read = _read(_clones(tmp_path), _held())

        assert [commit.sha for commit in read] == [kept]
        assert not unfinished.exists()

    def test_a_clone_that_cannot_be_fetched_is_unread(self, tmp_path: Path) -> None:
        larder = _Kept(tmp_path, "larder")
        larder.commit("Stock the larder", AT, {"pantry.txt": _lines(1)})
        larder.pushed()
        clones = _clones(tmp_path)
        clones.read(_held())
        larder.bare.rename(larder.bare.with_name("Gone.git"))

        with pytest.raises(Unread, match="^`git fetch` exited 128: "):
            clones.read(_held())

    @pytest.mark.parametrize("name", ["../Pantry", "..", "."])
    def test_a_name_that_is_no_one_folder_is_unread(
        self, tmp_path: Path, name: str
    ) -> None:
        with pytest.raises(Unread, match="is no name of one folder"):
            _clones(tmp_path).read(_held(name=name))


def _commit(n: int, files: int = 1) -> ReadCommitSchema:
    return ReadCommitSchema(
        sha=f"{n:040x}",
        made_at=AT,
        subject=f"Stock shelf {n}",
        files=[_change(f"shelf/{n}/{k}.md", 1, 0) for k in range(files)],
    )


class TestAReadsCalls:
    def test_a_read_within_its_bytes_is_one_call(self) -> None:
        found = [_commit(n) for n in range(3)]

        (part,) = reads(PANTRY, AT, found)

        assert (part.repository, part.read_at, part.commits) == (PANTRY, AT, found)

    def test_one_past_them_goes_on_in_another_call_in_its_order(self) -> None:
        found = [_commit(n) for n in range(5)]
        each = len(found[0].model_dump_json()) + 1

        split = reads(PANTRY, AT, found, budget=2 * each)

        assert [part.commits for part in split] == [found[:2], found[2:4], found[4:]]
        assert {(part.repository, part.read_at) for part in split} == {(PANTRY, AT)}

    def test_a_commit_past_them_alone_is_a_call_of_its_own(self) -> None:
        found = [_commit(0), _commit(1, files=40), _commit(2)]

        split = reads(PANTRY, AT, found, budget=len(found[0].model_dump_json()) + 1)

        assert [part.commits for part in split] == [[each] for each in found]


class TestGitsOutput:
    def test_a_rename_gives_its_old_path_and_its_new_after_its_lines(self) -> None:
        sha, parent = "a" * 40, "b" * 40
        logged = (
            f"{sha}\0{parent}\0{AT.isoformat()}\0Move the jars\0"
            "\n2\t1\t\0jars/jam.md\0shelves/jam.md\0-\t-\tlabels/jam.png\0"
            f"{parent}\0\0{AT.isoformat()}\0Stock the shelves\0"
            "\n5\t0\tjars/jam.md\0"
        ).encode()

        assert commits(logged) == [
            ReadCommitSchema(
                sha=sha,
                made_at=AT,
                subject="Move the jars",
                files=[
                    _change("shelves/jam.md", 2, 1),
                    _change("labels/jam.png", 0, 0),
                ],
            ),
            ReadCommitSchema(
                sha=parent,
                made_at=AT,
                subject="Stock the shelves",
                files=[_change("jars/jam.md", 5, 0)],
            ),
        ]

    def test_a_merge_commits_changes_are_none(self) -> None:
        sha, parents = "c" * 40, f"{'a' * 40} {'b' * 40}"
        logged = (
            f"{sha}\0{parents}\0{AT.isoformat()}\0Merge the spices\0\n1\t0\tspices.md\0"
        ).encode()

        (merged,) = commits(logged)

        assert merged.files == []
