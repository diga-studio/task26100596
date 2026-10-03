import unittest

from talentpulse import (
    APPROVED,
    DRAFT,
    IN_REVIEW,
    PUBLISHED,
    ACTION_APPROVE,
    ACTION_PUBLISH,
    ACTION_SUBMIT,
    InvalidTransitionError,
    RevisionNotFoundError,
    StoryNotFoundError,
    StoryStore,
    VersionConflictError,
)


class StoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = StoryStore()

    def tearDown(self):
        self.store.close()

    def test_create_edit_and_read(self):
        v = self.store.save("s1", 0, body="第一稿")
        self.assertEqual((v.version, v.status, v.draft_body), (1, DRAFT, "第一稿"))
        self.assertIsNone(v.published_body)
        self.assertIsNone(v.published_revision)

        v = self.store.save("s1", 1, body="第二稿")
        self.assertEqual((v.version, v.draft_body), (2, "第二稿"))
        self.assertEqual([r.revision for r in v.revisions], [2, 1])

    def test_expected_version_enforced(self):
        self.store.save("s1", 0, body="a")
        with self.assertRaises(VersionConflictError):
            self.store.save("s1", 0, body="b")
        with self.assertRaises(VersionConflictError):
            self.store.save("s2", 3, body="b")
        with self.assertRaises(VersionConflictError):
            self.store.transition("s1", 9, ACTION_SUBMIT)

    def test_transition_order_no_skip(self):
        self.store.save("s1", 0, body="a")
        with self.assertRaises(InvalidTransitionError):
            self.store.transition("s1", 1, ACTION_APPROVE)
        with self.assertRaises(InvalidTransitionError):
            self.store.transition("s1", 1, ACTION_PUBLISH)
        v = self.store.transition("s1", 1, ACTION_SUBMIT)
        self.assertEqual((v.status, v.version), (IN_REVIEW, 2))
        v = self.store.transition("s1", 2, ACTION_APPROVE)
        self.assertEqual((v.status, v.version), (APPROVED, 3))
        v = self.store.transition("s1", 3, ACTION_PUBLISH)
        self.assertEqual((v.status, v.version), (PUBLISHED, 4))
        self.assertEqual(v.published_body, "a")
        self.assertEqual(v.published_revision, 1)

    def test_stale_approve_does_not_approve_new_draft(self):
        store = self.store
        store.save("s1", 0, body="旧稿")
        store.transition("s1", 1, ACTION_SUBMIT)
        store.transition("s1", 2, ACTION_APPROVE)
        store.transition("s1", 3, ACTION_PUBLISH)

        v = store.save("s1", 4, body="新稿")
        self.assertEqual((v.status, v.version), (DRAFT, 5))
        store.transition("s1", 5, ACTION_SUBMIT)

        # 投递编辑前（版本 3 时）就已发出的批准请求：版本已过期，必须拒绝。
        with self.assertRaises(VersionConflictError):
            store.transition("s1", 3, ACTION_APPROVE)

        v = store.read("s1")
        self.assertEqual(v.status, IN_REVIEW)
        self.assertEqual(v.draft_body, "新稿")
        self.assertEqual(v.published_body, "旧稿")
        self.assertEqual(v.published_revision, 1)

    def test_save_invalidates_pending_approval(self):
        store = self.store
        store.save("s1", 0, body="v1")
        store.transition("s1", 1, ACTION_SUBMIT)
        store.transition("s1", 2, ACTION_APPROVE)
        v = store.save("s1", 3, body="v2")
        self.assertEqual(v.status, DRAFT)
        with self.assertRaises(InvalidTransitionError):
            store.transition("s1", 4, ACTION_PUBLISH)

    def test_history_pruned_but_published_body_kept(self):
        store = self.store
        store.save("s1", 0, body="发布稿")
        store.transition("s1", 1, ACTION_SUBMIT)
        store.transition("s1", 2, ACTION_APPROVE)
        store.transition("s1", 3, ACTION_PUBLISH)

        version = 4
        for i in range(1, 13):
            v = store.save("s1", version, body=f"编辑{i}")
            version += 1

        self.assertEqual(len(v.revisions), 10)
        kept = {r.revision for r in v.revisions}
        self.assertNotIn(1, kept)
        self.assertEqual(v.published_body, "发布稿")
        self.assertEqual(v.published_revision, 1)

        # 被裁剪的修订不能作为回滚来源。
        with self.assertRaises(RevisionNotFoundError):
            store.save("s1", version, source_revision=1)
        with self.assertRaises(RevisionNotFoundError):
            store.save("s1", version, source_revision=2)

    def test_rollback_kept_revision_creates_new_draft(self):
        store = self.store
        store.save("s1", 0, body="发布稿")
        store.transition("s1", 1, ACTION_SUBMIT)
        store.transition("s1", 2, ACTION_APPROVE)
        store.transition("s1", 3, ACTION_PUBLISH)
        store.save("s1", 4, body="编辑1")

        v = store.save("s1", 5, source_revision=1)
        self.assertEqual(v.status, DRAFT)
        self.assertEqual(v.draft_body, "发布稿")
        # 回滚产生全新修订号，不复用旧号。
        self.assertEqual(v.revisions[0].revision, 3)
        # 新工作稿是 Draft，不能直接发布。
        with self.assertRaises(InvalidTransitionError):
            store.transition("s1", 6, ACTION_PUBLISH)
        # 旧发布稿不受影响。
        self.assertEqual(v.published_body, "发布稿")
        self.assertEqual(v.published_revision, 1)

    def test_rollback_same_text_still_new_revision(self):
        store = self.store
        store.save("s1", 0, body="相同正文")
        v = store.save("s1", 1, source_revision=1)
        self.assertEqual(v.draft_body, "相同正文")
        self.assertEqual(v.revisions[0].revision, 2)
        self.assertEqual(v.status, DRAFT)

    def test_read_missing_story(self):
        with self.assertRaises(StoryNotFoundError):
            self.store.read("ghost")
        with self.assertRaises(StoryNotFoundError):
            self.store.transition("ghost", 0, ACTION_SUBMIT)

    def test_persistence_with_file_db(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            store = StoryStore(path)
            store.save("s1", 0, body="持久化")
            store.transition("s1", 1, ACTION_SUBMIT)
            store.close()

            store2 = StoryStore(path)
            v = store2.read("s1")
            self.assertEqual((v.version, v.status, v.draft_body), (2, IN_REVIEW, "持久化"))
            store2.close()
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
