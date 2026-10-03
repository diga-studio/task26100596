"""TalentPulse 故事审签发布库（Python3 标准库 + SQLite）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


DRAFT = "Draft"
IN_REVIEW = "InReview"
APPROVED = "Approved"
PUBLISHED = "Published"

ACTION_SUBMIT = "submit"
ACTION_APPROVE = "approve"
ACTION_PUBLISH = "publish"


class TalentPulseError(Exception):
    """库级错误基类。"""


class StoryNotFoundError(TalentPulseError):
    pass


class VersionConflictError(TalentPulseError):
    pass


class InvalidTransitionError(TalentPulseError):
    pass


class RevisionNotFoundError(TalentPulseError):
    pass


@dataclass
class RevisionInfo:
    revision: int
    body: str


@dataclass
class StoryView:
    story_id: str
    version: int
    status: str
    draft_body: str
    revisions: list[RevisionInfo]
    published_body: Optional[str]
    published_revision: Optional[int]


class StoryStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stories (
                story_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                draft_revision INTEGER NOT NULL,
                published_revision INTEGER
            );
            CREATE TABLE IF NOT EXISTS revisions (
                story_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                body TEXT NOT NULL,
                PRIMARY KEY (story_id, revision)
            );
            """
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def save(
        self,
        story_id: str,
        expected_version: int,
        body: Optional[str] = None,
        source_revision: Optional[int] = None,
    ) -> StoryView:
        if body is not None and source_revision is not None:
            raise TalentPulseError("body 与 source_revision 只能提供一个")

        row = self._conn.execute(
            "SELECT version, published_revision FROM stories WHERE story_id = ?",
            (story_id,),
        ).fetchone()

        if row is None:
            if expected_version != 0:
                raise VersionConflictError(
                    f"故事不存在，expected_version 必须为 0，收到 {expected_version}"
                )
            if source_revision is not None:
                raise RevisionNotFoundError("新故事没有可回滚的修订")
            if body is None:
                raise TalentPulseError("必须提供 body 或 source_revision")
            with self._conn:
                self._conn.execute(
                    "INSERT INTO stories (story_id, version, status, "
                    "draft_revision, published_revision) VALUES (?, 1, ?, 1, NULL)",
                    (story_id, DRAFT),
                )
                self._conn.execute(
                    "INSERT INTO revisions (story_id, revision, body) VALUES (?, 1, ?)",
                    (story_id, body),
                )
            return self.read(story_id)

        version, published_revision = row
        if version != expected_version:
            raise VersionConflictError(
                f"版本冲突：当前 {version}，expected {expected_version}"
            )

        max_rev = self._conn.execute(
            "SELECT MAX(revision) FROM revisions WHERE story_id = ?",
            (story_id,),
        ).fetchone()[0]

        if source_revision is not None:
            if source_revision > max_rev - 10:
                src = self._conn.execute(
                    "SELECT body FROM revisions WHERE story_id = ? AND revision = ?",
                    (story_id, source_revision),
                ).fetchone()
            else:
                src = None
            if src is None:
                raise RevisionNotFoundError(
                    f"修订 {source_revision} 不在最近 10 份内容修订内，无法回滚"
                )
            new_body = src[0]
        else:
            if body is None:
                raise TalentPulseError("必须提供 body 或 source_revision")
            new_body = body

        new_rev = max_rev + 1
        with self._conn:
            self._conn.execute(
                "INSERT INTO revisions (story_id, revision, body) VALUES (?, ?, ?)",
                (story_id, new_rev, new_body),
            )
            self._conn.execute(
                "UPDATE stories SET version = version + 1, status = ?, "
                "draft_revision = ? WHERE story_id = ?",
                (DRAFT, new_rev, story_id),
            )
            self._conn.execute(
                "DELETE FROM revisions WHERE story_id = ? AND revision <= ? "
                "AND revision IS NOT ?",
                (story_id, new_rev - 10, published_revision if published_revision is not None else -1),
            )
        return self.read(story_id)

    def transition(
        self,
        story_id: str,
        expected_version: int,
        action: str,
    ) -> StoryView:
        row = self._conn.execute(
            "SELECT version, status, draft_revision FROM stories WHERE story_id = ?",
            (story_id,),
        ).fetchone()
        if row is None:
            raise StoryNotFoundError(story_id)
        version, status, draft_revision = row
        if version != expected_version:
            raise VersionConflictError(
                f"版本冲突：当前 {version}，expected {expected_version}"
            )

        steps = {
            ACTION_SUBMIT: (DRAFT, IN_REVIEW),
            ACTION_APPROVE: (IN_REVIEW, APPROVED),
            ACTION_PUBLISH: (APPROVED, PUBLISHED),
        }
        if action not in steps:
            raise InvalidTransitionError(f"未知动作：{action}")
        want_from, to_status = steps[action]
        if status != want_from:
            raise InvalidTransitionError(
                f"不能从 {status} 执行 {action}（需要 {want_from}）"
            )

        with self._conn:
            if action == ACTION_PUBLISH:
                self._conn.execute(
                    "UPDATE stories SET version = version + 1, status = ?, "
                    "published_revision = draft_revision WHERE story_id = ?",
                    (to_status, story_id),
                )
            else:
                self._conn.execute(
                    "UPDATE stories SET version = version + 1, status = ? "
                    "WHERE story_id = ?",
                    (to_status, story_id),
                )
        return self.read(story_id)

    def read(self, story_id: str) -> StoryView:
        row = self._conn.execute(
            "SELECT version, status, draft_revision, published_revision "
            "FROM stories WHERE story_id = ?",
            (story_id,),
        ).fetchone()
        if row is None:
            raise StoryNotFoundError(story_id)
        version, status, draft_revision, published_revision = row

        draft_body = self._conn.execute(
            "SELECT body FROM revisions WHERE story_id = ? AND revision = ?",
            (story_id, draft_revision),
        ).fetchone()[0]

        published_body = None
        if published_revision is not None:
            published_body = self._conn.execute(
                "SELECT body FROM revisions WHERE story_id = ? AND revision = ?",
                (story_id, published_revision),
            ).fetchone()[0]

        revisions = [
            RevisionInfo(revision=rev, body=body)
            for rev, body in self._conn.execute(
                "SELECT revision, body FROM revisions "
                "WHERE story_id = ? ORDER BY revision DESC LIMIT 10",
                (story_id,),
            )
        ]

        return StoryView(
            story_id=story_id,
            version=version,
            status=status,
            draft_body=draft_body,
            revisions=revisions,
            published_body=published_body,
            published_revision=published_revision,
        )
