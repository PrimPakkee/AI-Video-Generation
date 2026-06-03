# AI Video Generation - 技术路线图（Technical Roadmap）

## 文档说明

本文档详细规划了从当前版本（V0）到端到端自动化（V4）的完整技术路线。每个 Phase 都有明确的技术目标、实现方案、技术栈和成功标准。

## 当前里程碑（v0.6.0）

- **Prompt Mode**：v0.4.10 已冻结，所有保护边界继续生效（详见
  [`prompt_mode_freeze_spec.md`](./prompt_mode_freeze_spec.md)）。
- **Video Mode 框架**：v0.5.2 完成独立数据库 / API / 6 tab / 播放器骨架 / 全局
  tooltip portal（详见 [`v0.5.2_video_mode_framework.md`](./v0.5.2_video_mode_framework.md)）。
- **Video Mode Job/Provider/Asset 基础层（v0.5.3）**：新增 `video_jobs` 表、
  `VideoProvider` 抽象层、`MockVideoProvider`、Job/Asset endpoint、首页
  `Generate Video` 动态入口、多阶段进度面板、Video Job 状态面板（详见
  [`v0.5.3_video_job_provider_framework.md`](./v0.5.3_video_job_provider_framework.md)）。
- **Video Content Asset Pipeline（v0.5.4）**：LLM 驱动的 7 个内容资产、9 步
  进度面板、Download All 升级、`AI_VIDEO_LLM_*` 配置体系（详见
  [`v0.5.4_video_content_asset_pipeline.md`](./v0.5.4_video_content_asset_pipeline.md)）。
- **Seedance Provider Contract Adapter（v0.5.5）**：新增 dry-run 契约
  适配器 `SeedanceContractAdapter`、3 个新契约文件（`seedance_payload_preview.json`
  / `provider_contract_validation.json` / `provider_lifecycle_preview.json`）、
  4 个 dry-run API 端点、Provider Contract Summary 区块、stage 升级到
  `contract_ready` / progress=90（详见
  [`v0.5.5_seedance_provider_contract_adapter.md`](./v0.5.5_seedance_provider_contract_adapter.md)）。
- **Seedance Prompt Compiler（v0.5.6）**：新增离线
  `SeedancePromptCompiler` 编译器（`compiler_version=
  seedance_prompt_compiler_v0.5.6`）+ provider profile
  (`config/provider_profiles/seedance.json`)；落 3 个新资产文件
  `seedance_prompt.txt` / `seedance_negative_prompt.txt` /
  `seedance_prompt_debug.json`；`seedance_payload_preview.json` 升级到
  `seedance_payload_preview_v0.5.6`，`payload.prompt` 优先取自 compiled
  prompt；Overview 新增 *Seedance Prompt Compiler: Ready / Not Available*
  行（详见
  [`v0.5.6_seedance_prompt_compiler.md`](./v0.5.6_seedance_prompt_compiler.md)）。
- **APX Seedance Real Provider（当前 v0.6.0）**：首次接入公司 APX 异步视频
  网关（底层 `doubao-seedance-2.0`），新增
  `web/video_providers/apx_seedance_provider.py`（仅此文件允许真实网络调用），
  把 v0.5.6 编译好的 `seedance_prompt.txt` 真正打到
  `POST /v1/async/chat`、轮询 `GET /v1/async/results/{id}`、成功后下载
  `response.video_url` 到 `outputs/<slug>/video.mp4` 并写入
  `video_history.video_file_path`，前端经
  `/api/video/history/{id}/asset/video` 播放本地 mp4。所有调用由
  `APX_VIDEO_ENABLED=true` + `APX_VIDEO_API_KEY` 显式开启；未配置时自动
  fallback 到 v0.5.3 Mock。新增 `blocked_fallback_prompt` 安全状态，避免
  在 fallback 资产上烧掉 APX 配额。`api-key` 永不入库 / 不写入 metadata /
  不出现在 Download All（详见
  [`v0.6.0_apx_seedance_real_provider.md`](./v0.6.0_apx_seedance_real_provider.md)）。
- **下一阶段**：基于 v0.6.0 的真实视频产物，引入 Video Review 独立评分
  协议、批量批处理、retry / cancel 真实 job、以及更细的失败状态机；
  Mock provider 与 prompt compiler 继续保留作为离线测试与回归基线。

---

## Phase 0: 项目文档和模板体系（已完成）

### 目标
建立标准化的视频生产规范和可复用的模板体系，为后续自动化打下基础。

### 核心交付物
- ✅ 产品需求文档（PRD）
- ✅ 完整工作流文档
- ✅ Think Academy AI 视频风格指南
- ✅ 结构化输出 Schema 定义
- ✅ NotebookLM Prompt 模板
- ✅ 分镜模板
- ✅ 质量检查清单模板
- ✅ 示例选题库（20 条）

### 技术栈
- Markdown 文档
- JSONL 数据格式
- 模板设计

### 成功标准
- ✅ 团队成员能够使用模板独立产出视频资料
- ✅ 每条视频资料生成时间 < 30 分钟
- ✅ 风格一致性 > 80%

### 当前状态
**已完成** - 2026-05-13

---

## Phase 1: CLI 工具与自动生成 Video Package

### 目标
开发 CLI 工具，输入题目后自动生成完整的视频生产资料（video package），包括脚本、分镜、旁白、字幕、NotebookLM Prompt。

### 核心功能
1. **命令行接口（CLI）**
   ```bash
   python scripts/generate_video_package.py --topic "题目文本"
   ```

2. **自动生成脚本**
   - 调用 ChatGPT API（GPT-4）
   - 生成题目重写、核心概念、钩子、题面、答案、推理过程、旁白

3. **自动生成分镜**
   - 根据脚本生成 5-8 个镜头
   - 每个镜头包含时间戳、画面描述、字幕、画面提示词

4. **自动填充 NotebookLM Prompt 模板**
   - 使用 Jinja2 模板引擎
   - 将生成的内容填充到模板

5. **自动保存**
   - 保存到 `outputs/{id}_{title}_{date}/` 文件夹
   - 包含 Markdown 和 JSON 两种格式

6. **自动质量检查**
   - 检查脚本完整性
   - 检查是否符合风格规范
   - 生成质量检查报告

### 技术栈
- **语言**：Python 3.10+
- **框架**：Click（CLI）、Jinja2（模板引擎）
- **API**：OpenAI API（GPT-4）
- **数据格式**：JSON、JSONL、Markdown
- **配置管理**：YAML / TOML

### 项目结构
```
scripts/
├── generate_video_package.py       # 主入口
├── modules/
│   ├── script_generator.py         # 脚本生成模块
│   ├── storyboard_generator.py     # 分镜生成模块
│   ├── prompt_builder.py           # NotebookLM Prompt 构建模块
│   ├── quality_checker.py          # 质量检查模块
│   └── file_manager.py             # 文件管理模块
├── templates/
│   └── notebooklm_prompt.jinja2    # Jinja2 模板
└── config/
    └── settings.yaml               # 配置文件
```

### 实现步骤
1. **Week 1-2**：搭建 CLI 框架，实现基础命令
2. **Week 3-4**：实现脚本生成模块（调用 OpenAI API）
3. **Week 5-6**：实现分镜生成模块
4. **Week 7**：实现 NotebookLM Prompt 构建模块
5. **Week 8**：实现质量检查模块
6. **Week 9**：测试和优化
7. **Week 10**：编写文档和示例

### 成功标准
- ✅ CLI 工具可用，命令简洁
- ✅ 自动生成的脚本质量 > 80 分（人工评分）
- ✅ 每条视频资料生成时间从 30 分钟降低到 5 分钟
- ✅ 自动质量检查通过率 > 90%

### 预计时间
**10 周（2.5 个月）**

---

## Phase 2: 批量处理与结构化输出

### 目标
支持批量处理选题库，结构化输出，便于后续工具读取和分析。

### 核心功能
1. **批量处理模式**
   ```bash
   python scripts/run_pipeline.py --batch --input data/topic_library_sample.jsonl
   ```

2. **并行处理**
   - 使用多线程/多进程
   - 充分利用 CPU/GPU 资源
   - 避免 API 速率限制

3. **数据库存储**
   - 使用 SQLite 存储视频资料
   - 记录生成历史、质量评分、状态

4. **结构化输出**
   - JSON/YAML 格式
   - 符合 `docs/prompt_schema.md` 定义的 Schema
   - 便于后续工具读取

5. **进度追踪**
   - 实时显示批量处理进度
   - 失败重试机制
   - 生成批量处理报告

6. **A/B 测试支持**
   - 同一题目生成多个版本
   - 对比不同 Prompt 策略的效果

### 技术栈
- **并行处理**：`concurrent.futures` / `asyncio`
- **数据库**：SQLite
- **数据验证**：Pydantic
- **进度显示**：tqdm
- **日志**：loguru

### 项目结构
```
scripts/
├── run_pipeline.py                 # 批量处理主入口
├── modules/
│   ├── batch_processor.py          # 批量处理模块
│   ├── database.py                 # 数据库模块
│   ├── progress_tracker.py         # 进度追踪模块
│   └── report_generator.py         # 报告生成模块
└── config/
    └── batch_settings.yaml         # 批量处理配置
```

### 实现步骤
1. **Week 1-2**：搭建批量处理框架
2. **Week 3-4**：实现并行处理和进度追踪
3. **Week 5-6**：实现数据库存储
4. **Week 7-8**：实现结构化输出和数据验证
5. **Week 9-10**：实现 A/B 测试支持
6. **Week 11-12**：测试和优化

### 成功标准
- ✅ 批量生成 100 条视频资料的时间 < 10 小时
- ✅ 自动质量检查通过率 > 90%
- ✅ 结构化输出格式稳定，可被后续工具读取
- ✅ 并行处理稳定，无死锁或资源泄漏

### 预计时间
**12 周（3 个月）**

---

## Phase 3: TTS 音频生成

### 目标
自动将旁白文案转换为音频文件，支持多种 TTS 服务。

### 核心功能
1. **TTS API 集成**
   - ElevenLabs（推荐，音质最好）
   - Azure TTS
   - OpenAI TTS
   - Google Cloud TTS

2. **音频生成**
   ```bash
   python scripts/generate_audio.py --script outputs/{id}_script.json
   ```

3. **音频配置**
   - 选择语音（voice）
   - 调整语速（speed）
   - 调整音调（pitch）
   - 添加停顿（pause）

4. **音频后处理**
   - 音量归一化
   - 降噪处理
   - 添加背景音乐（可选）

5. **音频质量检查**
   - 时长是否符合目标
   - 音频是否清晰
   - 是否有杂音

### 技术栈
- **TTS 服务**：ElevenLabs API / Azure TTS / OpenAI TTS
- **音频处理**：pydub、ffmpeg
- **音频分析**：librosa

### 项目结构
```
scripts/
├── generate_audio.py               # 音频生成主入口
├── modules/
│   ├── tts_client.py               # TTS 客户端（支持多个服务）
│   ├── audio_processor.py          # 音频后处理模块
│   └── audio_analyzer.py           # 音频质量分析模块
└── config/
    └── audio_settings.yaml         # 音频配置
```

### 实现步骤
1. **Week 1-2**：集成 ElevenLabs API
2. **Week 3-4**：集成其他 TTS 服务
3. **Week 5-6**：实现音频后处理
4. **Week 7-8**：实现音频质量检查
5. **Week 9-10**：测试和优化

### 成功标准
- ✅ 音频生成时间 < 2 分钟/条
- ✅ 音频清晰度 > 90 分
- ✅ 音频时长与旁白文案匹配（误差 < 5%）
- ✅ 支持至少 2 种 TTS 服务

### 预计时间
**10 周（2.5 个月）**

---

## Phase 4: 视频素材生成与导入

### 目标
自动生成或导入视频所需的视觉素材（图片、视频片段）。

### 核心功能
1. **图片生成**
   - 调用 DALL-E / Midjourney / Stable Diffusion
   - 根据画面提示词生成图片
   - 批量生成所有镜头的图片

2. **视频片段生成**
   - 调用 Runway / Pika / Luma AI
   - 将静态图片转换为短视频片段
   - 添加简单动效（缩放、平移、淡入淡出）

3. **素材库管理**
   - 建立可复用的素材库
   - 例如：硬币、人脸、树状图等常见图示
   - 避免重复生成，节省成本

4. **素材质量检查**
   - 图片分辨率是否足够
   - 视觉风格是否一致
   - 是否符合风格指南

### 技术栈
- **图片生成**：OpenAI DALL-E API / Stable Diffusion / ComfyUI
- **视频生成**：Runway API / Pika API / Luma AI API
- **素材管理**：本地文件系统 / 云存储（S3）

### 项目结构
```
scripts/
├── generate_visuals.py             # 视觉素材生成主入口
├── modules/
│   ├── image_generator.py          # 图片生成模块
│   ├── video_generator.py          # 视频片段生成模块
│   ├── asset_manager.py            # 素材库管理模块
│   └── visual_checker.py           # 视觉质量检查模块
└── config/
    └── visual_settings.yaml        # 视觉素材配置
```

### 实现步骤
1. **Week 1-3**：集成 DALL-E / Stable Diffusion
2. **Week 4-6**：集成 Runway / Pika
3. **Week 7-8**：实现素材库管理
4. **Week 9-10**：实现视觉质量检查
5. **Week 11-12**：测试和优化

### 成功标准
- ✅ 图片生成时间 < 30 秒/张
- ✅ 视频片段生成时间 < 2 分钟/片段
- ✅ 视觉风格一致性 > 85%
- ✅ 素材复用率 > 30%（降低成本）

### 预计时间
**12 周（3 个月）**

---

## Phase 5: ffmpeg 自动合成

### 目标
使用 ffmpeg 自动将音频、画面、字幕合成为完整的 mp4 视频。

### 核心功能
1. **视频合成**
   ```bash
   python scripts/assemble_video.py --project outputs/{id}/
   ```

2. **时间轴管理**
   - 按分镜顺序排列画面素材
   - 确保音频和画面同步
   - 添加过渡效果（淡入淡出、交叉溶解）

3. **字幕烧录**
   - 根据 SRT 文件烧录字幕
   - 字幕样式：大字体、白色字 + 黑色描边
   - 字幕位置：屏幕中下部

4. **画面调整**
   - 裁剪为 9:16（竖屏）或 16:9（横屏）
   - 分辨率：1080x1920（竖屏）或 1920x1080（横屏）
   - 帧率：30fps

5. **音频处理**
   - 音量归一化
   - 添加背景音乐（可选）
   - 混音平衡

### 技术栈
- **视频合成**：ffmpeg（通过 Python subprocess 调用）
- **视频处理**：moviepy
- **字幕处理**：pysrt

### 项目结构
```
scripts/
├── assemble_video.py               # 视频合成主入口
├── modules/
│   ├── timeline_manager.py         # 时间轴管理模块
│   ├── subtitle_burner.py          # 字幕烧录模块
│   ├── video_compositor.py         # 视频合成模块
│   └── ffmpeg_wrapper.py           # ffmpeg 封装模块
└── config/
    └── video_settings.yaml         # 视频合成配置
```

### 实现步骤
1. **Week 1-2**：搭建 ffmpeg 封装模块
2. **Week 3-4**：实现时间轴管理
3. **Week 5-6**：实现字幕烧录
4. **Week 7-8**：实现视频合成
5. **Week 9-10**：实现音频处理
6. **Week 11-12**：测试和优化

### 成功标准
- ✅ 视频合成时间 < 3 分钟/条
- ✅ 音频和画面同步误差 < 100ms
- ✅ 字幕准确率 > 95%
- ✅ 视频分辨率和帧率符合标准

### 预计时间
**12 周（3 个月）**

---

## Phase 6: 字幕自动生成与烧录

### 目标
自动根据旁白文案生成字幕文件（SRT），并提供字幕样式定制。

### 核心功能
1. **字幕生成**
   ```bash
   python scripts/generate_subtitles.py --script outputs/{id}_script.json
   ```

2. **时间轴对齐**
   - 根据旁白音频生成精确的时间戳
   - 使用语音识别（ASR）对齐
   - 手动调整工具

3. **字幕样式**
   - 字体：Sans-serif（例如：Arial、Roboto）
   - 字号：大（占屏幕 1/5-1/4）
   - 颜色：白色字 + 黑色描边
   - 位置：屏幕中下部
   - 高亮：关键词用黄色背景框

4. **字幕优化**
   - 断句合理（每句 1-2 秒）
   - 关键词高亮
   - 表情符号（可选）

### 技术栈
- **语音识别**：Whisper（OpenAI）/ Google Cloud Speech-to-Text
- **字幕格式**：SRT / VTT
- **字幕处理**：pysrt

### 项目结构
```
scripts/
├── generate_subtitles.py           # 字幕生成主入口
├── modules/
│   ├── subtitle_generator.py       # 字幕生成模块
│   ├── timestamp_aligner.py        # 时间戳对齐模块
│   └── subtitle_styler.py          # 字幕样式模块
└── config/
    └── subtitle_settings.yaml      # 字幕配置
```

### 实现步骤
1. **Week 1-2**：集成 Whisper ASR
2. **Week 3-4**：实现时间戳对齐
3. **Week 5-6**：实现字幕样式定制
4. **Week 7-8**：实现字幕优化（断句、高亮）
5. **Week 9-10**：测试和优化

### 成功标准
- ✅ 字幕生成时间 < 1 分钟/条
- ✅ 字幕准确率 > 95%
- ✅ 时间戳对齐误差 < 100ms
- ✅ 字幕样式符合风格指南

### 预计时间
**10 周（2.5 个月）**

---

## Phase 7: 完整端到端工作流

### 目标
整合所有 Phase，实现从题目到 mp4 视频的完整自动化流程。

### 核心功能
1. **一键生成**
   ```bash
   python scripts/run_pipeline.py --topic "题目文本" --output-video
   ```

2. **完整流程**
   - Phase 1: 生成脚本
   - Phase 2: 生成分镜
   - Phase 3: 生成旁白音频
   - Phase 4: 生成视觉素材
   - Phase 6: 生成字幕
   - Phase 5: 合成视频
   - 自动质量检查
   - 保存到 `outputs/{id}/{id}_final.mp4`

3. **质量评分**
   - 内容准确性评分
   - 视觉风格评分
   - 传播潜力评分
   - 综合评分

4. **数据分析**
   - 根据视频表现数据（播放量、完播率、点赞率）优化 Prompt
   - A/B 测试不同风格
   - 自动生成优化建议

5. **平台集成（可选）**
   - 自动上传到 TikTok / YouTube Shorts
   - 自动发布
   - 自动监控表现

### 技术栈
- **工作流编排**：Airflow / Prefect / 自定义
- **质量评分**：机器学习模型（分类器）
- **数据分析**：Pandas、Matplotlib
- **平台 API**：TikTok API / YouTube API

### 项目结构
```
scripts/
├── run_pipeline.py                 # 完整流程主入口
├── modules/
│   ├── workflow_orchestrator.py    # 工作流编排模块
│   ├── quality_scorer.py           # 质量评分模块
│   ├── data_analyzer.py            # 数据分析模块
│   └── platform_uploader.py        # 平台上传模块
└── config/
    └── pipeline_settings.yaml      # 完整流程配置
```

### 实现步骤
1. **Week 1-4**：整合所有 Phase
2. **Week 5-6**：实现工作流编排
3. **Week 7-8**：实现质量评分
4. **Week 9-10**：实现数据分析
5. **Week 11-12**：实现平台集成（可选）
6. **Week 13-16**：测试、优化、文档

### 成功标准
- 🎯 视频生成时间 < 10 分钟/条（从题目到 mp4）
- 🎯 自动生成的视频质量 > 85 分
- 🎯 无需人工介入即可发布
- 🎯 视频表现（播放量、完播率）与人工制作视频持平或更好
- 🎯 批量生产 100 条视频的时间 < 20 小时

### 预计时间
**16 周（4 个月）**

---

## 总体时间线

| Phase | 名称 | 预计时间 | 累计时间 | 状态 |
|-------|------|---------|---------|------|
| Phase 0 | 项目文档和模板 | - | - | ✅ 已完成 |
| Phase 1 | CLI 工具与自动生成 | 10 周 | 10 周 | 🔜 即将开始 |
| Phase 2 | 批量处理 | 12 周 | 22 周 | ⏳ 待开始 |
| Phase 3 | TTS 音频生成 | 10 周 | 32 周 | ⏳ 待开始 |
| Phase 4 | 视频素材生成 | 12 周 | 44 周 | ⏳ 待开始 |
| Phase 5 | ffmpeg 合成 | 12 周 | 56 周 | ⏳ 待开始 |
| Phase 6 | 字幕生成 | 10 周 | 66 周 | ⏳ 待开始 |
| Phase 7 | 端到端工作流 | 16 周 | 82 周 | ⏳ 待开始 |

**总计**：约 **82 周（20 个月）** 从 V0 到 V4。

**注**：Phase 3-6 可以部分并行开发，实际时间可缩短至 **12-15 个月**。

---

## 技术栈总览

### 后端
- **语言**：Python 3.10+
- **框架**：Click（CLI）、FastAPI（可选，用于 Web 界面）
- **数据库**：SQLite / PostgreSQL
- **任务队列**：Celery（可选，用于异步任务）

### AI / ML
- **LLM**：OpenAI GPT-4
- **TTS**：ElevenLabs / Azure TTS / OpenAI TTS
- **图片生成**：DALL-E / Stable Diffusion
- **视频生成**：Runway / Pika / Luma AI
- **ASR**：Whisper（OpenAI）

### 视频处理
- **视频合成**：ffmpeg
- **视频处理**：moviepy
- **音频处理**：pydub
- **字幕处理**：pysrt

### 数据与配置
- **数据格式**：JSON、JSONL、YAML
- **数据验证**：Pydantic
- **配置管理**：YAML / TOML

### 前端（可选）
- **Web 界面**：Streamlit / Gradio
- **可视化**：Matplotlib、Plotly

---

## 成本估算

### Phase 1-2（V1）
- OpenAI API：~$5-10 / 条视频资料
- 总成本（100 条）：~$500-1000

### Phase 3-6（V3）
- TTS（ElevenLabs）：~$2-5 / 条
- 图片生成（DALL-E）：~$3-6 / 条（5-8 张图）
- 视频生成（Runway）：~$10-20 / 条（5-8 个片段）
- 总成本（100 条）：~$1500-3000

### Phase 7（V4）
- 完整流程成本：~$15-30 / 条视频
- 批量生产（100 条）：~$1500-3000
- 加上数据分析和优化：~$2000-4000

**优化建议**：
- 建立可复用素材库，降低图片/视频生成成本
- 使用开源模型（Stable Diffusion）替代商业 API
- 批量处理时使用折扣或企业套餐

---

## 风险与挑战

### 技术风险
1. **API 稳定性**：依赖多个第三方 API，任何一个不稳定都会影响流程
2. **视频质量**：自动生成的视频初期可能不如 NotebookLM
3. **成本控制**：大量调用 API 成本较高

### 解决方案
- 实现多个 API 的 fallback 机制
- 建立人工审核流程（V3 初期）
- 优化 Prompt 减少 API 调用次数

---

**文档版本**：v1.0  
**编写日期**：2026-05-13  
**下次审阅**：Phase 1 开发前  
**负责人**：Think Academy 产品实习生
