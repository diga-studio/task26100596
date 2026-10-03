# task26100596

TalentPulse 故事审签发布库：Python3 标准库 + SQLite，正文为不透明字符串，无外部服务依赖。

## 文件

- `talentpulse.py`：库实现（`StoryStore`，三个操作 `save` / `transition` / `read`）。
- `test_talentpulse.py`：自动化测试，直接调用库函数。

## 用法

```python
from talentpulse import StoryStore, ACTION_SUBMIT, ACTION_APPROVE, ACTION_PUBLISH

store = StoryStore("stories.db")   # 或 ":memory:"

v = store.save("story-1", 0, body="第一稿")                 # 创建（expected_version=0）
v = store.save("story-1", v.version, body="第二稿")         # 普通编辑，回到 Draft
v = store.save("story-1", v.version, source_revision=1)     # 回滚最近 10 份修订之一

v = store.transition("story-1", v.version, ACTION_SUBMIT)   # Draft -> InReview
v = store.transition("story-1", v.version, ACTION_APPROVE)  # InReview -> Approved
v = store.transition("story-1", v.version, ACTION_PUBLISH)  # Approved -> Published

view = store.read("story-1")  # 版本、状态、工作稿正文、最近 10 份修订、发布稿
```

## 语义要点

- 每次成功变更（含审核状态流转）故事版本号 +1；`expected_version` 必须匹配变更前版本。
- 内容修订号只在 `save` 时递增，从 1 开始、永不复用；回滚也产生新修订并置为 `Draft`。
- 保存新工作稿后，之前的待审/批准资格失效；迟到的批准请求因版本冲突被拒绝，已有发布稿仍可读。
- 历史只保留最近 10 份修订；当前发布稿若更旧则额外保留其正文，被裁剪的修订不能作为回滚来源。

## 运行测试

```sh
python3 -m unittest test_talentpulse -v
```
