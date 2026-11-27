"""Commit, File, File Change and File Edit (DB §2.9): the work a Tool Call did
in a Repository, as its call showed it and as the Repository's history gives
it (F152.11, F158.4, F158.5).

A Commit has two sources, which meet in one row: the Tool Call that made it,
whose publication holds it at once with its Repository, its subject and its
hash as the call showed it, and no lines; and its Repository's history, which
completes it with its whole hash, its author's time and its File Changes, and
gives the Commits no Transcript made. A File Edit is a fact of its Tool Call
alone. A File is made the first time a File Edit or a File Change names it,
and stays.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Commit(db.Model):  # type: ignore[name-defined]
    """A git commit in a Repository: one a Tool Call made, or one no
    Transcript made, which its Repository's history alone gives.

    `sha` is the hash its Tool Call showed, abbreviated or whole, none where
    the call showed none, until its Repository gives it whole. `made_at` is
    its author's time and `lines_read_at` when its File Changes were read,
    both none until its Repository gives them, which it does with the whole
    hash. A Commit read from its Repository stays when the Tool Call that
    made it goes, with no Tool Call; one no read completed goes with it,
    which the publication's write keeps: the key sets none, and a Commit
    with neither a Tool Call nor a read is refused. That a Commit has File
    Changes only once it has a `lines_read_at` (DB 578) is the read's to
    keep.
    """

    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint("repository_id", "sha"),
        # What a File Change's key references, so its Commit and its File
        # are of one Repository (DB 557).
        UniqueConstraint("id", "repository_id"),
        # Read when a Tool Call goes, and for a Tool Call's Commits.
        Index("ix_commits_tool_call_id", "tool_call_id"),
        CheckConstraint(
            "tool_call_id IS NOT NULL OR lines_read_at IS NOT NULL",
            name="ck_commits_source",
        ),
        CheckConstraint(
            "(made_at IS NULL) = (lines_read_at IS NULL)"
            " AND (lines_read_at IS NULL OR sha IS NOT NULL)",
            name="ck_commits_read",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    sha: Mapped[str | None] = mapped_column(Text)
    made_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str] = mapped_column(Text)
    tool_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="SET NULL")
    )
    lines_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class File(db.Model):  # type: ignore[name-defined]
    """A file in a Repository, by its path within the checkout. A file that
    moved is two Files. `class_code` is a label, the labeller's, none until
    it is classed."""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("repository_id", "path"),
        # What a File Change's key references (DB 557).
        UniqueConstraint("id", "repository_id"),
        # Read at every walk, for the Files that wait to be classed.
        Index("ix_files_unclassed", "id", postgresql_where=text("class_code IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    path: Mapped[str] = mapped_column(Text)
    class_code: Mapped[str | None] = mapped_column(ForeignKey("file_classes.code"))


class FileChange(db.Model):  # type: ignore[name-defined]
    """A change one Commit made to one File, with the lines it added and
    removed, as its Repository's history gives it. It carries the Commit's
    Repository, which is its File's (DB 557)."""

    __tablename__ = "file_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["commit_id", "repository_id"],
            ["commits.id", "commits.repository_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["file_id", "repository_id"], ["files.id", "files.repository_id"]
        ),
        CheckConstraint(
            "lines_added >= 0 AND lines_removed >= 0", name="ck_file_changes_lines"
        ),
    )

    commit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    lines_added: Mapped[int] = mapped_column(Integer)
    lines_removed: Mapped[int] = mapped_column(Integer)


class FileEdit(db.Model):  # type: ignore[name-defined]
    """An edit of one File by one Tool Call, a successful Edit or Write, with
    the lines it added and removed. Its File may be of another Repository
    than its Tool Call's Transcript (DB 557); that its Tool Call is a
    successful Edit or Write (DB 579) is the publication's to keep."""

    __tablename__ = "file_edits"
    __table_args__ = (
        CheckConstraint(
            "lines_added >= 0 AND lines_removed >= 0", name="ck_file_edits_lines"
        ),
    )

    tool_call_id: Mapped[int] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), primary_key=True)
    lines_added: Mapped[int] = mapped_column(Integer)
    lines_removed: Mapped[int] = mapped_column(Integer)
