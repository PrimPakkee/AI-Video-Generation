# Changelog

本文件用于记录 **AI Video Generation** 项目的版本更新历史。

## v0.6.4 - Image2 接入（gpt-image-2 真实图像生成）

> v0.6.4 把 Image Video 路线从纯 Pillow 几何图升级成 gpt-image-2 真实图像生成 +
> Pillow 文字叠加。每张 slide 的英文 image_prompt 真发到公司 OpenAI-compatible
> 网关的 `images/generations` endpoint，PNG 作底图，title/caption/badge 仍由
> Pillow 干净叠加（防图像模型乱写字）。本版本仍**不**调用 Seedance / APX video /
> TTS，**不**修改 .env。详见
> [`docs/v0.6.4_image2_integration.md`](docs/v0.6.4_image2_integration.md)。

### 新增
- `web/image_providers/__init__.py` / `base.py`：`ImageProvider` 抽象 + `RenderedImage`
  dataclass + `ImageProviderError`。base 模块本身不 import requests。
- `web/image_providers/apx_image2_provider.py`：v0.6.4 中**唯一允许真发网络**的文件。
  `requests` lazy import，header 探测真实 PNG width/height，base64 解码，按 v0.6.0
  Seedance provider 的 hygiene 标准 — API key 不入库、不写文件、不返回前端。
- `IMAGE_VIDEO_RUN_STAGES` 新增 `generate_slide_images` 阶段（位于 `write_slide_content`
  之后、`render_slide_overlays` 之前），真实计时。
- Generation Evidence 面板新增 `Image2 called` / `Image2 success / total` 行。
- `IMAGE_VIDEO_DISABLE_IMAGE2=1` 短路（smoke 默认开），`--with-image2` smoke flag。
- `scripts/run_stability_checks.py` v0.6.4 升级 + 新增 `check_v064_image2_integration`：
  lazy import / 不 top-level import requests / env 引用 / 阶段名 / evidence 字段
  全套静态校验。
- 新增 `docs/v0.6.4_image2_integration.md`。

### 行为
- 单张 image2 失败 fallback 到 Pillow 几何图（per-slide 粒度，整段视频不崩）。
- pipeline 使用 `ThreadPoolExecutor`（默认 concurrency=4，可由 `APX_IMAGE2_CONCURRENCY`
  调）。20 张 slide 大约 5 分钟（vs 串行 20 分钟）。
- image2 PNG（默认 1792×1024）通过 `_resize_to_canvas` 比例放大 + 中心裁切到
  1920×1080；Pillow 在底图上画半透明白带 + title/caption + badge + 进度脚标。
- `media_api_called` 现在会因 image2 真发翻 true（之前 v0.6.3 永远 false）；
  `network_call_performed` = `image2 真发 OR LLM 真发`；`llm_network_call_performed`
  保持 LLM-only 子集。
- `Stage 4`（`generate_slide_images`）的耗时反映真实 image2 等待时间。
- 智能 Stage 重命名：原 `render_slide_images` → `render_slide_overlays`（更准确反映
  现在这一步只是叠字而不是画几何图）。

### 不做
- 不调 Seedance / APX video / TTS / subtitle burn-in。
- 不让 image2 自己写 on-screen 文字（仍由 Pillow 叠加，避免模型拼写错误）。
- 不修改 .env（操作员自己加 APX_IMAGE2_* 4 行）。
- 默认 smoke 仍纯本地（`IMAGE_VIDEO_DISABLE_LLM=1` + `IMAGE_VIDEO_DISABLE_IMAGE2=1`）。

## v0.6.3 - Static Image Video MVP + Generation Method Selector + Dark Mode Fix

> v0.6.3 在保留 v0.6.2 Seedance Video 链路的同时，**新增**一条本地静态图合成视频
> 的生成路线 **Image Video**（不调用 APX / Seedance / Image2 / TTS）。每张幻灯片
> 的文案与中文整体内容介绍由 `AI_VIDEO_LLM_*`（默认 gpt-5-chat）实时生成，确保
> 内容紧扣题目；LLM 失败时自动 fallback 到本地静态模板，视频依然能合成。
> 同时修复 dark mode 下大量白色色块问题。本版本**不**真实调用 APX，**不**修改
> `.env`，**不** git add / commit / push。已废弃旧设计：本版本**不**做强制
> Preflight、不做 Submit-to-Seedance 二次确认。

### 新增
- `web/image_video_pipeline.py`：本地 Pillow + FFmpeg 静态图合成视频管线，
  导出 `resolve_slide_count` / `generate_image_video_package`。新增
  `_call_llm_for_slide_content` 调用 `AI_VIDEO_LLM_*`（gpt-5-chat），按 schema
  返回每张 slide 的 `title / caption / highlight / visual_focus / badge` 以及
  `video_title_en / hook_question_en / answer_en / overview_cn`。LLM 失败时
  fallback 到静态模板，视频仍可生成。`outputs/<slug>/image_video/` 多出
  `llm_debug.json`、`llm_slide_content.json`、`overview_cn.txt` 三个文件。
- 首页 Video Mode `Generation method` selector（`Seedance Video` 默认 /
  `Image Video` 新增）。
- `VideoHistory.generation_method` 列 + 启动时 idempotent `ALTER TABLE` 迁移。
- `web/app.py`：`VideoGenerateRequest.generation_method` 字段、
  `_normalize_generation_method` 校验、Image Video 后台 worker，
  `/api/video/generate` 与 `/api/video/generate/start` 都按 method 分发。
- 新增 `Generation Evidence` 面板，明确显示
  `Real API call: No / Seedance Called: No / APX Called: No / Image2 Called: No /
  TTS Called: No`。
- 完整的 `body.dark-mode` 规则覆盖 input / duration selector / method selector /
  output card / Raw Text / Preview / Overview / Provider Evidence /
  Generation Evidence / video player / sidebar / 历史列表。
- `scripts/smoke_image_video_pipeline.py` 离线 smoke test，5/15/30/60/90 五种
  时长各跑一次。
- `scripts/run_stability_checks.py` 升级到 `v0.6.3`，新增
  `check_v063_image_video_mvp()`。
- `docs/v0.6.3_static_image_video_mvp.md`。
- `requirements.txt` 新增 `Pillow>=10.0.0`。

### 行为
- Slide 数严格按时长决定：5s=3 / 15s=4–6 / 30s=6–8 / 60s=10–15 / 90s=20–25。
  区间内按 title 复杂度（词数 / 复杂关键词 / 标点 / 中文字符）取低/中/高值。
- Image Video 输出 `outputs/<slug>/image_video/{slide_plan.json,
  overlay_plan.json, slides/slide_NN.png, concat.txt, ffmpeg_command.txt,
  final_video.mp4}`。
- FFmpeg 缺失时 pipeline 返回 `route_status="failed"` + 明确错误
  `"FFmpeg is required for Image Video composition. Please install ffmpeg."`，
  不抛异常。
- v0.6.2 的 Seedance quality gate / `prompt_extend=false` / 真实 run store /
  Provider Evidence / 5/15/30/60/90 时长选择器 / 16:9 English-only 规范全部保留。

### 不做
- 不调用 APX / Seedance / Image2 / TTS。`AI_VIDEO_LLM_*`（gpt-5-chat）**不在**
  禁止列表中——本身就是项目内现有的内容生成模型，被 Prompt Mode、Seedance Video
  Content Asset Pipeline 共用。
- 不做 subtitle burn-in / AI QA / batch / 多 provider 大重构。
- 不做强制 Preflight、不做 Submit-to-Seedance 二次确认。
- 不修改 .env。不 git add。不 git commit。不 git push。
- 不允许 `.env` / `data/*.db` / `outputs/` / `*.mp4` / `__MACOSX` / `.DS_Store`
  进入 git。

## v0.6.2 - Seedance Prompt Quality Gate + English Compiler + Real Progress Fix

> v0.6.2 不重接接口。APX/Seedance 真实接口已经在 v0.6.0 接通并成功返回过
> `video_url`、下载过 `video.mp4`。本次修复的是**真正提交给 Seedance 的
> `submit_payload.prompt` 质量**：禁止 `this topic` / `A` / `AB` / `BAB` /
> `Question` / `Answer` / `Why?` / `Human review required` / 中文字符 /
> 空 narration / 空 scene 进入真实 APX 调用。本次仍**不调用真实 APX、不生成
> 真实视频、不修改 .env、不引入 Celery / Redis / RQ**。

### 新增 / 变更
- Schema bump：
  - `seedance_prompt_compiler_v0.6.1 → v0.6.2`
  - `seedance_prompt_profile_v0.6.1 → v0.6.2`
  - `seedance_prompt_debug_v0.6.1 → v0.6.2`
  - `video_assets_v0.6.1`、`config/provider_profiles/seedance.json` 不变。
- `web/video_providers/seedance_prompt_compiler.py` 重写：
  - 新增 `normalize_seedance_prompt_input(...)`，把上游内容资产（topic_analysis /
    reasoning / video_script / storyboard / provider_request_preview）统一抽取为
    一份 English-only 结构化输入；任一字段缺失会写入 `quality_block_reasons`，
    绝不再 fallback 成 `this topic` / `A` / `AB` / `BAB`。
  - 新增 `BANNED_PLACEHOLDER_STRINGS` / `BANNED_STANDALONE_TOKENS` /
    `REQUIRED_PROMPT_KEYWORDS` / `GENERIC_OST_FRAGMENTS` 公开常量。
  - `build_seedance_prompt(...)` 改为紧凑的 Task / Format / Voiceover /
    Core explanation / Scene plan / Allowed on-screen text only / Text rules /
    Motion / Negative constraints / Final rules 段落格式；删除「does not yet
    generate audio」相关文案，改为正向要求 `Use one clear English narrator
    voiceover.`；保留 `Mandatory duration: <n> seconds. Ignore any conflicting
    duration instruction from earlier sections.`、`Single narrator monologue
    only.`、`max 8 English words`、`only render the exact provided on-screen
    text fragments`、`16:9 landscape, 1920x1080`。
- 新增 `validate_seedance_prompt_quality(prompt, compiled_payload, duration_seconds)`
  Default-deny gate。检测：CJK；banned placeholder；standalone A/AB/BAB；缺失
  required keywords；normalized_input 缺失字段；duration 不一致。
- `web/app.py` 真实 APX submit 前调用 quality gate，失败时创建
  `VideoJob.status="blocked_prompt_quality"` /
  `stage="blocked_before_submit"` / `progress=0` / `response_payload.prompt_quality`，
  `VideoHistory.video_status` 同步映射 `blocked_prompt_quality`，绝不调用 APX。
  `APX_VIDEO_ALLOW_FALLBACK_SUBMIT=true` 是唯一覆盖。
- `web/video_providers/apx_seedance_provider.py`：`DEFAULT_PROMPT_EXTEND = False`；
  `config/example.env` 推荐 `APX_VIDEO_PROMPT_EXTEND=false`，默认 duration 推荐 15。
- `web/app.py` 新增真实进度 run store：
  - `POST /api/video/generate/start` 启动后台线程并返回 `run_id`；
  - `GET /api/video/generate/runs/{run_id}` 返回每个 stage 的真实时间。
  - 9 个真实阶段：`validate_topic` / `build_llm_content_package` /
    `parse_package_output` / `create_video_history_record` /
    `build_video_assets` / `compile_seedance_prompt` /
    `validate_prompt_quality` / `submit_video_job` / `open_video_status_panel`。
- 前端：彻底删除 `advanceVideoGenerationProgress` + 1.5 秒 setInterval 假动画。
  改为 `startVideoRunPolling(runId, onComplete, onFailure)`，每秒轮询真实 stage。
- Video Output 进度覆盖层背景改为 `#0f172a` 实色，杜绝上一条视频从 overlay
  下方漏出；新增 `blocked_prompt_quality` 状态文案；
  `clearVideoPlayerStateForRecordSwitch()` 在新任务开始与历史切换时调用。
- 新增 Provider Evidence Summary 面板（`#provider-evidence-panel`）：
  Provider / Real API call / Provider Job ID / Job status / Remote video URL
  received（仅 Yes/No） / Local video downloaded / Local video available /
  Local file（仅文件名） / Duration / Prompt quality / Block reason。绝不
  暴露 API key、完整 signed video URL、绝对路径或请求 headers。
  数据来自 `/api/video/history/{id}/provider-contract` 新增的 `provider_evidence`
  字段。
- `templates/video_asset_prompt_template.md` 重写为 v0.6.2 强约束模板：
  要求 LLM 输出 `english_subject` / `english_title` / `english_question` /
  `correct_answer` / `narration_script` /
  `scene_plan[*].visual_en|narration_en|on_screen_text_en`；
  禁止 `this topic` / `A` / `AB` / `BAB` / 单独 `Question`/`Answer`/`Why?`；
  无法确定时设 `topic_analysis.needs_human_review=true` 而不是用占位符。
- `scripts/run_stability_checks.py` 升级到 `STABILITY_CHECKS_VERSION = "v0.6.2"`：
  新增 `check_v062_prompt_quality_gate()`；调整 v0.5.4 / v0.6.1 旧检查以接受
  v0.6.2 的真实 stage keys / 新版本号 / `pr.get("target_duration_seconds")` 写法 /
  `config/example.env` 编辑豁免。
- 文档：新增 `docs/v0.6.2_seedance_prompt_quality_gate.md`；删除未追踪的
  `docs/v0.6.1_english_landscape_video_spec.md`（内容已合并到 v0.6.2 spec）。

### 不变项 / 不允许的事
- 不修改 NotebookLM Prompt 主模板。
- 不修改 Prompt Mode 数据库 schema。
- 不修改 AI Review 评分标准。
- 不引入 Celery / Redis / RQ。
- 不修改 `.env`，不读取 / 打印 `APX_VIDEO_API_KEY`。
- 不真实调用 APX、不真实 poll、不真实下载、不生成 mp4。
- 不 `git add` / `git commit` / `git push`。
- 不提交 `data/*.db` / `outputs/` / `*.mp4` / `.env`。

## v0.6.1 - English-only 16:9 Landscape Video Spec & Progress UX Hardening

> 本版本固化 Video Mode 的输出形态：所有最终产物（Seedance prompt、旁白、
> on-screen text、`video_goal`）必须是英文；视频画幅强制为 **16:9 横屏**
> （`1920x1080`），不再使用 9:16 竖屏；首页新增视频时长选择器（5 / 15 /
> 30 / 60 / 90 秒，默认 15 秒），管线按时长档位决定场景数；视频播放区
> 新增覆盖式 0–100% 进度条；切换历史记录时清理上一条的视频残留。本版本
> 仍**不调用真实 APX、不生成真实视频**，所有 hard prohibitions 沿用 v0.6.0。

### 新增 / 变更
- Schema bump：`video_assets_v0.6.0 → v0.6.1`；
  `seedance_prompt_compiler_v0.5.6 → v0.6.1`；
  `seedance_prompt_profile_v0.5.6 → v0.6.1`；
  `seedance_prompt_debug_v0.5.6 → v0.6.1`。
  `VIDEO_ASSETS_LEGACY_SCHEMA_VERSION` 升至 `video_assets_v0.6.0`。
- 强制 16:9 横屏 / 1920x1080 / 24fps：`video_asset_pipeline.py` 与
  `seedance_prompt_compiler.py` 中的 `DEFAULT_ASPECT_RATIO`、
  `DEFAULT_RESOLUTION`、`DEFAULT_ORIENTATION`、provider request preview
  均硬绑定为 16:9 / 1920x1080 / landscape；`config/provider_profiles/seedance.json`
  对应字段同步。
- 强制英文输出：新增 `_strip_cjk` / `_english_topic_label` 工具；
  `output_language` 始终为 `"en"`；`input_language` 单独记录在 manifest 上；
  `on_screen_text` 在脚本、场景、fallback、compiler 全链路过 `_english_topic_label`，
  确保最大 8 个英文单词、无 CJK、不会把中文题目泄漏到屏幕文字。
- 新增 5 / 15 / 30 / 60 / 90 五个时长档位：`build_duration_profile` 重写为
  `hook_only_5s` / `quick_answer_15s` / `standard_short_30s` /
  `full_explanation_60s` / `extended_explanation_90s`，每档对应独立的
  scene_count / word_count 区间。`DEFAULT_DURATION_SECONDS` 由 5 改为 15。
- `web/app.py` 的 `/api/video/generate` 与 `/api/video/history/{id}/regenerate`
  接受可选 `duration_seconds` 字段，回落顺序：请求 → 历史记录 → 默认 15。
- 编译器 prompt 强化：增加 “# Seedance Educational Explainer Video Prompt
  (16:9)” 头部、`## Format and Style`、`## Allowed On-screen Text`、
  `## Negative Constraints and Final Rules` 段落；明确 `single narrator
  monologue`、no two-host / no podcast / no interview / no dialogue、
  English on-screen text only、no Chinese characters、no misspelled、
  only render the exact provided fragments、`Mandatory duration: N seconds`、
  `Ignore any conflicting duration, language, aspect-ratio or format
  instruction from earlier content`。
- 前端：
  - `index.html` 新增 `#video-duration-selector`（5 / 15 / 30 / 60 / 90，默认
    高亮 15s）；新增 `#video-progress-overlay` 覆盖在 `#video-player-shell` 上。
  - `style.css` 新增 `.video-duration-selector` / `.video-duration-option` /
    `.video-progress-overlay` 系列样式。
  - `main.js` 新增 `setVideoDurationSelectorActive` / `snapVideoDuration` /
    `getCurrentVideoDurationSeconds`、`renderVideoOverlayProgress`、
    `clearVideoPlayerStateForRecordSwitch`；`/api/video/generate` 与
    `/api/video/history/{id}/regenerate` 请求体中带上 `duration_seconds`；
    切换历史记录时清空 `<video>.src` 与 `currentVideoRecord` /
    `currentVideoJob` 上的视频残留路径。
  - 状态 → 进度映射：`submitted:20` / `pending:35` / `running:60` /
    `downloading:85` / `succeeded:100`（隐藏）/ `failed:100` /
    `blocked_fallback_prompt:100` / `provider_not_configured:85`。
- 稳定性脚本：`scripts/run_stability_checks.py` 升级到 v0.6.1，新增
  `check_v061_english_landscape()`，覆盖约 50 项子断言。

### 仍然不允许（与 v0.6.0 一致）
1. 不调用真实 APX。
2. 不生成真实视频。
3. 不提交 git，不推送。
4. 不修改 `.env`，不写死 API key。
5. 不修改 NotebookLM prompt 模板。
6. 不修改 Prompt Mode 数据库 schema。
7. 不修改 AI Review 评分标准。
8. 不引入 Celery / Redis / RQ / 后台队列。
9. 不新增 `video_review` 表。
10. 不把中文题目直接放进 Seedance prompt 的 screen text。

详细见 `docs/v0.6.1_english_landscape_video_spec.md`。

## v0.6.0 - APX Seedance Real Provider Integration

> 本版本首次接入公司内部 APX 异步视频网关（底层调用 `doubao-seedance-2.0`），
> 把 v0.5.6 已经 ready 的 `seedance_prompt.txt` / `seedance_payload_preview.json`
> 真正打到远端：`POST /v1/async/chat` 提交 → `GET /v1/async/results/{id}` 轮询
> → 成功后下载 `response.video_url` 到 `outputs/<slug>/video.mp4` →
> 写入 `video_history.video_file_path` → 前端通过
> `/api/video/history/{id}/asset/video` 播放本地 mp4。**真实网络调用仅允许出现
> 在 `web/video_providers/apx_seedance_provider.py` 内部**，且必须由
> `APX_VIDEO_ENABLED=true` + `APX_VIDEO_API_KEY` 显式开启；未配置时自动 fallback
> 到 v0.5.3 的 Mock provider。Prompt Mode 数据库 schema、主提示词、NotebookLM
> 主模板、AI Review 评分标准均未变动；不新增 `seedance_provider.py`，不新增
> `video_review` 表。

### 新增
- 新增 `web/video_providers/apx_seedance_provider.py`，类 `ApxSeedanceProvider`：
  `provider_name="apx_seedance"`、`network_enabled=True`、`PROVIDER_NAME` /
  `SUBMIT_PATH="/v1/async/chat"` / `RESULTS_PATH="/v1/async/results"` /
  `STATUS_MAP={1:"pending",2:"running",3:"succeeded",4:"failed"}` /
  `DEFAULT_DURATION=5`（NOT 60）/ `DEFAULT_MODEL="doubao-seedance-2.0"`。
  暴露 `load_config` / `is_configured` / `build_submit_payload` /
  `check_fallback_safety` / `submit` / `poll` / `download_video` /
  `download_cover` / `confirm` 等方法。Submit body 仅包含
  `{model, prompt, duration, prompt_extend}`，不含 `negative_prompt` /
  `extra_body` / `img_url` / `seed`。Headers 仅包含 `api-key` /
  `X-APX-Model` / `Content-Type: application/json; charset=utf-8`。
- 新增 fallback prompt 安全防护：当 `generation_manifest.json.llm_used=false`、
  `fallback_used=true`、`seedance_prompt_ready≠true`、prompt 中包含
  `需要人工核对` / `Human review required`、或 debug warnings 中包含
  `missing` 时，默认拒绝真实 submit，job 写入 `status=blocked_fallback_prompt`，
  绝不烧 APX 配额；可通过 `APX_VIDEO_ALLOW_FALLBACK_SUBMIT=true` 显式覆盖。
- 新增下载安全：`download_video` / `download_cover` 拒绝非 http(s) URL，
  对文件名做 `[^A-Za-z0-9._-]→_` 清洗，使用 `target.relative_to(out_dir)`
  阻止 path traversal，并通过 `.part → rename` 实现原子下载，避免半截 mp4。
- 新增 API key 脱敏：`_scrub_api_key` 递归遮蔽
  `api-key` / `api_key` / `apikey` / `authorization` / `x-api-key`，
  在落入 `request_json` / `response_json` 前完成；`load_config()` 只暴露
  `api_key_configured: bool`，绝不返回真实 key；headers 永不写入快照。
- 新增 `config/provider_profiles/apx_seedance.json`（`apx_seedance_profile_v0.6.0`），
  把 transport / 状态映射 / fallback 规则等 operator-facing 配置文件化，
  保持 forward-compatible。
- 新增 `docs/v0.6.0_apx_seedance_real_provider.md`，记录 surface、状态机、
  环境变量、安全防护、人工烟雾测试步骤。
- 新增环境变量（仅记录在 `.env.example`，不放真值）：
  `APX_VIDEO_ENABLED` / `APX_VIDEO_BASE_URL` / `APX_VIDEO_API_KEY` /
  `APX_VIDEO_MODEL` / `APX_VIDEO_DURATION` / `APX_VIDEO_PROMPT_EXTEND` /
  `APX_VIDEO_POLL_INTERVAL_SECONDS` / `APX_VIDEO_TIMEOUT_SECONDS` /
  `APX_VIDEO_CONFIRM_AFTER_DOWNLOAD` / `APX_VIDEO_ALLOW_FALLBACK_SUBMIT`。

### 后端
- `web/app.py` 新增 `_load_apx_assets_for_record`（读取
  `outputs/<slug>/video_assets/seedance_prompt.txt` /
  `generation_manifest.json` / `seedance_payload_preview.json` /
  `seedance_prompt_debug.json`），`_create_apx_video_job_for_record`（APX
  分支），`_create_video_job_for_record`（dispatcher：APX 已配置 → 走 APX，
  否则 fallback Mock），`_refresh_apx_job`（poll → 成功后 download_video +
  download_cover → 更新 VideoJob 与 VideoHistory，可选 confirm DELETE）。
- `/api/video/generate` / `/api/video/regenerate` / `POST /api/video/history/{id}/jobs`
  全部改为调用新的 dispatcher，实现 APX 优先、Mock 兜底。
- `/api/video/jobs/{id}/refresh` 增加 `apx_seedance` 分支：返回最新 job 状态；
  成功路径将 mp4 落到 `outputs/<slug>/video.mp4`，把
  `video_history.video_status="ready"`、`video_file_path` / `video_thumbnail_path`
  / `video_url` 同步到 DB。
- `/api/video/generate` 不阻塞等待视频生成完成；前端通过 Refresh 按钮主动
  推动状态机。

### 前端
- `web/static/main.js` 的 `renderVideoJobStatus()` 支持 `submitted` /
  `pending` / `running` / `succeeded` / `ready` / `failed` /
  `blocked_fallback_prompt` / `succeeded_but_no_video_url` /
  `provider_not_configured`，对运行中的 APX job 显示 Refresh 按钮，调用
  `POST /api/video/jobs/{id}/refresh` 并在成功后将 `<video>` 的 src 指向
  `/api/video/history/{id}/asset/video`。
- `web/static/index.html` 在 Video Job 紧凑状态条加入 `Refresh` 按钮，
  `web/static/style.css` 加入对应样式（无侵入式视觉变化）。

### 自检
- `scripts/run_stability_checks.py` bumped 到 `v0.6.0`，新增
  `check_v060_apx_provider`：apx_seedance_provider 文件 + 类 + 方法存在性、
  `/v1/async` 路径、`STATUS_MAP` 1/2/3/4 映射、`DEFAULT_DURATION=5`、
  10 个 `APX_VIDEO_*` env 变量名引用、API key 脱敏函数存在、fallback 安全
  防护存在、apx_seedance_provider.py 之外无 requests/httpx/urllib 真实网络
  调用、web/app.py 已 wire 上 APX dispatcher、main.js 已实现
  `refreshVideoJob()` 与新状态、Prompt Mode 文件未被 APX 写入、
  仓库工作树不含 `.env` / `data/*.db` / `outputs/` / `*.mp4`、
  submit body 形态正确、必需 headers 齐全、v0.6.0 文档存在。

### 安全 / 边界（与既往版本一致并继续生效）
- 不修改 Prompt Mode 数据库 schema、Prompt Mode 主提示词、NotebookLM
  Prompt 主模板、AI Review 评分标准。
- 不新增 `video_review` 表。
- 不新增 `seedance_provider.py`。
- 不在 `apx_seedance_provider.py` 之外触发任何真实网络调用。
- 不打印 / 不存储 / 不导出 API key；`.env` 不入库；自动测试不触达真实 APX。

## v0.5.6 - Seedance Prompt Compiler (Dry-Run)

> 本版本在 v0.5.5「Seedance Provider Contract Adapter」之上新增 **Seedance
> Prompt Compiler**——一个离线、dry-run、不联网的编译器，把 Video Mode 的
> 结构化内容资产（`topic_analysis` / `reasoning` / `video_script` /
> `storyboard` / `provider_request_preview`）编译成 Seedance 形态的英文
> prompt 包（主 prompt + negative prompt + debug 元数据），为 v0.6.0 的
> 首次真实 Seedance 调用提供可直接复用的输入。**v0.5.6 仍然不接 Seedance、
> 不接任何真实视频生成 API、不发起任何真实网络请求、不生成真实 mp4、
> 不下载真实视频文件、不写入真实视频 URL；真正的 submit / poll / download
> 仍保留给 v0.6.0。** Prompt Mode 数据库 schema、主提示词、NotebookLM Prompt
> 主模板、AI Review 评分标准均未变动。

### 新增
- 新增 `config/provider_profiles/seedance.json`，
  `profile_version="seedance_prompt_profile_v0.5.6"`：声明
  `preferred_prompt_language="en"`、`default_duration_seconds=60`、
  `default_aspect_ratio="9:16"`、`prompt_strategy="scene_by_scene"`、
  `narration_mode="single_narrator_monologue"`、12 项
  `must_include_constraints`、14 项 `negative_prompt_defaults`、
  `visual_defaults`、8 段 `section_order`。Profile 是静态配置文件，
  forward-compatible，可在不影响 Seedance 的前提下追加 `kling.json` /
  `runway.json` / `veo.json`。
- 新增 `web/video_providers/seedance_prompt_compiler.py`，类
  `SeedancePromptCompiler`：`compiler_version="seedance_prompt_compiler_v0.5.6"`、
  `network_enabled=False`，导出
  `compile_from_assets` / `build_seedance_prompt` /
  `build_negative_prompt` / `build_debug_payload` 四个方法；
  模块顶层无 `requests` / `httpx` / `aiohttp` / `urllib` 真实网络调用，
  也不导入 NotebookLM Prompt 主模板。`build_seedance_prompt` 输出英文
  8-section prompt：Video Goal / Visual Style / Narration Mode /
  Core Explanation / Scene-by-scene Storyboard / On-screen Text Rules /
  Motion / Final Constraints。`build_debug_payload` 输出
  `seedance_prompt_debug_v0.5.6` schema 的 JSON。
- `web/video_asset_pipeline.py` 升级到 `video_assets_v0.5.6`（保留
  `VIDEO_ASSETS_LEGACY_SCHEMA_VERSION="video_assets_v0.5.5"`），在写完
  `provider_request_preview.json` 之后、调用 `SeedanceContractAdapter`
  之前，先调用 `SeedancePromptCompiler.compile_from_assets(...)`，落 3
  个新资产文件：`seedance_prompt.txt`、`seedance_negative_prompt.txt`、
  `seedance_prompt_debug.json`，资产数量从 10 升级到 13。Manifest 新增
  `seedance_prompt_compiler_version` / `seedance_prompt_profile_version`
  / `seedance_prompt_ready` / `seedance_prompt_path` /
  `seedance_negative_prompt_path` / `seedance_prompt_debug_path` /
  `prompt_source_for_seedance_payload` 字段。
- `web/video_providers/seedance_contract_adapter.py` 升级到
  `seedance_payload_preview_v0.5.6`（保留
  `PAYLOAD_PREVIEW_LEGACY_SCHEMA_VERSION="seedance_payload_preview_v0.5.5"`）：
  `build_seedance_payload_preview` 新增 `compiled_prompt` /
  `compiled_negative_prompt` / `prompt_compiler_version` /
  `prompt_source` / `negative_prompt_source` / `compiler_ready`
  关键字参数；`payload.prompt` 优先使用 compiled `seedance_prompt.txt`，
  缺失时回退 upstream `provider_prompt.txt` 并在 `warnings` 中记录
  `Compiled Seedance prompt was empty; payload fell back to provider_prompt.`
  返回值新增 `prompt_compiler_version` / `prompt_source` /
  `negative_prompt_source` / `prompt_from_compiler` /
  `negative_prompt_from_compiler` 顶层字段。
- `/api/video/generate` 与 `/api/video/history/{id}/regenerate` 响应额外
  携带 `seedance_prompt` / `seedance_negative_prompt` /
  `seedance_prompt_debug` / `seedance_prompt_compiler_version` /
  `seedance_prompt_profile_version` / `seedance_prompt_ready` 字段，
  并在 `provider_contract` 子对象中追加 `prompt_compiler_ready` /
  `prompt_compiler_version`。message 文案改为
  `Seedance prompt compiler + contract adapter are ready in v0.5.6.
  Compiled Seedance prompt + negative prompt were generated, but no real
  video API was called.`
- `/api/video/history/{id}/provider-contract` 端点扩展：顶层加上
  `prompt_compiler_ready` / `prompt_compiler_version`，直接返回
  `seedance_prompt` / `seedance_negative_prompt` /
  `seedance_prompt_debug`；`readiness_summary` 加
  `has_seedance_prompt` / `has_seedance_negative_prompt` /
  `has_seedance_prompt_debug` / `prompt_compiler_ready`。
- Video Mode Overview 的 *Provider Contract Summary* 区块新增一行
  *Seedance Prompt Compiler: Ready / Not Available*，与 *Contract Status*
  并列展示；前端通过既有的
  `GET /api/video/history/{id}/provider-contract` 异步刷新。
- Download All 的 `metadata.json` 升级到 `export_schema_version=video_v0.5.6`
  （保留 `legacy_export_schema_version="video_v0.5.5"`），新增
  `seedance_prompt_compiler_version` / `seedance_prompt_profile_version`
  / `seedance_prompt_ready` 与 3 个新资产路径字段。zip 内自动追加 3 个
  新资产文件。
- 新增 `docs/v0.5.6_seedance_prompt_compiler.md`，详述 Prompt Compiler
  的三层 prompt 架构、provider profile 设计、新资产、manifest 与 payload
  preview 升级、API 表面、UI 行为、严禁项与自检命令。
- `scripts/run_stability_checks.py` 升级到 `STABILITY_CHECKS_VERSION="v0.5.6"`，
  新增 `check_v056_compiler` 检查组（≥17 项），py_compile 列表加入
  `seedance_prompt_compiler.py`，`allowed_untracked` 加入 v0.5.6 新文件
  （doc / compiler / profile / 可选 fixture）。

### 修复
- 修复 stability check 因 v0.5.6 升级误报的 v0.5.5 marker：v0.5.5 检查组
  改为同时接受 `video_assets_v0.5.5` 与 `video_assets_v0.5.6` 两种
  schema_version；`VIDEO_ASSETS_LEGACY_SCHEMA_VERSION` 检查放宽至同时
  接受 `video_assets_v0.5.4` 与 `video_assets_v0.5.5`。
- 修复 export_schema_version 检查在多版本下的回归：v0.5.3 / v0.5.4 /
  v0.5.5 检查组的 `export_schema_version` 上限统一放宽到 `video_v0.5.6`，
  不再在 v0.5.6 升级后误报旧版 marker 缺失。

### 严禁项（在本版本中得到保留）
- 不接 Seedance / 不接任何真实视频生成 API。
- 不新增 `seedance_provider.py`，不创建任何真实 video provider 实现。
- 不执行 `requests.post` / `httpx.post` / `aiohttp` / `urllib.request` 的真实
  网络调用（自动化检查会扫描整个 `seedance_prompt_compiler.py`）。
- 不生成真实 mp4，不下载真实视频文件，不写入真实视频 URL。
- 不引入 Celery / Redis / RQ / 真实异步任务队列。
- 不新增 `video_review` 表。
- 不修改 Prompt Mode 数据库 schema、不修改 Prompt Mode 主提示词、不修改
  NotebookLM Prompt 主模板、不修改 AI Review 评分标准。
- 不修改 `.env`，不打印 API key，不硬编码 API key。
- 不提交 `data/*.db` / `outputs/` / `.env`；不执行 `git add` / `git commit`
  / `git push`（由用户决定）。

---

## v0.5.5 - Seedance Provider Contract Adapter (Dry-Run)

> 本版本在 v0.5.4「Video Content Asset Pipeline」之上新增 **Seedance Provider
> Contract Adapter**——一个只读、dry-run、不联网的契约层，用来把 v0.5.4 写好
> 的 `provider_request_preview.json` 校验为「未来可被 Seedance 接收」的载荷，
> 并落 3 个新的契约文件。**v0.5.5 不接 Seedance、不接任何真实视频生成 API、
> 不发起任何真实网络请求、不生成真实 mp4、不下载真实视频文件、不写入真实视频
> URL；真正的 submit / poll / download 留给 v0.6.0。** Prompt Mode 数据库
> schema、主提示词、NotebookLM 主模板、AI Review 评分标准均未变动。

### 新增
- 新增 `web/video_providers/seedance_contract_adapter.py`，类
  `SeedanceContractAdapter`：`provider_name="mock"`、
  `future_provider="seedance"`、`network_enabled=False`，导出
  `validate_provider_request_preview` / `build_seedance_payload_preview` /
  `build_lifecycle_preview` / `dry_run_submit` / `dry_run_poll` /
  `dry_run_download` 六个方法；模块顶层无 `requests.post` / `httpx.post` /
  `aiohttp` / `urllib.request` 真实网络调用；`http://` / `https://` 字符串只
  作为 `_scan_for_unsafe_strings` 的检测模式，不作为真实 endpoint。
- `web/video_asset_pipeline.py` 升级到 `video_assets_v0.5.5`（保留
  `VIDEO_ASSETS_LEGACY_SCHEMA_VERSION = "video_assets_v0.5.4"` 常量），落
  3 个新资产文件：`seedance_payload_preview.json`、
  `provider_contract_validation.json`、`provider_lifecycle_preview.json`，
  `generation_manifest.json` 自身仍然自注册路径，资产数量从 7 升级到 10。
- `/api/video/generate` 与 `/api/video/history/{id}/regenerate` 响应额外携带
  `seedance_payload_preview` / `provider_contract_validation` /
  `provider_lifecycle_preview` / `provider_contract` 四个字段，message 文案
  改为 `Seedance contract adapter is ready in v0.5.5. Content assets and
  provider payload preview were generated, but no real video API was called.`
- 新增 4 个 dry-run API 端点：
  - `GET  /api/video/history/{history_id}/provider-contract`
  - `POST /api/video/jobs/{job_id}/dry-run-submit`
  - `POST /api/video/jobs/{job_id}/dry-run-poll`
  - `POST /api/video/jobs/{job_id}/dry-run-download`
  全部不发起任何真实 HTTP 请求；submit/poll/download 将所有真实步骤标记为
  `blocked_until_v0.6.0`。
- VideoJob 的 stage 从 `not_started` 升级为 `contract_ready`，progress 从
  `0` 升级为 `90`；`provider` 仍是 `mock`、`status` 仍是
  `provider_not_configured`。
- Video Mode Overview 标签新增独立的 **Provider Contract Summary** 区块
  (`<div id="provider-contract-summary">`)，前端通过新端点
  `GET /api/video/history/{id}/provider-contract` 异步刷新；摘要显示
  future provider、contract status、network call performed、real video
  downloaded。`refreshProviderContractSummary()` 仅访问本地 dry-run 端点，
  不发起任何真实视频下载或外部 API 调用。
- Download All 的 `metadata.json` 升级到 `export_schema_version=video_v0.5.5`，
  新增 `provider_contract_schema_version=seedance_contract_v0.5.5` /
  `seedance_contract_ready` / `provider_contract_validation_valid` /
  `real_video_downloaded=false` / `network_call_performed=false` 字段；zip
  内追加 3 个新资产文件。
- 新增 `docs/v0.5.5_seedance_provider_contract_adapter.md`，详述 dry-run
  适配器的设计、资产升级、schema version、API 端点、UI 行为、严禁项与自检
  命令。
- 新增 `tests/fixtures/seedance_contract_sample_request.json` 作为契约样例。
- `scripts/run_stability_checks.py` 升级到 `STABILITY_CHECKS_VERSION="v0.5.5"`，
  新增 `check_v055_contract` 检查组（≥16 项），py_compile 列表加入
  `seedance_contract_adapter.py`，`allowed_untracked` 加入 v0.5.5 新文件。

### 修复
- 修复 stability check 因 v0.5.5 升级误报的 v0.5.4 marker：v0.5.4 检查组
  改为同时接受 `v0.5.4` 与 `v0.5.5` 两种 export_schema_version / 用户可见
  message；v0.5.3 检查组放宽 export_schema_version 上限到 `v0.5.5`。
- 修复 v0.5.5 contract 检查组的 `http://` / `https://` 误报——改为只匹配
  真实 URL 字面量（`https?://[A-Za-z0-9]`），让 `_scan_for_unsafe_strings`
  内部的检测模式不再被当作 endpoint 泄漏。

### 严禁项（在本版本中得到保留）
- 不接 Seedance / 不接任何真实视频生成 API。
- 不新增 `seedance_provider.py`，不创建任何真实 video provider 实现。
- 不执行 `requests.post` / `httpx.post` / `aiohttp` / `urllib.request` 的真实
  网络调用。
- 不生成真实 mp4，不下载真实视频文件，不写入真实视频 URL。
- 不引入 Celery / Redis / RQ / 真实异步任务队列。
- 不新增 `video_review` 表。
- 不修改 Prompt Mode 数据库 schema、不修改 Prompt Mode 主提示词、不修改
  NotebookLM Prompt 主模板、不修改 AI Review 评分标准。
- 不修改 `.env`，不打印 API key，不硬编码 API key。
- 不提交 `data/*.db` / `outputs/` / `.env`；不执行 `git add` / `git commit`
  / `git push`（由用户决定）。

---

## v0.5.4 - Video Content Asset Pipeline

> 本版本在 v0.5.3「Video Job / Provider / Asset 基础层」之上新增 **Video
> Content Asset Pipeline**，把 Video Mode 的「生成」从「写一份 NotebookLM 脚本
> + Mock VideoJob」升级为「先调用 LLM 生成结构化内容资产 → 落 7 个产物文件 →
> 写历史 + Mock VideoJob → 把资产塞回响应」。**本版本仍然不接 Seedance、不接
> 任何真实视频生成 API、不生成真实 mp4、不下载视频文件**。Video Mode Raw Text
> 在 v0.5.4 中改为承载未来给 Seedance 用的 `provider_prompt`，而不是
> NotebookLM 脚本（NotebookLM 主模板归 Prompt Mode 独占，未被复制或修改）。

### 新增
- 新增 `web/video_asset_pipeline.py` 与 `build_video_content_assets()`：
  - 渲染 `templates/video_asset_prompt_template.md` 模板（v0.5.4 新增）。
  - 通过 `AI_VIDEO_LLM_*` 环境变量复用 OpenAI-compatible 客户端
    (`AI_VIDEO_LLM_PROVIDER` / `AI_VIDEO_LLM_BASE_URL` /
    `AI_VIDEO_LLM_MODEL` / `AI_VIDEO_LLM_API_KEY` /
    `AI_VIDEO_LLM_TEMPERATURE` / `AI_VIDEO_LLM_MAX_TOKENS` /
    `AI_VIDEO_LLM_TIMEOUT` / `AI_VIDEO_LLM_RESPONSE_FORMAT`)，
    并实现 temperature/json_mode 不支持时的降级重试。
  - 严格 JSON 解析（直接 / 去 markdown fence / 抽取最外层 `{...}` 三段式
    fallback），失败统一走确定性 fallback，不抛异常。
  - 落 7 个产物到 `outputs/<slug>/video_assets/`：
    `topic_analysis.json` / `reasoning.md` / `video_script.md` /
    `storyboard.json` / `provider_prompt.txt` /
    `provider_request_preview.json` / `generation_manifest.json`。
    LLM 原始输出落 `llm_raw_output.txt`。
  - **不打印 API key**，只输出 `AI_VIDEO_LLM_API_KEY configured: true/false`、
    `AI_VIDEO_LLM_BASE_URL configured: true/false`、`current model: ...`、
    `LLM path used: real LLM / fallback`；不写 API key 进任何文件，不硬编码
    API key。`OPENAI_API_KEY` 仅作为 legacy fallback，不再作为主路径判断。
- 新增 `templates/video_asset_prompt_template.md`：v0.5.4 的 Video Asset
  Prompt 模板，强制输出严格 JSON，包含 `topic_analysis` / `reasoning` /
  `script` / `storyboard` / `provider_prompt` / `web_copy_placeholder`
  六个顶层 key；硬约束：单个旁白 / monologue / 不允许 dialogue /
  interview / podcast / two-host / multiple speakers / 无相关装饰 /
  不允许错答 / 视觉与推理一致 / 大字号可读屏幕文本；语言规则：中文题目
  → 中文旁白 + 英文 `provider_prompt`。
- `/api/video/generate` 与 `/api/video/history/{id}/regenerate`：
  在 subprocess 写完 `outputs/<slug>/notebooklm_clean_source.txt` 之后
  立即调用 `build_video_content_assets()`，把 `provider_prompt` 写入
  `VideoHistory.prompt_text`、把 design summary 写入 `overview_cn`，
  并在响应中新增 `video_assets` / `provider_prompt` /
  `provider_request_preview` / `asset_manifest` / `asset_paths` /
  `video_assets_schema_version` / `video_assets_warnings` / `llm_used`
  字段。同时附带 v0.5.4 message：
  `Real video provider is not connected in v0.5.4. Content assets were
  generated successfully, but no real video API was called.`
- Video Mode Download All (`/api/video/history/{id}/download-all`)：
  在保留原有 `raw_text.txt` / `preview.txt` / `overview.txt` /
  `web_copy.txt` / `metadata.json` 之外，把磁盘上的
  `outputs/<slug>/video_assets/` 整个目录递归追加到 zip（仅文本资产，
  不含 mp4 / mov / video URL / token / API key）。`metadata.json` 升级
  到 `export_schema_version=video_v0.5.4`，新增
  `video_assets_schema_version=video_assets_v0.5.4` /
  `provider_status=provider_not_configured` /
  `real_video_generated=false` / `has_video_assets`。
- 前端 Video Mode 多阶段进度面板从 8 步升级为 9 步：
  Analyzing topic → Verifying answer → Writing video script →
  Building storyboard → Creating provider prompt →
  Preparing provider request → Creating mock video job →
  Saving assets → Done。最终阶段仍按真实响应落到
  `provider_not_configured` 或失败态。
- 前端 Video Mode Tab 内容映射：Video tab = compact Video Job + 播放器
  占位；Web Copy tab = 占位（v0.5.4 不变）；Raw Text tab = `provider_prompt`
  （未来 Seedance 输入）；Preview tab = pipeline 渲染的脚本 + storyboard 摘要；
  Overview tab = pipeline 渲染的中文 design summary；AI Review tab = 占位。
- 新增 `docs/v0.5.4_video_content_asset_pipeline.md`，详述 v0.5.4 的设计、
  资产形态、LLM 配置复用与失败降级、Tab 映射、Download All 契约、稳定性
  检查清单与保护边界。
- README 与 `docs/technical_roadmap.md` 当前里程碑更新至 v0.5.4 阶段。

### 修复
- 修复 Video Mode 生成完成后 Job message 的版本号，由「v0.5.3 / Mock provider
  produced this job shell only」改为版本无关 + v0.5.4 资产说明：
  `Real video provider is not connected in v0.5.4. Content assets were
  generated successfully, but no real video API was called.`
- v0.5.4 first structural fix：修正 LLM 配置读取与生成顺序：
  - 资产管线主配置改为读取 `AI_VIDEO_LLM_API_KEY` /
    `AI_VIDEO_LLM_BASE_URL` / `AI_VIDEO_LLM_MODEL`；`OPENAI_API_KEY` 降级为
    legacy fallback。`generation_manifest.json` 的 `llm` 段不再写
    完整 base_url，只写 `base_url_configured` / `api_key_configured` /
    `config_namespace`。
  - 资产管线 CLI 在独立运行时主动加载项目根 `.env`（如果存在），保证
    standalone / FastAPI / stability check 三处口径一致。
  - `/api/video/generate` 改为「先 `create_history_record` → 再
    `build_video_content_assets(history_id=record.id)` →
    `update_asset_pipeline_result()` 写回 `prompt_text` /
    `preview_text` / `overview_cn` / `metadata_json`」。
    `generation_manifest.json` 中的 `history_id` 不再为 `null`。
  - `/api/video/history/{id}/regenerate` 同样修复：先建 new_record，再
    用 new_record.id 调 pipeline，再写回 record。
  - 新增 `VideoHistoryRepository.update_asset_pipeline_result()` 用于
    在不改 schema 的前提下回写 v0.5.4 字段。
  - `Download All`：`preview.txt` 优先使用 `record.preview_text`，
    若为空且磁盘上存在 `video_assets/video_script.md` 与
    `video_assets/storyboard.json`，则按「Script + Storyboard」拼接
    fallback；`metadata.json` 增加 `asset_list` /
    `asset_history_id` / `llm_used` / `fallback_used` 字段，
    `asset_list` 优先来自 `generation_manifest.assets`。
- v0.5.4 second polish：
  - `generation_manifest.json` 的 `assets` / `files` 现在自登记，
    包含 `generation_manifest.json` 自身（核心资产共 7 个），LLM 命中
    时再追加 `llm_raw_output.txt`。manifest 顶层新增
    `future_provider=seedance` / `submit_mode=not_connected` /
    `real_video_generated=false`，便于未来 v0.6.0 Seedance 集成做契约对齐。
  - `provider_request_preview.json` 重塑为「未来 Seedance 契约预览」：
    顶层暴露 `provider` / `future_provider` / `prompt` /
    `duration_seconds` / `aspect_ratio` / `resolution` / `fps` /
    `language` / `style` / `negative_prompt` / `submit_mode` /
    `provider_status` / `real_video_generated` / `note`，原嵌套结构
    保留在 `request` 字段下兼容。v0.5.4 仍然不发送该请求。
  - `scripts/run_stability_checks.py` 新增 `check_git_status_hygiene()`
    只读审计：禁止旧 `docs/v0.4.*` 文件被删除、禁止乱码（mojibake）
    docs 出现在 untracked、禁止 `.env` / `data/*.db` / `outputs/` /
    `__MACOSX` / `.DS_Store` 出现在 git status。

### 保护边界
- 本版本**不接** Seedance。
- 本版本**不新增** `seedance_provider.py`，也不新增任何真实视频
  provider 实现文件。
- 本版本**不接**任何真实视频生成 API。
- 本版本**不生成**真实 mp4，**不下载**视频文件。
- 本版本**不修改** `.env`，**不打印** API key 真实内容，**不硬编码** API key。
- 本版本**不新增**真实异步任务队列（无 Celery / Redis / RQ）。
- 本版本**不新增** `video_review` 表。
- 本版本**不修改** Prompt Mode 数据库 schema（`prompt_history` /
  `prompt_reviews` 不变）。
- 本版本**不修改** Prompt Mode 主流程、Prompt 主提示词、AI Review 评分
  标准、NotebookLM 输出结构。
- 本版本**不破坏** Prompt Mode 既有能力（Prompt 生成 / Raw Text /
  历史 / 版本 / 收藏 / 置顶 / 回收站 / Regenerate / Download All 全部保留）。
- 本版本**不跨库写入**：VideoJob 与 Video Content Asset 仅写入
  `data/video_history.db` 与 `outputs/<slug>/video_assets/`，
  从不接触 Prompt Mode 表。
- 本版本**不提交** `.env` / `data/*.db` / `outputs/` / 任何 API key 或
  真实密钥。

---

## v0.5.3 - Video Job / Provider / Asset 基础层与生成流程升级

> 本版本在 v0.5.2「Video Mode 独立框架」之上新增 Video Job 数据模型、Provider
> 抽象层与 Asset endpoint，并将 Video Mode 的生成流程从「单纯写历史记录」升级为
> 「生成历史 + 创建 Mock VideoJob + 返回组合响应」。**本版本不接 Seedance、
> 不接任何真实视频生成 API、不生成真实 mp4、不引入真实异步任务队列**。

### 新增
- 新增 `VideoJob` 数据模型与 `video_jobs` 表，用于记录 Video Mode 的视频生成
  任务状态（status / stage / progress / provider / provider_job_id / 请求与
  响应快照 / 时间戳等）。仅写入 `data/video_history.db`，与 Prompt Mode 完全隔离。
- 新增 `VideoJobRepository`（`web/db/video_job_repository.py`），管理 Video Job
  的创建、查询、最新一条获取、状态更新与取消。
- 新增 `web/video_providers/` provider 抽象层，包括 `VideoProvider` 基类与
  `MockVideoProvider`。`VideoProvider` 提供 `submit / get_status / cancel`
  接口与 `empty_response()` 标准 shell 助手。
- 新增 Mock Provider 任务链路：不访问网络、不读取 API key、不生成真实视频，
  仅返回 `provider_not_configured` 任务壳（status=`provider_not_configured`、
  stage=`provider_not_connected`、progress=85）。
- 新增 Video Job API：
  - `POST /api/video/history/{history_id}/jobs`
  - `GET /api/video/history/{history_id}/jobs/latest`
  - `GET /api/video/jobs/{job_id}`
  - `POST /api/video/jobs/{job_id}/refresh`
  - `POST /api/video/jobs/{job_id}/cancel`
- 新增 Video Asset API：
  - `GET /api/video/history/{history_id}/asset/video`
  - `GET /api/video/history/{history_id}/asset/thumbnail`
  Asset endpoint 通过 `_resolve_safe_outputs_path()` 强约束在
  `project_root/outputs/` 之下，任何越界路径直接 404；v0.5.3 内 VideoHistory
  与 VideoJob 都不会写入真实视频文件路径，所以 asset endpoint 在正常使用下
  始终返回 404。
- Video Mode 首页右下角圆形按钮在当前模式下显示为 `Generate Video`，
  Prompt Mode 仍显示 `Generate Prompt`。aria-label 与 tooltip 随
  `currentAppMode` 实时切换。
- Video Mode 首页生成过程新增多阶段进度面板（9 个步骤）：识别题目 / 生成
  prompt / 写脚本 / 准备 provider 请求 / 提交 mock provider / 等待生成 /
  保存资产 / 完成。最终阶段会落到 `provider_not_configured` 或失败态。
- `/api/video/generate` 与 `/api/video/history/{id}/regenerate` 在写完历史
  记录后自动调用 `MockVideoProvider().submit(...)` 并写入 `video_jobs`，
  response 中新增 `video_job` 字段（`VideoJob.to_dict()`）。
- Video tab 新增 compact Video Job 状态区，作为播放器上方的辅助状态条目，
  展示 status pill / provider / progress / stage / provider_job_id /
  updated 与 message。
- 新增 `docs/v0.5.3_video_job_provider_framework.md`，详述 Video Job /
  Provider / Asset 基础层的数据模型、API、安全约束、前端集成与稳定性检查。
- README 与 `docs/technical_roadmap.md` 当前里程碑更新至 v0.5.3 阶段。

### 修复
- 修复 Video Mode AI Review placeholder 中 v0.5.1.2 旧版本号残留：
  `web/static/ai_review.js` 的 placeholder 改为版本无关的中性文案
  「AI Review for Video Mode is not connected yet.」。
- 修复 Video Job 状态展示过重的问题，改为 compact 辅助状态区，不再做大号
  居中 hero card，不再显示「Video Job Framework Ready」大标题。
- 修复 Video Mode 生成中 progress steps 视觉偏左问题，
  `.video-progress-panel` 改为 `margin: 16px auto 0`，整体居中。
- 修复 `download_all` 中 `metadata.json` 的 `export_schema_version` 由
  `video_v0.5.1` 升级为 `video_v0.5.3`。
- 修复 VideoHistory.video_status 与 VideoJob.status 不一致的问题：
  在 `_create_mock_video_job_for_record()` 中，job 创建成功后会按
  `_map_job_status_to_video_status()` 将对应 `VideoHistory.video_status`
  从 `not_generated` 同步为 `provider_not_configured`（v0.5.3 默认情况），
  保证 generate / regenerate response 与 download-all metadata 的
  `video_status` 字段一致。

### 保护边界
- 本版本**不接** Seedance。
- 本版本**不接**任何真实视频生成 API。
- 本版本**不生成**真实 mp4。
- 本版本**不新增**真实异步任务队列（无 Celery / Redis / RQ）。
- 本版本**不新增** `video_review` 表。
- 本版本**不修改** Prompt Mode 数据库 schema（`prompt_history` /
  `prompt_reviews` 不变）。
- 本版本**不修改** Prompt 生成主提示词。
- 本版本**不修改** AI Review 评分标准 / schema。
- 本版本**不破坏** Prompt Mode v0.4.10 既有能力（Prompt 生成 / Raw Text /
  历史 / 版本 / 收藏 / 置顶 / 回收站 / Regenerate 全部保留）。
- 本版本**不跨库写入**：VideoJob 仅写入 `data/video_history.db`，
  从不接触 Prompt Mode 表。

---

## v0.5.2 - Video Mode 独立框架与播放器界面稳定版

> 本版本是 v0.5.x 在「框架 + 播放器界面 + UI 稳定性」上的收口版本，统一取代
> v0.5.1 / v0.5.1.2 等临时小版本。本版本**不接 Seedance、不接真实视频生成 API、
> 不生成真实视频文件**。

### 新增
- **Mode Selector**：页面右上角新增 `mode-selector-btn` 下拉，
  Prompt Mode / Video Mode 两个选项。当前模式 active 高亮，点击页面其它区域关闭；
  默认进入 Prompt Mode。编辑态 / 生成中切换会先弹确认；切换会清空当前选中状态、
  重新加载目标模式的 sidebar 历史，并将 `<video>` 元素暂停卸载。
- **Video Mode 独立页面状态**：与 Prompt Mode 并列运行，UI 风格一致，数据完全隔离。
  Video Mode sidebar 不显示 Prompt Mode 历史，Prompt Mode 也不显示 Video Mode 历史。
- **Video Mode 独立数据库与历史模型**：`data/video_history.db`（与
  `data/prompt_history.db` 完全隔离）。新增 `web/db/video_database.py`
  （独立 engine / `VideoSessionLocal` / `VideoBase`）、`web/db/video_models.py`
  （`VideoHistory` ORM）、`web/db/video_repository.py`（`VideoHistoryRepository` CRUD）。
  `init_video_db()` 仅在 Video Mode 库中 `Base.metadata.create_all`，不触碰
  Prompt Mode 表，也不修改 Prompt Mode 任何 schema。
- **`/api/video/*` 后端接口骨架**：`web/app.py` 注册
  `/api/video/generate` / `/api/video/history` / `/api/video/history/{id}` (GET/PATCH) /
  `/api/video/history/group/{topic_group_id}/versions` /
  `/api/video/history/{id}/regenerate` /
  `/api/video/history/group/{topic_group_id}/rename` /
  pin / unpin / favorite / unfavorite / trash / restore / permanent /
  `/api/video/trash` / `/api/video/favorites` /
  `/api/video/history/{id}/download-all`。Download All 与 Prompt Mode 同款只读
  契约，包内只含 `raw_text.txt` / `preview.txt` / `overview.txt` / `web_copy.txt` /
  `metadata.json`，对数据库零写入；不含任何 mp4 / mov / 视频 URL / token / API key。
- **Video Mode 六个内容 tab**：Video（默认）/ Web Copy / Raw Text / Preview /
  Overview / AI Review。Prompt Mode 仍保持 4 个 tab（Raw / Preview / Overview /
  AI Review），Video / Web Copy 在 Prompt Mode 下通过 `[hidden]` 隐藏。
- **视频播放器占位界面**：`video-player-shell` 内嵌 `<video>` + 中央
  `video-center-play` 三角播放按钮 + 底部 `video-controls`（播放 / 暂停、进度条、
  时间 `mm:ss/mm:ss`、音量控件、倍速 `0.5×/1×/1.5×/2×/3×/5×`、全屏 Fullscreen API）。
  Video Mode 默认进入 Video tab。当 `<video>` 无 src 时 `togglePlay()` no-op，
  并在播放器作用域内提示「Video file is not available yet.」；切换 tab 或
  App Mode 时暂停并卸载视频元素。**v0.5.2 不会给播放器赋任何真实视频 URL，也不
  生成真实视频文件。**
- **Web Copy tab**：用于未来 YouTube / TikTok / Instagram 等平台的标题、
  description、caption、posting copy。当前支持编辑（`#web-copy-edit-textarea`）、
  保存（PATCH `web_copy` 字段）、复制（`getWebCopyPlainText()`）、下载
  （`web_copy.txt`）；**空内容时也可下载 placeholder `web_copy.txt`**，
  避免按钮无响应。
- **Video Mode AI Review placeholder**：Video Mode AI Review tab 仅展示
  placeholder 文案，**不调用** Prompt Mode `/api/history/{id}/review` 接口，
  避免误调用 Prompt Mode AI Review。后续真实视频生成接入后再单独设计 Video
  Review / 视频质检 prompt。
- **`/api/health` 增加 video DB 健康字段**：返回 `video_database: ok|error`。
- **全局 tooltip portal**：所有 `.icon-button` hover tooltip 改用单例
  `#global-icon-tooltip` 节点，由 `document.body.appendChild` 挂载到 body，
  `position: fixed; z-index: 2147483647`，基于 `getBoundingClientRect()` +
  `window.innerWidth` 在视口坐标系定位，`scroll` / `resize` 时统一隐藏。
  Tooltip 不再被视频框、内容卡片、结果区、footer 或 header 遮挡。
- **设计文档** `docs/v0.5.2_video_mode_framework.md`：v0.5.2 收口说明书，
  含 12 个章节（版本定位、Prompt/Video Mode 关系、Mode Selector、Video Mode
  数据隔离、Video Mode API、6 个 tab、Video tab、Web Copy tab、AI Review tab、
  Tooltip / UI 修复、Prompt Mode 保护边界、后续计划）。

### 修复
- **Video Mode 与 Prompt Mode 接口隔离**：历史、版本、AI Review、重命名等
  接口前缀通过 `apiUrl()` / `getApiPrefix()` 动态切换，确保 Video Mode 不会
  误调用 Prompt Mode endpoint，反之亦然。
- **Video tab 下 Edit / Copy / Download 不可用提示**：通过
  `data-unavailable-message` 给出明确文案——「Video tab cannot be edited.」/
  「Video content cannot be copied.」/「Video file is not available yet.
  Video source is not available yet.」；不再使用浏览器原生 `title` 属性，
  避免与自定义 tooltip 同时出现两层提示。
- **tooltip 层级与定位问题**：旧版按钮内 `position: absolute` tooltip 会被
  祖先 `overflow` / stacking context 遮挡或剪裁；改用全局 portal 后彻底消除
  该类问题，并在 textContent 变化点（Save↔Edit、Copy↔Copied!、退出编辑等）
  调用 `refreshActiveGlobalIconTooltip()` 实时刷新。
- **`exitEditMode` 重入与重复 Save tooltip**：用 `_exitEditModeInFlight` 守卫
  防止重入；移除重复 Save tooltip span 与多余的 `title` 设置。

### 调整
- **稳定性检查脚本升级到 v0.5.2**：`scripts/run_stability_checks.py` 标题更新为
  `Prompt Mode + Video Mode Stability Checks - v0.5.2`，docs 检查指向
  `docs/v0.5.2_video_mode_framework.md`，不再依赖已删除的
  `docs/v0.5.1_video_mode_framework.md`。原 v0.5.1 / v0.5.1.2 检查函数保留为
  内部 helper，继续覆盖 Mode Selector DOM、`/api/video/*` 注册、Video Mode 文件
  存在性、Prompt Mode 4 tab 不变、`.gitignore` 仍覆盖 `data/*.db`、全局
  tooltip portal 六个 helper（`ensureGlobalIconTooltip` / `showGlobalIconTooltip` /
  `hideGlobalIconTooltip` / `bindGlobalIconTooltips` / `getIconTooltipMessage` /
  `getIconTooltipPlacement`）、`getBoundingClientRect()` 与 `window.innerWidth`
  引用、portal `document.body.appendChild` 挂载、DOMContentLoaded 启动调用、
  `scroll/resize` 全局隐藏等审计。脚本继续保持 read-only：不调用 LLM、
  不修改任何数据库、不触发任何下载、不启动服务。

### 注意
- 本版本保留 Prompt Mode v0.4.10 全部既有能力：不修改 Prompt 生成主提示词、
  AI Review 评分标准、NotebookLM 输出结构、Prompt Mode Download All 只读契约、
  Prompt Mode Raw Text 数据保护逻辑、Prompt Mode Regenerate / 版本管理 /
  收藏 / 置顶 / 回收站逻辑、`prompt_history` / `prompt_reviews` schema。
- 本版本未引入：Seedance API、真实视频生成 provider、真实视频任务队列、
  外部视频链接、`video_review` 表、React/Vue 重构、用户登录系统、大型新依赖。
- 本版本未提交：`.env`、`data/*.db`、`data/*.db-shm`、`data/*.db-wal`、
  `data/backups/*.db`、`data/video_history.db`、`outputs/`、`__MACOSX/`、
  `.DS_Store`、任何 API key 或真实密钥。

## v0.4.10 - Prompt Mode 导出一致性与冻结说明书

### 二次热修（v0.4.10 hotfix）
- **Download All 只读性修复**：`web/app.py` `download_all()` 之前调用了
  `PromptReviewRepository.get_review_status(db, history_id)`，该函数内部会在 generating
  超时时调用 `mark_review_failed()`，把 review 状态写回数据库。这意味着
  `GET /api/history/{id}/download-all` 这样一个下载接口会在用户「下载」时悄悄修改
  `data/prompt_history.db`，违反「下载必须只读」的约定。修复后 `download_all()`
  不再调用任何会触发写库的 helper，整个链路对数据库零写入，不再触发任何 timeout 标记。
- **Download All 旧 schema AI Review 兼容**：之前 hotfix 用
  `PromptReviewRepository.get_review_by_history_id()` 读取 review，但该 helper 默认只匹配
  当前 schema (`v0.4.6.9_strict`)，导致只存在旧 schema review（如 `v0.4.6_calibrated` /
  `v0.4.5_legacy`）的历史记录被误判为「AI Review has not been generated yet.」。
  修复后 `download_all()` 改为直接 `db.query(PromptReview).filter(...).order_by(...).all()`
  做只读查询，先从当前 schema 中按 `completed > stale > generating > failed` 选最近一条；
  若当前 schema 完全没有 review，则回退到旧 schema 中最近一条 `review_json` 可解析的记录，
  在 `ai_review.md` 顶部追加 `Note: This AI Review may be outdated because the prompt
  has changed.`，并把 `metadata.json` 中的 `ai_review_status` 标记为 `"stale"`、
  `ai_review_schema_version` 保留旧 schema 字符串、`ai_review_total_score` 保留旧 score。
  仅有旧 schema 但 `review_json` 解析失败时，写入「AI Review data exists but could not
  be parsed.」并保留 metadata 中的 schema/score；完全没有 review 时落入 `"none"`。
  整个分支对数据库依然零写入。
- **`scripts/run_stability_checks.py` 加固**：v0.4.10 检查中新增三项 FAIL 级源码审计 ——
  (1) `download_all()` 函数体禁止出现 `get_review_status(`；
  (2) 禁止出现 `get_review_by_history_id(`；
  (3) 必须直接 `db.query(PromptReview)` 读 `PromptReview` 表以保证旧 schema 兼容。
  定位方式为按 `async def download_all` 起点截取到下一个 `@app.` / `async def ` / `def `
  顶层定义为止，剥除 `#` 注释行后做纯文本扫描，不引入新依赖、不启动服务、不访问网络、
  不修改数据库。

### 修复
- **Download All 内容补齐**：`GET /api/history/{id}/download-all` 现在打包 `raw_text.txt` /
  `preview.txt` / `overview.txt` / `ai_review.md` / `metadata.json` 五个文件。`ai_review.md`
  按前端 `reviewToMarkdown` 同款表格输出；`stale` 状态会在 markdown 头部追加
  「Note: This AI Review may be outdated because the prompt has changed.」；review 不存在时
  写入占位文案，不会触发 LLM 调用。`metadata.json` 仅包含 id / title / slug / output_dir /
  model / mode / status / topic_group_id / version_number / created_at / updated_at /
  has_preview_text / has_overview_cn / has_change_summary_cn / regenerate_from_history_id /
  regenerate_feedback / ai_review_status / ai_review_total_score / ai_review_schema_version /
  export_schema_version 字段，**不包含 API key、`.env`、密钥或本地路径以外的敏感信息**。
- **Overview Copy / Download 缺失 change_summary_cn**：`web/static/main.js` 新增
  `getOverviewPlainText()` 辅助函数，Overview 视图的 Copy / Download 现在会拼接
  `currentOverviewText` 与 `currentChangeSummaryText`，并以「本次生成新增或改动的内容」
  作为分隔标题，与 UI 渲染保持一致。该改动**只影响 Overview 链路**，Raw / Preview / AI Review
  的复制下载内容保持不变；Raw Text 仍是干净的 NotebookLM Prompt。

### 审计
- **AI Review 表格列结构核对**：再次审计 `web/static/ai_review.js` 中
  `renderReviewWithToolbar()` 表格 —— 表头 5 列（Criterion / Weight / Evaluation Focus /
  LLM Score / LLM Comment），所有 body / Total Score / Overall Review 行均为 5 个 `<td>`，
  每行只有一个 `<td class="weight">`，无重复 weight 列。本次未对该函数做结构性修改。

### 新增
- **Prompt Mode 冻结说明书** `docs/prompt_mode_freeze_spec.md`：覆盖 (1) 当前能力清单、
  (2) 不可破坏的核心约定（Raw 必须干净、schema 冻结、Prompt 主提示词冻结、AI Review 评分协议
  冻结、NotebookLM 输出结构冻结、隐私与安全）、(3) Prompt Mode 与未来 Video Mode 的边界、
  (4) 后续 Claude Code 修改约束（任务范围、禁止接触清单、严禁行为、验证义务、报告格式、
  冲突与歧义处理）。该文档作为后续修改的「读权威」，与之冲突的改动应先暂停并请求人工确认。

### 调整
- **稳定性脚本升级到 v0.4.10**：`scripts/run_stability_checks.py` 标题更新为
  `Prompt Mode Stability Checks - v0.4.10`，新增 `check_v0410_fixes()`：核对
  `download_all` 包内出现 `ai_review.md` 与 `metadata.json` 字符串，前端
  `getOverviewPlainText` 函数存在，`docs/prompt_mode_freeze_spec.md` 存在。脚本继续保持
  read-only：不调用外部 LLM、不修改数据库、不触发任何下载。

### 注意
- 本次未引入 Video Mode、video provider、video API、video tab、Seedance 接口或异步视频任务队列。
- 本次未修改数据库 schema、`requirements.txt`、Prompt 生成主提示词、AI Review 评分标准、
  NotebookLM Prompt 输出结构、Raw / Preview / Overview / AI Review tab 主逻辑、Regenerate
  主逻辑、版本管理主逻辑、收藏 / 置顶 / 回收站逻辑。
- 本次未提交 `.env`、`data/*.db`、`data/*.db-shm`、`data/*.db-wal`、`data/backups/*.db`、
  `outputs/`、`__MACOSX/`、`.DS_Store`、任何 API key 或真实密钥。

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
