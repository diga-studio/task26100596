"""TalentPulse 故事审签发布库的自动化测试（直接调用库函数）。"""

import unittest

from talentpulse import (
    ACTION_APPROVE,
    ACTION_PUBLISH,
    ACTION_SUBMIT,
    HISTORY_KEEP,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    InvalidTransition,
    RevisionNotFound,
    StoryNotFound,
    StoryStore,
    VersionConflict,
)


class TalentPulseTest(unittest.TestCase):
    def setUp(self):
        self.store = StoryStore()

    def tearDown(self):
        self.store.close()

    def test_stale_approve_after_edit(self):
        # 创建并走完审签发布流程，发布第 1 版
        self.store.save("story", 0, body="第一版正文")
        self.store.transition("story", 1, ACTION_SUBMIT)
        self.store.transition("story", 2, ACTION_APPROVE)
        self.store.transition("story", 3, ACTION_PUBLISH)

        # 继续编辑：产生新工作稿，状态回到 Draft，批准资格失效
        self.store.save("story", 4, body="第二版正文")
        state = self.store.read("story")
        self.assertEqual(state["status"], STATUS_DRAFT)
        self.assertEqual(state["version"], 5)

        # 迟到的批准请求（携带编辑前的 expected_version=3）不得批准新稿
        with self.assertRaises(VersionConflict):
            self.store.transition("story", 3, ACTION_APPROVE)

        # 新稿仍是 Draft，旧发布稿未变且仍可读
        state = self.store.read("story")
        self.assertEqual(state["status"], STATUS_DRAFT)
        self.assertEqual(state["draft_body"], "第二版正文")
        self.assertEqual(state["published_revision"], 1)
        self.assertEqual(state["published_body"], "第一版正文")

    def test_history_pruned_but_published_readable(self):
        # 发布第 1 版
        self.store.save("story", 0, body="已发布的第一版")
        self.store.transition("story", 1, ACTION_SUBMIT)
        self.store.transition("story", 2, ACTION_APPROVE)
        self.store.transition("story", 3, ACTION_PUBLISH)

        # 连续编辑 11 次（超过保留窗口 10）
        version = 4
        for i in range(2, 13):
            self.store.save("story", version, body=f"第{i}版草稿")
            version += 1

        state = self.store.read("story")
        # 共 12 份修订，历史只保留最近 10 份：修订 3..12
        kept = [r["revision"] for r in state["revisions"]]
        self.assertEqual(len(kept), HISTORY_KEEP)
        self.assertNotIn(1, kept)
        self.assertNotIn(2, kept)
        self.assertEqual(min(kept), 3)
        self.assertEqual(max(kept), 12)

        # 发布稿对应修订 1，虽被裁出历史窗口，正文仍额外保留可读
        self.assertEqual(state["published_revision"], 1)
        self.assertEqual(state["published_body"], "已发布的第一版")

        # 被裁剪的修订不能作为回滚来源
        with self.assertRaises(RevisionNotFound):
            self.store.save("story", version, source_revision=1)

    def test_rollback_creates_new_draft(self):
        # 发布第 1 版，再编辑出第 2 版
        self.store.save("story", 0, body="原始正文")
        self.store.transition("story", 1, ACTION_SUBMIT)
        self.store.transition("story", 2, ACTION_APPROVE)
        self.store.transition("story", 3, ACTION_PUBLISH)
        self.store.save("story", 4, body="改坏的正文")

        # 回滚到修订 1：正文逐字相同，但产生全新修订，工作稿为 Draft
        result = self.store.save("story", 5, source_revision=1)
        self.assertEqual(result["status"], STATUS_DRAFT)
        state = self.store.read("story")
        self.assertEqual(state["draft_revision"], 3)
        self.assertEqual(state["draft_body"], "原始正文")

        # 即使正文与已发布稿逐字相同，也不继承旧修订的批准资格：
        # 不能直接发布，必须重新走完整审签流程
        with self.assertRaises(InvalidTransition):
            self.store.transition("story", 6, ACTION_PUBLISH)
        with self.assertRaises(InvalidTransition):
            self.store.transition("story", 6, ACTION_APPROVE)

        # 重新走流程后可以发布，发布稿指向新修订 3
        self.store.transition("story", 6, ACTION_SUBMIT)
        self.store.transition("story", 7, ACTION_APPROVE)
        self.store.transition("story", 8, ACTION_PUBLISH)
        state = self.store.read("story")
        self.assertEqual(state["status"], STATUS_PUBLISHED)
        self.assertEqual(state["published_revision"], 3)
        self.assertEqual(state["published_body"], "原始正文")

        # 不存在的故事 read 报错
        with self.assertRaises(StoryNotFound):
            self.store.read("ghost")


if __name__ == "__main__":
    unittest.main()
