"""Paths of the store's tree, and the hash the sync protocol speaks (design 1
§5.1, §5.2)."""

import hashlib

from app.models import Attachment, Project

DRAFT = "project.md"
HANDBOOK = "handbook.md"
PLAN = "plan.json"
TIMELINE = "timeline.json"
CHAT = "chat.md"
REFERENCE = "reference.json"
"""At the tree's root, beside the projects' folders (DB decision 34)."""


def folder(project: Project) -> str:
    """The project's folder: `draft-<number>` until Create project takes its
    slug (DB decision 1)."""
    if project.slug is None:
        return f"draft-{project.number}"
    return project.slug


def tree_path(project: Project, path: str) -> str:
    """A path of the project's folder, from the tree's root."""
    return f"{folder(project)}/{path}"


def attachment_path(attachment: Attachment) -> str:
    """Where an attachment is in its project's folder (DB decision 39)."""
    return f"attachments/{attachment.batch}/{attachment.filename}"


def sha256_hex(text: str) -> str:
    """The sha256 of a text's UTF-8 bytes, hex (DB §7.1)."""
    return hashlib.sha256(text.encode()).hexdigest()
