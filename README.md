# AI Video Generation - AI Educational Video Workflow Engine

## 项目简介

这是一个面向 Think Academy 海外业务的 **AI 教育短视频工作流引擎（AI Educational Video Workflow Engine）**。

**最终长期目标**：输入一个选题 → 自动输出可发布的 mp4 短视频。

**当前短期目标（Phase 2A）**：输入题目 → 自动生成可投喂 NotebookLM 的高质量 prompt。

**当前阶段定位**：
- 本项目负责：自动生成 NotebookLM source prompt
- NotebookLM 负责：执行视频生成（根据我们的 prompt 生成视频）
- 最终演进：完全替代 NotebookLM，实现端到端 mp4 输出

这个项目将逐步发展成一个端到端的自动化视频生产流水线，从选题到成片，尽量减少人工干预。

## 解决的问题

### 当前流程的痛点
- ❌ 流程分散：需要在 ChatGPT、NotebookLM、Gamma、即梦 AI、剪映之间反复切换
- ❌ 人工搬运：每个环节都需要人工复制粘贴
- ❌ 标准不一致：每次生成的风格、结构、质量都不稳定
- ❌ 效率低下：一条视频从选题到成片需要数小时
- ❌ 难以复用：没有标准化模板，每次都从头开始

### 我们的解决方案
- ✅ 标准化流程：将经验沉淀为模板和规范
- ✅ 结构化输出：20-field NotebookLM prompt structure
- ✅ 风格一致性：内置 Think Academy AI 教育短视频风格指南
- ✅ 自动化生成：从任意题目自动生成 NotebookLM prompt
- ✅ 质量保证：内置质量检查清单

## 版本路线图

### Phase 1: Template Mode（已完成 ✅）
**Phase 1A**: 基础模板体系
- ✅ 完整的项目文档体系
- ✅ 20-field NotebookLM prompt 标准
- ✅ 示例选题库（JSONL 格式）

**Phase 1B**: Enhanced Template Mode（已完成 ✅）
- ✅ 自动生成完整 video package（从 enhanced topic data）
- ✅ 支持 50-60 秒视频结构
- ✅ 词数、时间轴、模式命名一致性
- ✅ Topic 001 可作为 NotebookLM 测试样例

### Phase 2: LLM-Powered Generation（当前阶段 🚧）
**Phase 2A**: Title-to-NotebookLM Prompt MVP（进行中 🚧）
- ✅ **输入**：任意教育短视频题目（不依赖 topic_library_sample.jsonl）
  - 例如："为什么数字9总感觉最特别"
  - 例如："为什么0.999...等于1"
  - 例如："为什么排队总觉得旁边那队更快"
- ✅ **处理**：调用 LLM 自动生成 enhanced topic JSON
- ✅ **输出**：notebooklm_clean_source.txt（可直接复制到 NotebookLM）
- ✅ 支持 OpenAI-compatible API
- ✅ dry-run 模式（不调用 API，只生成 prompt）
- ✅ mock-response 模式（本地测试，不调用 API）

**Phase 2B**: Batch Processing
- ⏳ 批量题目输入
- ⏳ 并发 LLM 调用
- ⏳ 批量生成 NotebookLM prompts

### Phase 3: Visual & Audio Generation
- ⏳ 接入视觉生成 API（图像/动画）
- ⏳ 接入 TTS（文本转语音）
- ⏳ 字幕自动对齐

### Phase 4: End-to-End Video Pipeline
- ⏳ ffmpeg 视频合成
- ⏳ 自动化后期处理
- ⏳ 端到端输出 mp4
- ⏳ 自动质量评分
- ⏳ 根据视频表现数据优化 Prompt

## 项目结构

```
AI Video Generation/
├── README.md                          # 项目总览（当前文件）
├── docs/                              # 产品文档
│   ├── product_brief.md               # 产品需求文档
│   ├── workflow.md                    # 完整工作流说明
│   ├── style_guide.md                 # Think Academy AI 视频风格指南
│   └── prompt_schema.md               # 结构化输出 Schema
├── templates/                         # 可复用模板库
│   ├── notebooklm_prompt_template.md  # NotebookLM Prompt 模板
│   ├── storyboard_template.md         # 分镜模板
│   └── qa_checklist_template.md       # 质量检查清单模板
├── data/                              # 选题库和数据
│   └── topic_library_sample.jsonl     # 示例选题库（JSONL 格式）
├── outputs/                           # 输出文件存放处
├── assets/                            # 视觉资源和素材
└── scripts/                           # 当前可运行的自动化脚本
```

## 快速开始

### Phase 2A: Title-to-NotebookLM Prompt（推荐）

**前置要求**：
1. Python 3.8+
2. OpenAI-compatible API（可选，dry-run 不需要）

**配置 API（可选）**：
```bash
# 复制示例配置
cp config/example.env .env

# 编辑 .env，填入你的 API 信息
# AI_VIDEO_LLM_PROVIDER=openai_compatible
# AI_VIDEO_LLM_BASE_URL=https://api.openai.com/v1
# AI_VIDEO_LLM_MODEL=gpt-4o-mini
# AI_VIDEO_LLM_API_KEY=your_api_key_here

# 加载环境变量
source .env  # bash/zsh
# 或者
set -a; source .env; set +a  # 更通用的方式
```

**使用方法**：

**1. Dry-run 模式（推荐先测试）**：
```bash
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --dry-run \
  --output-slug number_9_test
```
这会生成 LLM prompt 但不调用 API。

**2. LLM 生成模式**：
```bash
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --output-slug number_9
```
这会调用 LLM 生成完整的 NotebookLM prompt。

**3. 使用已有 topic（Phase 1B 模式）**：
```bash
python scripts/generate_video_package.py --topic-id 001 --overwrite
```
从 topic_library_sample.jsonl 中读取已增强的题目。

**输出文件**：
- `notebooklm_clean_source.txt` - **复制这个到 NotebookLM**
- `video_package.md` - 内部项目管理
- `internal_review.md` - 质量审核记录
- `llm_generation_prompt.md` - LLM 调用记录
- `llm_raw_response.txt` - LLM 原始返回

### Phase 1: Template Mode（手动模式）

如果不使用 LLM，可以手动填充模板：
1. 打开 `templates/notebooklm_prompt_template.md`
2. 根据题目填充所有字段
3. 复制到 NotebookLM 生成视频

## 面向的平台和受众

- **平台**：TikTok、YouTube Shorts、Instagram Reels、小红书
- **受众**：海外学生和家长
- **时长**：30-90 秒短视频
- **语言**：英语（面向海外市场）

## 核心风格原则

⭐ **必须**：
- Single narrator / 单人旁白 / monologue narration
- 白底线稿、简洁图示
- 大而清晰的字幕
- 前后一致的核心图示
- 逻辑正确的推理过程

❌ **禁止**：
- 双人对话、访谈、播客、多人讨论
- 复杂背景、无关装饰、随机人物/动物
- 黑色背景、恐怖风格
- 为了效果牺牲答案准确性

## 两种工作流模式

### 模式 A：NotebookLM Prompt Mode（当前支持）
```
输入题目 
→ 填充 NotebookLM Prompt 模板 
→ 人工复制到 NotebookLM 
→ NotebookLM 生成视频 
→ 在剪映中后期调整
```
**适用场景**：利用 NotebookLM 的视频生成能力，人工介入较多

### 模式 B：Direct Video Pipeline Mode（未来目标）
```
输入题目 
→ 自动生成脚本、分镜 
→ 自动生成画面提示词 
→ 自动生成旁白音频 
→ 自动生成字幕文件 
→ ffmpeg 自动合成 
→ 输出 mp4 视频
```
**适用场景**：完全自动化，批量生产，无需人工介入

详见 `docs/workflow.md` 和 `docs/technical_roadmap.md`

---

## 两种生成模式（Template Mode / LLM Mode）

本项目在内容生成层面支持两种模式，方便不同阶段使用：

### Template Mode（Legacy / Testing Only）
**说明**：
- **主要用途**：回归测试、golden sample 对比
- 不调用任何外部 API
- 不消耗模型 token，零成本
- 只读取 `data/topic_library_sample.jsonl` 和 `templates/`
- **限制**：必须先把题目写入 topic_library_sample.jsonl（不适合随时输入任意题目）
- 生成结构完整但带 TODO 占位符的 video package（如果 topic 包含 enhanced fields，则生成完整内容）

**使用场景**：
- 回归测试：确保代码改动不破坏现有功能
- Golden sample：Topic 001 作为标准参考
- 测试模板设计是否合理
- 团队内部流程培训

**命令示例**：
```bash
python scripts/generate_video_package.py --topic-id 001
# 使用 Template Mode（legacy）
```

**⚠️ 注意**：这不是主产品路径。真正使用时，请用 LLM Mode（输入任意题目，不需要预先写入 JSONL）。

### LLM Mode（Phase 2A，**主产品路径** ⭐）
**说明**：
- **这是主入口**：用户输入任意题目，不需要预先写入 topic_library_sample.jsonl
- 调用 OpenAI-compatible API（支持 ChatGPT、gpt-4o-mini、gpt-4o 及其他兼容 API）
- LLM 自动补全所有字段：
  - title_en、topic_label_en、core_concept
  - full_problem、question、correct_answer、wrong_intuition
  - reasoning_steps、narration_script
  - subtitle_segments、storyboard_scenes
  - notebooklm_specific_instructions
- 需要通过 `.env` 文件配置 API_KEY、BASE_URL、MODEL_NAME
- **绝对不要把 API Key 写死在代码里**

**使用场景**：
- **主要使用场景**：任意题目输入 → 立即生成 NotebookLM prompt
- 快速从题目生成完整 video package
- 自动化内容生产流程

**命令示例**：
```bash
# Dry-run（不调用 API，只生成 prompt）
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --dry-run

# Mock response（测试完整链路，不调用 API）
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --mock-response tests/fixtures/number_9_response.json

# 真实 LLM 调用（需要先配置 .env）
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm
```

**当前状态**：
1. ✅ Dry-run 已完成
2. ✅ API 调用框架已完成
3. ⏳ 需要配置 .env 中的 AI_VIDEO_LLM_API_KEY 后进行真实 API 测试

**配置步骤**：
```bash
cp config/example.env .env
# 编辑 .env，设置你的 API key
pip install -r requirements.txt
```

---

## 适用人群

- **产品经理**：理解工作流，优化流程
- **内容运营**：使用模板批量生产视频资料
- **视频编导**：遵循风格指南保证质量一致性
- **技术开发**：未来实现自动化脚本

## 贡献指南

目前项目处于 MVP 阶段，主要工作：
1. 优化 LLM prompt 模板（`scripts/llm_topic_enhancer.py`）
2. 测试任意题目生成效果
3. 记录 NotebookLM 生成结果
4. 迭代 notebooklm_clean_source.txt 的风格约束

## 联系方式

- 项目负责人：Think Academy 海外业务产品实习生
- 使用场景：AI 教育短视频生产
- 更新频率：根据实际使用反馈迭代

---

**版本**：v0.2.0-phase2a  
**最后更新**：2026-05-14  
**状态**：Phase 2A MVP ready for real API smoke test
