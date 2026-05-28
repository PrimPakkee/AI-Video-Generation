# Prompt Mode 冻结说明书 (Freeze Spec)

> 文档版本：v0.4.10
> 适用范围：当前仓库的 **Prompt Mode**（不包含尚未实现的 Video Mode）
> 目的：明确当前 Prompt Mode 的能力边界、不可破坏的核心约定、与 Video Mode 的隔离原则，
> 以及未来 Claude Code 在该仓库做改动时必须遵守的红线。

本说明书是「读权威」：当任何后续修改与本文档冲突时，应当**先停止修改、提示风险、要求人工确认**，
而不是默默改动核心结构。

---

## 1. Prompt Mode 当前能力清单

下列能力构成截至 v0.4.10 的 Prompt Mode 稳定能力面。任何「不破坏现有用户路径」的小修复
都必须保证下面这些能力**继续可用**。

### 1.1 Prompt 生成与查看
- 用户可以基于一个题目（topic）生成一份可直接复制到 NotebookLM 的 Prompt。
- 单条 Prompt 在前端有四种视图：
  - **Raw**：原始 Prompt 全文，可直接复制给 NotebookLM 使用。
  - **Preview**：基于 Raw 渲染的可读分段视图。
  - **Overview**：中文内容概览（`overview_cn`），便于产品/教研快速判断主题。
  - **AI Review**：对该 Prompt 的多维度质量评估表（`v0.4.6.9_strict` 评分体系）。
- Raw / Preview / Overview / AI Review 之间可自由切换；切换不触发 LLM 调用。

### 1.2 历史与版本管理
- 每一次生成会写入一条 `prompt_history` 记录，并按 `topic_group_id` + `version_number`
  归入版本组。
- 历史侧边栏支持：
  - 置顶 (`is_pinned`)、收藏 (`is_favorite`)、软删除 (`deleted_at`) 与回收站；
  - 同一题目多版本切换；
  - 编辑 Prompt 后保存为新版本；
  - Regenerate 工作流：基于现有版本和反馈生成新版本，并在 Overview 下方展示
    `change_summary_cn`「本次生成新增或改动的内容」。

### 1.3 AI Review
- 仅在用户主动点击 **Re-review** 时触发 LLM 调用；切换历史记录、切 tab 都不会自动触发。
- 评分采用固定 schema 版本 `v0.4.6.9_strict`，配套硬上限 / 校准规则。
- 状态机：`none` / `generating` / `completed` / `failed` / `stale`，前端会展示对应 UI。
- `stale` 状态下仍展示最近一条可解析的旧 review，并提示「内容已变化，需要重新 review」。
- 提供清理脚本 `scripts/cleanup_ai_reviews.py`，默认 dry-run，仅把超时 `generating`
  记录标记为 `failed`，不删除 `completed` 数据。

### 1.4 复制 / 下载
- 单视图 Copy / Download：
  - Raw → `*.txt`，原始 Prompt 全文；
  - Preview → `*.txt`，可读分段文本；
  - Overview → `*.txt`，中文概览，且**包含** `change_summary_cn`「本次生成新增或改动的内容」段落（v0.4.10 起统一）；
  - AI Review → `<slug>_ai_review_<时间戳>.md`，markdown 表格。
- Download All：`<slug>_prompt_package.zip`，至少包含
  `raw_text.txt` / `preview.txt` / `overview.txt` / `ai_review.md` / `metadata.json`。
- 当 AI Review 不存在时，`ai_review.md` 内容为占位文案；`stale` 时在头部追加提示。

### 1.5 本地化与隐私
- 项目仅在本地运行（FastAPI + SQLite + 静态前端）。
- `metadata.json` 等导出物不包含 API key、`.env` 内容、密钥或任何敏感配置。
- 数据库 `data/prompt_history.db` 与 `data/backups/*.db` **不入 Git**。

---

## 2. 不可破坏的核心约定 (Inviolable Principles)

下面任何一条原则被破坏，都视为 Prompt Mode 严重回归。

### 2.1 Raw Text 必须保持「干净」
- Raw 视图、Raw 复制、Raw 下载、Download All 中的 `raw_text.txt` 必须始终是**可直接粘贴到
  NotebookLM** 的 Prompt 全文。
- **严禁**在 Raw 中混入：Overview、change_summary、AI Review、UI 提示语、调试信息、版本备注等任何「非 Prompt 内容」。
- Overview Copy/Download 中的「本次生成新增或改动的内容」**只能出现在 Overview 链路**，
  **不得回流到 Raw**。

### 2.2 数据库 schema 与主数据结构冻结
- 不得修改 `web/db/models.py` 中已有的核心表与字段：
  `prompt_history.*`、`prompt_reviews.*` 的字段名、类型、约束。
- 不得新增/删除字段以「顺手」实现新功能；新字段必须配合明确的迁移脚本与版本号说明。
- 历史记录的主结构（`topic_group_id` + `version_number` 版本管理、软删除、置顶、收藏、回收站）冻结。

### 2.3 Prompt 生成主提示词冻结
- `scripts/llm_topic_enhancer.py` 中用于生成 NotebookLM Prompt 的主提示词
  与字段集合（`overview_cn`、`reasoning_steps`、`subtitle_segments`、`storyboard_scenes`、
  `core_visual_consistency`、`notebooklm_specific_instructions` 等）冻结。
- 不得在 Prompt Mode 修复中「顺手」改写主提示词、压缩字段、调整语气或加入新指令。

### 2.4 AI Review 评分协议冻结
- AI Review 使用 `v0.4.6.9_strict` 评分体系；维度、权重、硬上限、校准规则不得调整。
- 仅当用户点击 **Re-review** 时才能 POST `/api/history/{id}/review?force=true`。
- 任何 tab 切换、历史切换、自动刷新均不得触发 LLM 调用。

### 2.5 NotebookLM 输出结构冻结
- NotebookLM 最终消费的 Prompt 字段集合与 markdown 段落顺序冻结，保证既有渠道（剪映 / NotebookLM 工作流）不破。

### 2.6 用户操作语义冻结
- Regenerate 工作流：必须在 `change_summary_cn` 中说明本次相对旧版的改动，并保留旧版本不被覆盖。
- 收藏 / 置顶 / 软删除 / 回收站 / 还原的语义保持不变；不得改成硬删除或不可逆操作。

### 2.7 隐私与安全
- 严禁把 `.env`、`data/*.db`、`data/*.db-shm`、`data/*.db-wal`、`data/backups/*.db`、`outputs/`、
  `__MACOSX/`、`.DS_Store`、任何 API key 或真实密钥提交到 Git。
- 严禁让任何导出物（zip、metadata.json、日志）泄露上述内容。

---

## 3. 与 Video Mode 的边界 (Mode Boundary)

Video Mode 是**未来路线图**，目前仓库中**没有也不应当出现** Video Mode 的实现。
Prompt Mode 与 Video Mode 必须严格隔离。

### 3.1 Prompt Mode 不做的事
- 不调用任何视频生成模型（Seedance 2.0 / SeeDance 2.0 等）。
- 不发起任何指向视频生成 API、远程 GPU、视频任务队列的网络请求。
- 不在数据库中创建 `video_*`、`render_*`、`job_*` 表或字段。
- 不在 UI 上出现「生成视频」「Render」「Submit Video Job」等入口。
- 不在导出包中混入 mp4 / mov / 视频 storyboard 之外的视频产物。

### 3.2 当前与未来的接口约定
- Video Mode 真正落地之前，`metadata.json` 中可以**可选地**包含
  `export_schema_version` 等字段，但不得包含暗示视频任务的 ID/URL/Token。
- 如未来确实接入 Video Mode：
  - 必须以新 endpoint、新表、新页面承接，**不得复用** `/api/history/{id}/...` 的语义；
  - 必须保留 Prompt Mode 的全部既有路径；
  - 必须更新本文档第 1、3 节，并产出独立的 Video Mode 设计文档。

### 3.3 修改判定
- 任何提到 "video" / "seedance" / "render" / "job queue" 的代码改动，
  在 Prompt Mode 修复任务里都默认是**越界**，需要先停下来与维护者确认。

---

## 4. Claude Code 修改约束 (Modification Constraints)

未来在该仓库执行任务的 Claude Code（或任何自动化代理）必须遵守以下约束。
违反任何一条，应当主动停下来报告而不是继续。

### 4.1 任务范围控制
- 仅修改用户在任务中**显式列出的文件**；其余文件即使发现「问题」也只汇报、不擅自改。
- 不擅自重构未列出的模块（如 `web/db/`、`scripts/llm_topic_enhancer.py` 主提示词）。
- 不为了「顺手清理」而删除未使用的字段、函数、注释、文件。

### 4.2 禁止接触清单
绝对不可修改、读取后写出、或提交以下内容：
- `.env`、任何 `*.env*` 文件；
- `data/*.db`、`data/*.db-shm`、`data/*.db-wal`、`data/backups/*.db`；
- `outputs/` 下的任何历史生成产物；
- 任何 API key / token / 密钥；
- `__MACOSX/`、`.DS_Store`、`.venv/` 等环境与系统文件。

### 4.3 严禁行为
- 严禁自动 `git add` / `git commit` / `git push` / `git tag` / `git rebase`（除非用户在当前任务中明确授权）。
- 严禁修改 `requirements.txt` 引入新依赖来「方便实现」，应优先使用现有依赖。
- 严禁绕过 pre-commit / hook（不要使用 `--no-verify` 等）。
- 严禁删除已有版本的文档（`docs/v0.4.x_*.md`）或 CHANGELOG 历史条目。

### 4.4 验证义务
每次完成 Prompt Mode 修改后，至少跑通以下自检（脚本不调用外部 LLM、不写数据库）：
- `python3 -m py_compile` 全部 Python 文件；
- `node --check` 全部前端 JS 文件；
- `python scripts/run_stability_checks.py` 全绿（FAIL=0）；
- `python scripts/cleanup_ai_reviews.py --dry-run` 可正常输出；
- `git status` 检查未引入受保护文件。

### 4.5 报告格式
完成任务后必须按以下结构报告：
1. **本次版本**（如 v0.4.10）；
2. **修改文件清单**（每个文件一行说明）；
3. **修复点说明**（一一对应用户列出的问题）；
4. **自测结果**（py_compile / node --check / stability checks / cleanup dry-run / git status）；
5. **保护性说明**（确认未触碰禁止清单、未引入 Video Mode、未修改 Prompt 主提示词与评分协议）。

### 4.6 冲突与歧义
- 若用户当次任务与本文档冲突，**先暂停修改**，明确指出冲突点并请求确认；
- 不得以「用户说什么就做什么」为由覆盖第 2 节核心约定（Raw 干净、schema 冻结、评分协议冻结、Video 隔离、隐私与安全）。

---

**维护说明**：本文档随重大版本（涉及导出结构、tab 主逻辑、评分协议、Video Mode 接入）更新；
小修小补不强制更新本文档，但需在 CHANGELOG 中说明。
