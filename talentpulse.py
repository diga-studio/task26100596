"""TalentPulse 故事审签发布库（Python3 标准库 + SQLite）。"""

from __future__ import annotations

import sqlite3
from typing import Optional

HISTORY_KEEP = 10

STATUS_DRAFT = "Draft"
STATUS_IN_REVIEW = "InReview"
STATUS_APPROVED = "Approved"
STATUS_PUBLISHED = "Published"

ACTION_SUBMIT = "submit"
ACTION_APPROVE = "approve"
ACTION_PUBLISH = "publish"


class TalentPulseError(Exception):
    """库内所有错误的基类。"""


class StoryNotFound(TalentPulseError):
    pass


class VersionConflict(TalentPulseError):
    pass


class InvalidTransition(TalentPulseError):
    pass


class RevisionNotFound(TalentPulseError):
    pass


class MissingBody(TalentPulseError):
    pass


_SCHEMA = """
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


class StoryStore:
    """基于 SQLite 的故事审签发布存储。"""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()


    # ---- 内部辅助 ----

    def _get_story(self, story_id: str) -> Optional[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(
            "SELECT * FROM stories WHERE story_id = ?", (story_id,)
        )
        return cur.fetchone()

    def _latest_revision(self, story_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(revision), 0) FROM revisions WHERE story_id = ?",
            (story_id,),
        )
        return cur.fetchone()[0]

    def _prune(self, story_id: str) -> None:
        """只保留最近 HISTORY_KEEP 份修订，外加当前发布稿对应的那份。"""
        row = self._get_story(story_id)
        latest = self._latest_revision(story_id)
        keep_from = latest - HISTORY_KEEP + 1
        published = row["published_revision"]
        self._conn.execute(
            "DELETE FROM revisions WHERE story_id = ? AND revision < ? "
            "AND revision IS NOT ?",
            (story_id, keep_from, published),
        )

    def _check_version(self, row: sqlite3.Row, expected_version: int) -> None:
        if row["version"] != expected_version:
            raise VersionConflict(
                f"expected_version={expected_version} 与当前版本 "
                f"{row['version']} 不一致"
            )

    def _state(self, story_id: str) -> dict:
        row = self._get_story(story_id)
        return {
            "story_id": story_id,
            "version": row["version"],
            "status": row["status"],
            "draft_revision": row["draft_revision"],
            "published_revision": row["published_revision"],
        }

    def save(
        self,
        story_id: str,
        expected_version: int,
        body: Optional[str] = None,
        source_revision: Optional[int] = None,
    ) -> dict:
        """保存新工作稿：普通编辑（body）或回滚（source_revision）。

        两者都产生全新的内容修订，并将工作稿置为 Draft。
        不存在的故事以 expected_version=0 创建。
        """
        if body is None and source_revision is None:
            raise MissingBody("必须提供 body 或 source_revision")
        if body is not None and source_revision is not None:
            raise MissingBody("body 与 source_revision 只能二选一")

        with self._conn:
            row = self._get_story(story_id)
            if row is None:
                if expected_version != 0:
                    raise VersionConflict(
                        "故事不存在，必须以 expected_version=0 创建"
                    )
                if source_revision is not None:
                    raise RevisionNotFound("新故事没有可回滚的修订")
                self._conn.execute(
                    "INSERT INTO stories "
                    "(story_id, version, status, draft_revision, "
                    "published_revision) VALUES (?, 1, ?, 1, NULL)",
                    (story_id, STATUS_DRAFT),
                )
                self._conn.execute(
                    "INSERT INTO revisions (story_id, revision, body) "
                    "VALUES (?, 1, ?)",
                    (story_id, body),
                )
                return self._state(story_id)

            self._check_version(row, expected_version)

            if source_revision is not None:
                latest = self._latest_revision(story_id)
                keep_from = latest - HISTORY_KEEP + 1
                cur = self._conn.execute(
                    "SELECT body FROM revisions WHERE story_id = ? "
                    "AND revision = ? AND revision >= ?",
                    (story_id, source_revision, keep_from),
                )
                found = cur.fetchone()
                if found is None:
                    raise RevisionNotFound(
                        f"修订 {source_revision} 不存在或已被裁剪，不能回滚"
                    )
                new_body = found[0]
            else:
                new_body = body

            new_revision = self._latest_revision(story_id) + 1
            self._conn.execute(
                "INSERT INTO revisions (story_id, revision, body) "
                "VALUES (?, ?, ?)",
                (story_id, new_revision, new_body),
            )
            self._conn.execute(
                "UPDATE stories SET version = version + 1, status = ?, "
                "draft_revision = ? WHERE story_id = ?",
                (STATUS_DRAFT, new_revision, story_id),
            )
            self._prune(story_id)
            return self._state(story_id)

    def transition(self, story_id: str, expected_version: int, action: str) -> dict:
        """推进工作稿状态：submit / approve / publish，逐级前进。

        发布时才把工作稿正文替换为对外可读的发布稿。
        """
        forward = {
            ACTION_SUBMIT: (STATUS_DRAFT, STATUS_IN_REVIEW),
            ACTION_APPROVE: (STATUS_IN_REVIEW, STATUS_APPROVED),
            ACTION_PUBLISH: (STATUS_APPROVED, STATUS_PUBLISHED),
        }
        if action not in forward:
            raise InvalidTransition(f"不支持的动作: {action!r}")

        with self._conn:
            row = self._get_story(story_id)
            if row is None:
                raise StoryNotFound(f"故事不存在: {story_id}")
            self._check_version(row, expected_version)

            want_from, want_to = forward[action]
            if row["status"] != want_from:
                raise InvalidTransition(
                    f"当前状态 {row['status']} 不能执行 {action}"
                )

            if action == ACTION_PUBLISH:
                self._conn.execute(
                    "UPDATE stories SET version = version + 1, status = ?, "
                    "published_revision = draft_revision WHERE story_id = ?",
                    (want_to, story_id),
                )
                self._prune(story_id)
            else:
                self._conn.execute(
                    "UPDATE stories SET version = version + 1, status = ? "
                    "WHERE story_id = ?",
                    (want_to, story_id),
                )
            return self._state(story_id)

    def read(self, story_id: str) -> dict:
        """读取故事版本、工作稿状态及正文、最近修订和当前发布稿。"""
        row = self._get_story(story_id)
        if row is None:
            raise StoryNotFound(f"故事不存在: {story_id}")

        def body_of(revision: Optional[int]) -> Optional[str]:
            if revision is None:
                return None
            cur = self._conn.execute(
                "SELECT body FROM revisions WHERE story_id = ? AND revision = ?",
                (story_id, revision),
            )
            found = cur.fetchone()
            return found[0] if found else None

        cur = self._conn.execute(
            "SELECT revision, body FROM revisions WHERE story_id = ? "
            "ORDER BY revision DESC LIMIT ?",
            (story_id, HISTORY_KEEP),
        )
        revisions = [
            {"revision": rev, "body": text} for rev, text in cur.fetchall()
        ]

        return {
            "story_id": story_id,
            "version": row["version"],
            "status": row["status"],
            "draft_revision": row["draft_revision"],
            "draft_body": body_of(row["draft_revision"]),
            "revisions": revisions,
            "published_revision": row["published_revision"],
            "published_body": body_of(row["published_revision"]),
        }
