# AI Video Generation

> 一个面向教育短视频场景的 AI 端到端生成工具。从 v0.4.x 的 NotebookLM Prompt
> 生成器，演进到 v0.6.8 的多用户视频生成平台 —— 输入题目，自动产出带英文旁白、
> 字幕、背景音乐、Apple 风格画面的 16:9 横屏教育短视频。

---

## 中文版

### 项目当前状态（v0.6.8.1）

**这个项目现在能做什么：**

- **登陆 / 注册 / 多用户隔离**：每个朋友都能注册自己的账号，由创始人在 Admin
  面板批准后才能使用；每人只看到自己的生成历史，互相不可见。
- **Image Video（本地静态图视频管线，主推线路）**：输入题目 → LLM 写脚本和分镜
  → gpt-image-2 真实生成每一张幻灯片底图 → Pillow 叠 title/caption/badge →
  edge-tts 生成英文旁白 → ffmpeg 合成视频 + 字幕烧录 + 背景音乐混音 → 浏览器内
  直接播放下载。一条完整流水线，全部自动跑完，无需任何人工干预。
- **Seedance Video（云端视频生成线路，备线）**：通过公司 APX 异步视频网关
  （底层 `doubao-seedance-2.0`）真实生成视频。已完成完整的 prompt 编译器、
  契约适配器、quality gate、submit/poll/download 全链路；通过
  `APX_VIDEO_ENABLED` 显式开启。
- **Prompt Mode（v0.4.x 老路径，仍然保留）**：生成 NotebookLM 可直接复制的
  结构化短视频 Prompt。多版本管理、AI Review 自动质检、收藏 / 置顶 / 回收站全部
  保留。
- **Apple 风格 UI**：登陆页全屏白底大字 hero，6 段式生成进度面板，深色 / 浅色
  双主题（系统主题 + 应用内手动切换都能跑），账号管理面板自助改邮箱 / 改密码。

> 当前阶段已经不只是 Prompt 生成器——**主推路径 Image Video 是真实端到端视频生成**，
> 调用真实图像 / TTS / FFmpeg，输出真实可播放的 mp4。

---

### 适用平台与题材

- **平台**：TikTok、YouTube Shorts、Instagram Reels 等短视频平台
- **题材**：数学、逻辑、概率、商业数学、认知心理等教育类短视频
- **风格**：单人英文旁白、Apple 风格简约画面、大字号屏幕文字、字幕烧录、
  16:9 横屏 1920×1080 @ 24fps
- **时长**：5 / 15 / 30 / 60 / 90 秒可选（默认 15s）

---

### 核心功能

#### A. 多用户体系（v0.6.8 / v0.6.8.1）

- **三库分离架构**：
  - `data/auth.db` —— users 表
  - `data/prompt_history.db` —— Prompt Mode 历史 + AI Review
  - `data/video_history.db` —— Video Mode 历史 + VideoJob
  - 跨库通过 `user_id` 逻辑外键关联，仓储层强制每个查询都带 `user_id`，
    任何越权访问统一返回 404（不泄漏存在性）。
- **Session 机制**：Starlette `SessionMiddleware`，HttpOnly + SameSite=Lax cookie
  （`aivg_session`，30 天有效），由 `SESSION_SECRET` 签名。Cookie 只携带
  `user_id`，每次请求从 `auth.db` 重新水合用户信息，支持即时撤销。
- **密码安全**：bcrypt 直接哈希（不依赖 passlib），首次登陆强制改密码。
- **创始人 + 审核制**：通过 `scripts/create_founder.py` 一次性 seed 创始人；
  其他人注册后状态为 `pending`，必须在 Admin 面板（右上角 user chip → Manage）
  被点 Approve 才能登陆。
- **账号自助管理**：Settings 弹窗的 Account 面板可改邮箱（带当前密码 +
  格式校验 + 撞号校验）、改密码（旧密码 + 新密码 + 确认），不需要找 admin。
- **登陆页 Apple 风格**（v0.6.8.1 重写）：全屏白底，正中 clamp(40-64px) 大字
  "AI Video Generator"，灰底输入框 + 深灰按钮（`#1d1d1f`，不是蓝色），
  深色模式自动反相，密码栏带眼睛切换。

#### B. Image Video 管线（v0.6.3 → v0.6.7，主推路径）

- **LLM 内容生成（v0.6.3）**：单次调用 `AI_VIDEO_LLM_*`（默认 gpt-5-chat）
  写完每一页幻灯片的 title / caption / highlight / visual_focus / badge +
  整段 narration_script_en + 中文 overview_cn。
- **真实图像生成（v0.6.4）**：每一张 slide 通过 `gpt-image-2` 真发到公司
  OpenAI-compatible 网关取真实底图（PNG，1792×1024 → 比例放大 + 中心裁剪
  到 1920×1080）。Pillow 只负责文字叠加（避免图像模型乱写字）。失败的 slide
  自动 fallback 到几何 placeholder，整段视频不崩。
- **背景音乐（v0.6.5）**：本地 `assets/bgm/` 库 + 操作员手写 manifest
  描述每首曲子的 mood / tempo / energy / instruments；LLM 在写内容时挑曲；
  ffmpeg `-stream_loop -1` + `volume=-15dB` + `afade=t=out:st=N-1:d=1`
  混音，TTS 旁白时自动 duck 到 -22dB。
- **TTS 旁白 + 字幕烧录（v0.6.7）**：
  - **edge-tts**（en-US-JennyNeural，免费，无需 API key）取代 ElevenLabs
    （免费层封禁 library voices）。
  - **图音强对应**：LLM schema 加 `narration_line` 字段，每页幻灯片必须
    对应一句 8-22 词的英文。edge-tts 的 SentenceBoundary 时间戳驱动
    每页幻灯片真实在屏时长，**句子 N 必须在第 N 张幻灯片在屏时被听到**，
    不再"音轨说一件事画面播另一件"。
  - **字幕烧录**：`BorderStyle=1`（无黑底框，只有外描边 + 阴影）+
    `Outline=5` 厚黑色白字 + `\pos(960,1010)` 锚定底部居中，1 行 / 2 行
    自动换行共享同一底边。
- **6 段式 Apple 风格进度（v0.6.6.1）**：Hero title + 全局进度条 +
  6 个阶段卡（Plan / Write content / Select music / Generate images /
  Render overlays / Compose video），实时显示真实后端 `stage.message`，
  深色浅色双主题。

#### C. Seedance Video 管线（v0.5.x → v0.6.2，备线）

- **Provider Contract Adapter（v0.5.5）**：Dry-run 契约层，把内容资产
  校验为"未来可被 Seedance 接收的载荷"。
- **Prompt Compiler（v0.5.6）**：离线编译器，把结构化资产编译为英文
  Seedance prompt 包（主 prompt + negative prompt + debug metadata），
  通过 `config/provider_profiles/seedance.json` 配置 must-include /
  negative-defaults。
- **APX 真实接口（v0.6.0）**：`web/video_providers/apx_seedance_provider.py`
  是项目内**唯一允许真实 video API 网络调用**的文件。`POST /v1/async/chat` →
  `GET /v1/async/results/{id}` 轮询 → 成功后下载 `response.video_url` 到
  `outputs/<slug>/video.mp4` → 前端通过本地路径播放。
- **Quality Gate（v0.6.2）**：default-deny 校验：CJK 字符 / `this topic` /
  `A` / `AB` / `BAB` / `Question` / `Answer` 等占位符 / 缺失 narration /
  缺失 scene plan → **绝不调用 APX**，job 写入
  `status=blocked_prompt_quality`，避免烧配额。
- **English-only 16:9 规范（v0.6.1）**：管线全链路硬绑定 1920×1080 横屏，
  output_language 锁 `en`，中文题目通过 `_english_topic_label` 转英文 subject。
- **APX key 卫生**：never logged / never written / never returned。Header 永不
  落入 `request_json` 快照。`download_video` 拒绝非 http(s)、清洗文件名、
  阻止 path traversal、`.part → rename` 原子下载。

#### D. Prompt Mode（v0.4.x，仍然保留）

- 用户输入教育短视频题目 → 生成结构化 NotebookLM Prompt。
- **Topic-based Prompt Generation**：包含标题 / 平台 / 受众 / 时长 /
  核心概念 / 题面 / 答案 / 推理过程 / 旁白稿 / 字幕建议 / 视觉风格 /
  禁忌项；强调单人旁白、白底线稿、短视频节奏、字幕画面强约束。
- **History Management**：左侧历史列表，支持搜索 / 置顶 / 收藏 / 删除 /
  废纸篓 / 日期筛选。
- **Version Management**：同一题目多版本，每次 Regenerate 生成新版本，
  旧版本不会被覆盖；下拉框切换版本。
- **Prompt View Modes**：Raw Text（NotebookLM 直接可用）/ Preview（结构化
  预览）/ Overview（中文内容概览）/ AI Review（多维度自动质检）。
- **AI Review**：完整性 / 逻辑正确性 / NotebookLM 可用性 / 视觉可控性 /
  短视频适配度 / 单人旁白约束 / 教育清晰度 / 风险控制。支持手动重新质检。
- **Regenerate Workflow**：基于当前版本继续输入修改要求，生成新版本，
  Overview 中说明本次新增或改动内容。

#### E. 本地 Web 应用

- **后端**：FastAPI + SQLAlchemy + SQLite
- **前端**：原生 HTML + JS（main.js 5290 行），Apple 风格 CSS
- **数据库**：3 个独立 SQLite 文件（auth / prompt / video）
- **访问方式**：本地运行后通过 `http://127.0.0.1:8000`，未登录自动跳转
  `/auth.html`

---

### 项目结构

```
AI Video Generation/
├── README.md                    # 项目说明（当前文件）
├── CHANGELOG.md                 # 版本更新记录（详细到每个 .x 版本）
├── requirements.txt             # Python 依赖
├── web/                         # FastAPI 应用 + 前端 + 各类 provider
│   ├── app.py                   # 主入口，路由注册（51 路由 + 10 auth 路由）
│   ├── auth.py                  # bcrypt + session + FastAPI 依赖
│   ├── image_video_pipeline.py  # Image Video 主管线（LLM / image2 / TTS / ffmpeg）
│   ├── video_asset_pipeline.py  # Seedance Video 内容资产管线
│   ├── audio_providers/         # edge-tts + bgm_selector
│   ├── image_providers/         # gpt-image-2 (apx_image2_provider.py)
│   ├── video_providers/         # Seedance prompt compiler + contract adapter + APX provider
│   ├── db/                      # 三个 ORM/Repository 模块（auth / prompt / video）
│   └── static/                  # 前端：auth.html / index.html / main.js / app_bootstrap.js / 等
├── scripts/                     # 一次性 CLI（create_founder / migrate_legacy / 稳定性检查）
├── templates/                   # NotebookLM Prompt + Seedance video asset prompt 模板
├── docs/                        # 每个版本的设计说明书 + 技术路线 + freeze spec
├── tests/                       # 测试用例 / fixture
├── config/                      # provider_profiles + example.env
├── data/                        # 本地三个 SQLite（不进 git）
├── outputs/                     # 本地生成结果（不进 git）
└── assets/                      # bgm/ 本地 BGM 库 + manifest.json
```

> **不进 Git**：`.env` / `.venv/` / `data/*.db` / `outputs/` / `*.mp4`。
> **永远不要**在 README、commit、issue、任何提交中写入真实 API Key、内部
> 密钥或公司内部地址。

---

### 本地运行

#### 1. 环境准备

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. 配置 `.env`

参考 `config/example.env`，至少需要配置：

```
# 必填：内容生成 LLM（gpt-5-chat 等 OpenAI-compatible 网关）
AI_VIDEO_LLM_PROVIDER=openai
AI_VIDEO_LLM_BASE_URL=https://...
AI_VIDEO_LLM_MODEL=gpt-5-chat
AI_VIDEO_LLM_API_KEY=sk-...

# 必填：v0.6.8 后多用户 session 签名秘钥
SESSION_SECRET=<32 字节随机十六进制>

# 选填：gpt-image-2 真实图像生成（不配则 fallback 到 Pillow 几何图）
APX_IMAGE2_ENABLED=true
APX_IMAGE2_BASE_URL=https://...
APX_IMAGE2_API_KEY=...
APX_IMAGE2_MODEL=gpt-image-2

# 选填:Seedance Video 备线（不配则只跑 Image Video）
APX_VIDEO_ENABLED=false
APX_VIDEO_API_KEY=...
```

生成 `SESSION_SECRET`：

```bash
python -c 'import secrets; print("SESSION_SECRET=" + secrets.token_hex(32))' >> .env
```

> ⚠️ **永远不要**把 `.env` 提交到 git。仓库 `.gitignore` 已经覆盖。

#### 3. v0.6.8 多用户首次启用（仅一次）

种创始人账号（默认密码会被打印到终端一次，首次登陆后强制改）：

```bash
python -m scripts.create_founder --email you@example.com
```

把现有所有历史记录回填到创始人名下（如果是从 v0.6.7 之前升级上来的）：

```bash
python -m scripts.migrate_legacy_to_founder
```

两个脚本都是幂等的，重复跑不会出问题。

#### 4. 启动 Web 应用

```bash
python -m uvicorn web.app:app --reload --port 8000
```

#### 5. 访问

```
http://127.0.0.1:8000
```

未登录会跳转到 `/auth.html`。其他人需要先注册，然后由创始人在 Admin 面板
（右上角 user chip 旁边的 Manage 按钮）点 Approve 才能登陆。

---

### 关键环境变量

| 变量名 | 用途 |
| --- | --- |
| `SESSION_SECRET` | **v0.6.8 必填**，session cookie 签名秘钥（32 字节十六进制） |
| `AI_VIDEO_LLM_PROVIDER` | 内容生成 LLM 类型（openai / openai-compat） |
| `AI_VIDEO_LLM_BASE_URL` | LLM 网关 base URL |
| `AI_VIDEO_LLM_MODEL` | 内容生成模型（默认 gpt-5-chat） |
| `AI_VIDEO_LLM_API_KEY` | LLM API key（**永远不要提交**） |
| `AI_VIDEO_LLM_TIMEOUT` | LLM 请求超时秒数 |
| `APX_IMAGE2_ENABLED` | 是否启用真实 gpt-image-2（false 则走 Pillow 几何图） |
| `APX_IMAGE2_API_KEY` | image2 API key |
| `APX_IMAGE2_CONCURRENCY` | image2 并发数（默认 4） |
| `APX_IMAGE2_TIMEOUT` | image2 单次请求超时秒数（默认 300） |
| `IMAGE_VIDEO_DISABLE_BGM` | 关闭 BGM（smoke 测试用） |
| `IMAGE_VIDEO_BGM_VOLUME_DB` | BGM 基础音量，默认 -15dB |
| `IMAGE_VIDEO_BGM_FORCE` | 强制指定一首 BGM 文件名 |
| `APX_VIDEO_ENABLED` | 是否启用 Seedance 真实接口 |
| `APX_VIDEO_API_KEY` | Seedance APX key |
| `APX_VIDEO_PROMPT_EXTEND` | 默认 false（避免被 prompt 改写） |

---

### 版本路线（已发布）

| 版本 | 主题 |
| --- | --- |
| v0.4.x | Prompt Mode 主路径稳定（NotebookLM Prompt 生成 / AI Review / 版本管理 / Download All） |
| v0.5.2 | Video Mode 独立框架与播放器界面 |
| v0.5.3 | Video Job / Provider / Asset 基础层 + 多阶段进度 |
| v0.5.4 | Video Content Asset Pipeline（LLM 写 7 个内容资产文件） |
| v0.5.5 | Seedance Provider Contract Adapter（dry-run 契约层） |
| v0.5.6 | Seedance Prompt Compiler + provider profile（离线编译器） |
| v0.6.0 | APX Seedance 真实接口集成（首次跑通真实视频生成） |
| v0.6.1 | English-only 16:9 横屏规范 + 5/15/30/60/90 时长选择器 + 进度条 |
| v0.6.2 | Seedance Prompt Quality Gate（拒绝占位符）+ 真实进度修复 |
| v0.6.3 | Static Image Video MVP（本地 Pillow + ffmpeg）+ Generation Method selector + Dark Mode 修复 |
| v0.6.4 | gpt-image-2 真实图像生成接入 + Pillow 文字叠加 + ThreadPoolExecutor 并发 |
| v0.6.5 | 本地 BGM 库 + LLM 选曲 + ffmpeg 同步混音 |
| v0.6.6 | Video 播放区只显示播放器（evidence 移到 Overview 底部）+ 首帧自动显示 + 点击切换播放 |
| v0.6.6.1 | Apple 风格 6 段式生成 UI（Hero + 全局进度条 + 6 个阶段卡） |
| v0.6.7 | edge-tts 旁白 + 字幕烧录 + 图音强对应（每页 narration_line） |
| **v0.6.8** | **多用户登陆 / 注册 / 创始人审核 + 数据隔离（当前版本）** |
| v0.6.8.1 | Auth UX 抛光：登陆页苹果风重写 + Settings 加 Account 面板 + 自助改邮箱 |

### 已知遗留问题

- **uvicorn `--reload` 会丢 in-memory runs**：`VIDEO_GENERATION_RUNS` 是
  进程内字典；`--reload` 在 run 进行中改代码会让前端轮询拿到 404。
  目前用 4 次容忍 + 清晰错误提示兜底。生产部署前需要把 run state 落到磁盘
  或 Redis。
- **founder@local 占位邮箱**：v0.6.8 setup 时如果不指定 `--email`，会用
  `founder@local` 占位。可以通过登陆后 Account 面板自助改成真实邮箱（v0.6.8.1
  支持）。

### 后续可能的方向（未排期）

- **生产化部署**：Run state 持久化、Redis、容器化。
- **Brute-force lockout / rate limit**：当前小范围分享所以没做，朋友圈外推
  之前需要补。
- **付费 TTS 升级**：edge-tts 免费够用，如果声线疲劳可以换 ElevenLabs
  paid（项目里曾经有 elevenlabs_tts.py，已删除，但实现方式记在 changelog 里）。
- **更多画风**：当前 5-style rotation，如果反馈说"风格单调"可以扩。
- **批量批处理 / Video Job 真实 retry / cancel**：单次生成已经稳，批处理
  还没做。
- **独立 Video Review 协议**：当前 AI Review 只覆盖 Prompt Mode；视频质检
  需要专门 schema。

---

## English Version

### Current State (v0.6.8.1)

**What this project does today:**

- **Login / register / multi-user isolation**: each friend signs up their own
  account; the founder approves them in the Admin panel; everyone sees only
  their own generation history.
- **Image Video pipeline (primary path)**: end-to-end. Topic in →
  LLM writes script + per-slide content → gpt-image-2 generates real
  background images → Pillow overlays title/caption/badge → edge-tts
  generates English narration → ffmpeg composes video with burnt-in
  subtitles + background music → playable mp4 in browser. Fully automated.
- **Seedance Video pipeline (alternate path)**: real cloud video generation
  through the in-house APX async video gateway (`doubao-seedance-2.0`).
  Full pipeline: prompt compiler → contract adapter → quality gate →
  submit/poll/download. Gated behind `APX_VIDEO_ENABLED`.
- **Prompt Mode (v0.4.x legacy, preserved)**: structured NotebookLM
  prompts, copy-ready. Multi-version, AI Review, favorite/pin/trash.
- **Apple-style UI**: full-bleed login hero, 6-phase Apple-style progress
  panel, dark/light themes covering both system preference and an in-app
  toggle, self-service Account panel.

> This is no longer "just" a prompt generator — the primary Image Video
> path is **real end-to-end video generation** with real image / TTS /
> ffmpeg calls and real playable mp4 output.

### Target Platforms & Topics

- **Platforms**: TikTok, YouTube Shorts, Instagram Reels.
- **Topics**: math, logic, probability, business math, cognitive psychology.
- **Style**: single English narrator, Apple-style minimalist visuals,
  large on-screen text, burnt-in subtitles, 16:9 1920×1080 @ 24fps.
- **Duration**: 5 / 15 / 30 / 60 / 90 seconds (default 15s).

### Architecture Highlights

- **Three-DB split**: `auth.db` / `prompt_history.db` / `video_history.db`.
  Cross-DB joins handled in app code via logical `user_id` foreign keys.
  Repository layer enforces ownership on every query — wrong owner returns
  None, never leaks existence.
- **Session auth**: Starlette `SessionMiddleware`, HttpOnly Lax cookie
  (`aivg_session`, 30 days), signed by `SESSION_SECRET`. Cookie carries
  only `user_id`; user state rehydrates from `auth.db` per request.
- **bcrypt** for password hashing; founder-approval gate; first-login
  forced password change.
- **Frontend bootstrap pattern**: `app_bootstrap.js` runs before main.js,
  patches `fetch()` to auto-redirect on 401, mounts the user chip and
  Admin modal — main.js (5290 lines) untouched.
- **Image Video stack**: gpt-image-2 (real PNG) → Pillow (text overlay) →
  edge-tts (narration with SentenceBoundary timing for image↔audio
  alignment) → ffmpeg (compose + ASS subtitles + BGM mix).
- **Seedance hygiene**: `apx_seedance_provider.py` is the ONLY file in
  the repo allowed to make real video API network calls. API key never
  logged, never persisted, never returned to frontend. Path-traversal
  protection on downloaded mp4s. Atomic `.part → rename` writes.

### Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Generate session secret + write to .env
python -c 'import secrets; print("SESSION_SECRET=" + secrets.token_hex(32))' >> .env

# 2. Configure AI_VIDEO_LLM_* in .env (required) and APX_IMAGE2_* (optional)

# 3. Seed the founder account (one-time)
python -m scripts.create_founder --email you@example.com

# 4. Backfill existing rows to founder (one-time, idempotent)
python -m scripts.migrate_legacy_to_founder

# 5. Start the server
python -m uvicorn web.app:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. You'll be redirected to `/auth.html`.
Log in as the founder, change the default password, and you're in.

### Environment Variables

See the [Chinese section](#关键环境变量) above for the full table —
the names are identical.

`.env` is gitignored. **Never commit real API keys.**

### Roadmap (shipped)

See the [Chinese section's version table](#版本路线已发布) above. Highlights:

- **v0.4.x** — Prompt Mode + AI Review (NotebookLM prompt generation only).
- **v0.5.x** — Video Mode framework, content asset pipeline, Seedance
  contract adapter, prompt compiler.
- **v0.6.0** — APX Seedance real provider — first end-to-end real video.
- **v0.6.1–v0.6.2** — English-only 16:9, duration selector, prompt quality
  gate.
- **v0.6.3–v0.6.5** — Static Image Video MVP, real gpt-image-2 integration,
  local BGM library + ffmpeg sync mix.
- **v0.6.6–v0.6.7** — Apple-style 6-phase progress UI, edge-tts narration,
  burnt-in subtitles, image↔audio strict alignment.
- **v0.6.8 / v0.6.8.1 (current)** — multi-user login/register/founder
  approval, Apple-style auth page, self-service Account panel.

### Known Issues

- **`uvicorn --reload` drops in-memory runs**: `VIDEO_GENERATION_RUNS`
  is process-local; saving a code edit mid-run causes a 404 on poll.
  Mitigated with 4-strike tolerance. Move to disk/Redis before deploying
  to production.
- **`founder@local` placeholder**: if `--email` was omitted during
  v0.6.8 setup, the founder gets a `founder@local` placeholder. Change it
  via the Account panel after logging in (v0.6.8.1).

### Possible Future Directions (not scheduled)

- Production hardening: persistent run state, Redis, containerization.
- Brute-force lockout / rate limit (small audience now, must add before
  wider sharing).
- Paid TTS upgrade (edge-tts → ElevenLabs paid voices) if narrator quality
  becomes a complaint.
- More art styles beyond the current 5-style rotation.
- Batch processing / real Video Job retry + cancel.
- Standalone Video Review protocol (current AI Review covers Prompt Mode
  only).
