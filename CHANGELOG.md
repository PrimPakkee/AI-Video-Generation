# Changelog

本文件用于记录 **AI Video Generation** 项目的版本更新历史。

## v0.4.9 - Prompt Mode 稳定性收尾与 AI Review 状态修复

### 二次热修（v0.4.9 hotfix）
- **`web/app.py` 补全 `import json`**：在文件顶部 import 区新增全局 `import json`。stale review 分支与 debug 接口都在运行时调用 `json.loads`，但之前仅有部分函数级局部 import，未覆盖 stale 分支；外层 `except Exception` 会把 `NameError` 吞掉，导致 stale 状态最终仍返回 `review: null`，让本次「stale 状态展示旧 review」的核心修复在某些路径下失效。
- **`scripts/run_stability_checks.py` 强化 v0.4.9 检查**：新增「`web/app.py` 必须存在顶层 `import json`」检查；缺失即判定 FAIL（而不是 WARN）。同时把 docs 中文文件名检查从 exact 路径改为版本前缀 glob（`docs/v0.4.6.9_*.md`、`docs/v0.4.6.8_*.md`），缺失降为 WARN，避免跨平台中文编码导致的误报；核心英文文件仍保持 FAIL 级别。

### 修复
- **AI Review stale 状态展示旧 review**：当 prompt 编辑后 review 进入 stale，`GET /api/history/{id}/review` 现在会返回最近一条可解析的旧 review 内容，前端 AI Review tab 可继续展示旧 review 并提示「内容已变化，需要重新 review」，不再只返回空状态。
- **AI Review debug 接口字段错误**：`GET /api/history/{id}/review/debug` 不再引用 `PromptHistory` 中不存在的字段（`prompt_id` / `version` / `prompt_hash`），改为返回 `id` / `slug` / `topic_group_id` / `version_number` / `prompt_text_length` / `prompt_text_sha1` 等真实字段，保证直接访问不再报 500。
- **/api/health SQLAlchemy 2.0 兼容**：将 `db.execute("SELECT 1")` 改为 `db.execute(text("SELECT 1"))`，避免在 SQLAlchemy 2.0 下因字符串 SQL 触发误报。
- **Preview 首次编辑空白**：进入 Preview 编辑模式时，若用户尚未编辑过 Preview，会回退到当前渲染内容（或基于 raw 重新生成），保证 textarea 不再出现空白；同时不影响 Raw / Overview 的现有编辑逻辑。

### 新增
- **AI Review Copy / Download**：在 AI Review tab 下点击 Copy 复制完整可读 markdown 文本；点击 Download 下载 `<slug>_ai_review_<时间戳>.md`。当当前没有 review 时给出明确提示，不会复制 / 下载空内容。Raw / Preview / Overview 的复制下载逻辑保持不变。
- **AI Review 清理脚本** `scripts/cleanup_ai_reviews.py`：默认 dry-run，支持 `--dry-run` / `--apply` / `--max-age-minutes` / `--backup`。仅将超过阈值的 `generating` 记录标记为 `failed`，写入清晰的 `error_message`，不删除 completed review，不修改 schema。`--backup` 会把数据库备份到 `data/backups/prompt_history_before_review_cleanup_YYYYMMDD_HHMMSS.db`。脚本不会被自动执行，备份与原数据库均不入 Git。

### 调整
- **稳定性检查脚本升级到 v0.4.9**：`scripts/run_stability_checks.py` 标题更新为 `Prompt Mode Stability Checks - v0.4.9`，新增 `check_v049_fixes()`（核对 `text("SELECT 1")` 写法、stale review 分支、debug 接口字段引用、cleanup 脚本是否存在），并把 `cleanup_ai_reviews.py` 加入 Python 编译检查列表。脚本不依赖外部 LLM API，不修改数据库。

### 注意
- 本次为 Prompt Mode 局部稳定性修复，未新增 Video Mode 相关功能，未引入新依赖，未修改数据库 schema、Prompt 主提示词、AI Review 评分标准或 NotebookLM 输出结构。
- 不提交 `.env`、`data/*.db`、备份 db、`outputs/`、`.venv/` 等任何敏感或本地文件。

## v0.4.8 - README 与 GitHub 仓库规范化

### 新增
- 新增中英文双语 README 项目说明。
- 明确项目当前 Prompt Mode 与未来 Video Mode 的产品路线。
- 补充核心功能说明，包括历史记录、版本管理、视图切换、AI Review、Regenerate Workflow 等。
- 补充本地运行方式和环境变量说明。
- 新增 CHANGELOG.md，用于后续记录每次版本更新。

### 调整
- 将项目描述从早期 Prompt 生成脚本，升级为 AI 教育短视频生成工作流工具。
- 明确当前阶段不直接生成视频，长期目标是接入 Seedance 2.0 / SeeDance 2.0 实现端到端视频生成。
- 强化 GitHub 仓库展示和版本管理规范。

### 注意
- 本次只更新项目文档，不修改后端、前端、数据库或生成逻辑。
- 不提交任何 API Key、本地 .env、虚拟环境、outputs 或本地数据库文件。
