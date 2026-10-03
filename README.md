# task26100596

TalentPulse 故事审签发布库：Python3 标准库 + SQLite 实现，无外部依赖。

## 模型

- **故事版本号**：每次成功变更（save 或状态流转）加 1；`expected_version` 必须匹配变更前的版本号，否则抛 `VersionConflict`。
- **内容修订号**：只在 `save` 时增加，从 1 开始，永不复用；回滚也产生新修订。
- **工作稿状态**：`Draft` → `InReview` → `Approved` → `Published`，逐级前进，不能跳级。
- **发布稿**：只有 `publish` 动作才替换对外可读的发布稿；继续编辑不影响已发布正文。
- **历史裁剪**：只保留最近 10 份修订；当前发布稿若更旧，额外保留这一份正文。

## 使用

```python
from talentpulse import (
    StoryStore,
    ACTION_SUBMIT, ACTION_APPROVE, ACTION_PUBLISH,
)

store = StoryStore("stories.db")   # 或 ":memory:"

# save：新故事以 expected_version=0 创建；之后每次携带变更前版本号
store.save("story-1", 0, body="第一版正文")

# transition：submit / approve / publish 逐级推进
store.transition("story-1", 1, ACTION_SUBMIT)
store.transition("story-1", 2, ACTION_APPROVE)
store.transition("story-1", 3, ACTION_PUBLISH)

# 继续编辑：产生新修订，工作稿回到 Draft，此前的批准资格失效
store.save("story-1", 4, body="第二版正文")

# 回滚：复制最近 10 份修订之一的正文，同样产生新修订（Draft）
store.save("story-1", 5, source_revision=1)

# read：版本、工作稿状态及正文、最近 10 份修订、当前发布稿
state = store.read("story-1")
# state = {
#   "story_id", "version", "status",
#   "draft_revision", "draft_body",
#   "revisions": [{"revision", "body"}, ...],   # 最近 10 份，新→旧
#   "published_revision", "published_body",      # 未发布时为 None
# }
```

## 错误

均继承 `TalentPulseError`：`StoryNotFound`、`VersionConflict`、
`InvalidTransition`、`RevisionNotFound`（回滚源不存在或已被裁剪）、
`MissingBody`。

## 测试

```sh
python3 -m unittest -v
```
