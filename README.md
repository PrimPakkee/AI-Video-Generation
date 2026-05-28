# AI Video Generation

> AI-powered educational short-video prompt generation tool —— 现阶段聚焦 Prompt Mode，长期演进到 Video Mode 端到端教育短视频生成。

---

## 中文版

### 项目简介

**AI Video Generation** 是一个面向教育短视频场景的 AI 生成工作流工具。

- **当前短期目标**：构建一个 *AI-powered educational short-video prompt generation tool*，用户输入一个教育短视频题目，系统自动生成可直接复制到 **NotebookLM** 的高质量视频生成 Prompt。
- **当前核心阶段**：**Prompt Mode**。本项目当前阶段不直接生成视频文件，而是负责生成结构化、可控、可审核的视频创作 Prompt。
- **长期目标**：**Video Mode**。未来计划接入 **Seedance 2.0 / SeeDance 2.0** 等视频生成能力，实现「输入题目 → 自动生成 Prompt → 自动生成视频 → 网页端播放、预览、下载、管理」的端到端闭环。

> ⚠️ 当前阶段并未实现端到端视频生成。请明确区分：
> - ✅ 已实现：**Prompt Mode**（生成 NotebookLM Prompt）
> - 🔜 规划中：**Video Mode**（端到端视频生成）

---

### 适用平台与题材

- **平台**：TikTok、YouTube Shorts、Instagram Reels 等短视频平台
- **题材**：数学、逻辑、概率、商业数学、认知心理等教育类短视频
- **风格**：单人旁白、白底线稿、逻辑推理画面、短视频节奏、字幕与画面强约束

---

### 核心功能

#### A. Prompt Mode（当前主路径）

- 用户输入教育短视频题目。
- 系统生成结构化的 NotebookLM Prompt。
- 适用于 TikTok / YouTube Shorts / Instagram Reels 等短视频平台。
- 支持数学、逻辑、概率、商业数学、认知心理等教育类题材。

#### B. Topic-based Prompt Generation

根据用户输入题目生成完整视频创作 Prompt，Prompt 内容包含但不限于：

- 标题（Title）
- 目标平台（Target Platform）
- 目标受众（Target Audience）
- 视频时长（Duration）
- 核心概念（Core Concept）
- 题面（Problem Statement）
- 答案（Correct Answer）
- 推理过程（Reasoning Steps）
- 旁白稿（Narration Script）
- 字幕建议（Subtitle Segments）
- 视觉风格（Visual Style）
- 禁止事项与错误限制（Restrictions & Pitfalls）

强调：
- **单人旁白**、教育短视频风格、白底线稿、逻辑推理画面、短视频节奏；
- 字幕与画面的强约束；
- 系统当前生成的是 **NotebookLM 可直接使用的 Prompt**，而**不是视频文件本身**。

#### C. History Management（历史记录）

- 左侧历史题目列表。
- 支持历史记录查看。
- 支持搜索、置顶、收藏、删除、废纸篓、日期筛选等功能。
- 历史记录用于管理不同题目和不同生成结果。

#### D. Version Management（版本管理）

- 同一题目支持多个版本。
- 每次 Regenerate 会生成新版本。
- 用户可在 **Version 下拉框**中切换不同版本。
- 旧版本不会被覆盖，便于比较、回看、回退。

#### E. Prompt View Modes（视图切换）

- **Raw Text**：原始 NotebookLM Prompt，适合直接复制使用。
- **Preview**：结构化预览，便于快速检查 Prompt 各组成部分。
- **Overview**：中文内容概览，解释这条视频准备讲什么、怎么讲、画面如何呈现。
- **AI Review**：基于多维度质量维度对 Prompt 进行自动质检。

#### F. AI Review（自动质检）

对 Prompt 进行多维度质量评估，评价维度包括但不限于：

- 完整性
- 逻辑正确性
- NotebookLM 可用性
- 视觉可控性
- 短视频适配度
- 单人旁白约束
- 教育清晰度
- 风险与错误控制

支持：
- 各维度评分与点评
- 总分与整体评价
- 手动触发重新质检

> 当前 AI Review 仍在持续校准评分严格性和评价质量，避免出现过度宽松或模板化结果。

#### G. Regeneration Workflow（再生成流程）

- 用户可基于当前版本继续输入修改要求。
- 系统根据已有 Prompt 与新增要求生成新版本。
- Regenerate **不会覆盖旧版本**，而是生成新的 Version。
- Overview 中会说明本次新增或改动内容，帮助用户理解新版本相对旧版本的变化。

#### H. Local Web App（本地 Web 应用）

- **后端**：FastAPI
- **前端**：静态前端页面 + JS 脚本
- **数据库**：SQLite（本地）
- **访问方式**：本地运行后通过 `http://127.0.0.1:8000` 访问

> 当前项目以本地开发和原型验证为主，后续可扩展到云端部署。

---

### 项目结构

```
AI Video Generation/
├── README.md           # 项目说明（当前文件）
├── CHANGELOG.md        # 版本更新记录
├── requirements.txt    # Python 依赖
├── web/                # Web 应用入口、API、静态页面与前端脚本
├── scripts/            # Prompt 生成、LLM 调用、AI Review、数据修复与测试辅助脚本
├── templates/          # NotebookLM Prompt、QA checklist、storyboard 等模板文件
├── docs/               # 版本说明、产品文档、技术路线和功能设计记录
├── tests/              # 测试用例和测试数据
├── config/             # 配置示例文件（example.env 等）
├── data/               # 本地数据和示例数据
├── outputs/            # 本地生成结果目录
└── assets/             # 视觉资源和素材
```

> 注意：
> - `.env` **不会**提交到 GitHub，需要用户在本地自行配置；
> - `.venv`、`outputs/`、本地数据库文件等**不进入** Git 版本管理；
> - 不要在 README 或任何提交内容中写入真实 API Key、内部密钥或敏感地址。

---

### 本地运行

#### 1. 环境准备

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. 启动 Web 应用

```bash
python -m uvicorn web.app:app --reload --port 8000
```

#### 3. 访问

打开浏览器访问：

```
http://127.0.0.1:8000
```

---

### 环境变量说明

请在项目根目录创建本地 `.env` 文件（不要提交到 GitHub）。常用变量如下：

| 变量名 | 用途 |
| --- | --- |
| `AI_VIDEO_LLM_PROVIDER` | LLM provider 类型（如 OpenAI-compatible） |
| `AI_VIDEO_LLM_BASE_URL` | OpenAI-compatible API base URL |
| `AI_VIDEO_LLM_MODEL` | 用于 Prompt 生成和 AI Review 的模型名称 |
| `AI_VIDEO_LLM_API_KEY` | 本地配置的 API Key（**不应提交到 GitHub**） |
| `AI_VIDEO_LLM_MAX_TOKENS` | 模型最大输出 token 配置 |
| `AI_VIDEO_LLM_TIMEOUT` | 模型请求超时时间 |

> ⚠️ 任何真实 API Key、公司内部密钥、内部地址都不应出现在 README、提交记录或仓库任何文件中。

---

### 当前版本状态

- **当前版本阶段**：`v0.4.x — Prompt Mode stability and AI Review iteration`
- **已完成**：Prompt Mode 的核心功能（Prompt 生成、历史记录、版本管理、视图切换、AI Review、Regenerate workflow、本地 Web 应用）。
- **正在进行**：
  - AI Review 评分严格性持续校准
  - 编辑保存稳定性
  - 数据保护与回归测试
  - README 与 GitHub 仓库规范化
- **尚未完成**：端到端视频生成（Video Mode 属于长期路线）。

---

### Roadmap（规划路线）

| 版本 | 主要内容 |
| --- | --- |
| **v0.4.x** | Prompt Mode 稳定性修复、AI Review 校准、README 与 GitHub 仓库规范化 |
| **v0.5.x** | Prompt Mode 完整测试、体验优化、更多题材模板 |
| **v0.6.x** | Video Mode 原型设计 |
| **v0.8.x** | 接入 Seedance 2.0 / SeeDance 2.0 视频生成能力 |
| **v1.0.0** | 输入题目 → 自动生成 Prompt → 自动生成视频 → 网页端播放 / 下载 / 管理的完整闭环 |

未来可继续扩展：
- 用户登录系统
- 用户空间与权限
- 云端部署
- 视频生成任务队列
- 视频资产管理

---

## English Version

### Overview

**AI Video Generation** is an AI-powered workflow tool for creating educational short videos.

- **Short-term goal**: an *AI-powered educational short-video prompt generation tool*. The user provides an educational short-video topic, and the system generates a structured **NotebookLM** prompt that can be copied directly into NotebookLM to drive video generation.
- **Current stage — Prompt Mode**: the project currently focuses on generating high-quality, structured prompts. It does **not** generate video files at this stage.
- **Long-term goal — Video Mode**: integrate **Seedance 2.0 / SeeDance 2.0** so that users can input a topic and the system automatically produces a finished educational short video, with in-browser playback, preview, download, and management.

> Today's reality:
> - ✅ Implemented: **Prompt Mode** (NotebookLM prompt generation)
> - 🔜 Planned: **Video Mode** (end-to-end video generation)

### Target Platforms & Topics

- **Platforms**: TikTok, YouTube Shorts, Instagram Reels.
- **Topics**: math, logic, probability, business math, cognitive psychology, and other educational subjects.
- **Style**: single-narrator monologue, white background with line art, reasoning-driven visuals, short-form pacing, strong subtitle and visual constraints.

### Core Features

- **Prompt Mode** — generate a structured NotebookLM prompt from a user-supplied topic.
- **Topic-based Prompt Generation** — full prompt covering title, platform, audience, duration, core concept, problem statement, correct answer, reasoning steps, narration script, subtitles, visual style, and restrictions. The output is a NotebookLM-ready prompt, **not** a video file.
- **History Management** — left-side history list with search, pin, favorite, delete, trash, and date filtering.
- **Version Management** — multiple versions per topic; each Regenerate creates a new version without overwriting old ones; switch via the Version dropdown.
- **Prompt View Modes** — Raw Text (copy-ready), Preview (structured), Overview (Chinese summary of intent and visuals), AI Review (automated QA).
- **AI Review** — multi-dimensional automated quality check (completeness, logical correctness, NotebookLM usability, visual controllability, short-form fit, single-narrator constraint, educational clarity, risk control). Scoring strictness is still being calibrated.
- **Regeneration Workflow** — users can refine the current version with extra requirements; the system creates a new version, and the Overview explains what changed.
- **Local Web App** — FastAPI backend + static frontend + local SQLite database, accessible at `http://127.0.0.1:8000`.

### Project Structure

```
web/         FastAPI app, API routes, static frontend, JS scripts
scripts/     Prompt generation, LLM calls, AI Review, data tools
templates/   NotebookLM prompt, QA checklist, storyboard templates
docs/        Product docs, version notes, technical roadmap
tests/       Test cases and fixtures
config/      Example configuration files
data/        Local and sample data
outputs/     Local generation outputs
```

`.env`, `.venv/`, `outputs/`, and local database files are **not** committed to Git. Never put real API keys or sensitive addresses in this repository.

### Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn web.app:app --reload --port 8000
```

Then open `http://127.0.0.1:8000`.

### Environment Variables

Configure a local `.env` (do not commit):

- `AI_VIDEO_LLM_PROVIDER` — LLM provider type.
- `AI_VIDEO_LLM_BASE_URL` — OpenAI-compatible API base URL.
- `AI_VIDEO_LLM_MODEL` — model used for prompt generation and AI Review.
- `AI_VIDEO_LLM_API_KEY` — local API key (must not be committed).
- `AI_VIDEO_LLM_MAX_TOKENS` — max output tokens.
- `AI_VIDEO_LLM_TIMEOUT` — request timeout.

### Current Status

The project is in **v0.4.x — Prompt Mode stability and AI Review iteration**. Prompt Mode core features are in place. Ongoing work focuses on AI Review calibration, edit-save stability, data protection, regression tests, and repository normalization. End-to-end video generation is not yet implemented and remains a long-term Video Mode goal.

### Roadmap

- **v0.4.x** — Prompt Mode stability fixes, AI Review calibration, repository normalization.
- **v0.5.x** — Full Prompt Mode testing, UX polish, more topic templates.
- **v0.6.x** — Video Mode prototype design.
- **v0.8.x** — Integrate Seedance 2.0 / SeeDance 2.0 video generation.
- **v1.0.0** — Topic → prompt → video → in-browser playback, download, and management, end to end.

Future extensions: user accounts, user workspaces, cloud deployment, video job queue, and video asset management.
