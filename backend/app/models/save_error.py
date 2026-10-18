"""Save Error (DB §2.2): the faults held against an Environment's tree."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import ERROR_KIND, ErrorKind


class SaveError(db.Model):  # type: ignore[name-defined]
    """A fault the engine holds against the latest save of one path.

    `path` is from the tree's root: the project's folder, then the file. A
    path's `parse` rows are those of its latest save; a `reverted` row stands
    until the hook has printed it (DB decision 33, assertion 174).
    """

    __tablename__ = "save_errors"
    __table_args__ = (
        Index("ix_save_errors_environment_id_path", "environment_id", "path"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"))
    path: Mapped[str] = mapped_column(Text)
    kind_code: Mapped[ErrorKind] = mapped_column(ERROR_KIND)
    line: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
