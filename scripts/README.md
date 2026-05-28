# Scripts - AI Educational Video Generation

## 当前可用脚本

### 1. `generate_video_package.py` - 主入口脚本

完整的 video package 生成器，支持 Template Mode 和 LLM Mode。

**Template Mode（Phase 1B）**：
```bash
# 列出所有可用选题
python scripts/generate_video_package.py --list-topics

# 从 JSONL 生成 video package
python scripts/generate_video_package.py --topic-id 001 --overwrite
```

**LLM Mode（Phase 2A）**：
```bash
# Dry-run（不调用 API，只生成 prompt）
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --dry-run \
  --output-slug number_9_test

# 真实 LLM 调用（需要先配置 .env）
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --output-slug number_9
```

**主要功能**：
- Template Mode: 从 `data/topic_library_sample.jsonl` 读取 enhanced topic 生成完整文件
- LLM Mode: 输入题目 → 调用 OpenAI-compatible API → 生成 enhanced topic JSON → 生成完整文件
- 生成 notebooklm_clean_source.txt（复制到 NotebookLM 的干净版本）
- 生成 internal_review.md（内部审核文档）
- 生成其他辅助文件（narration_script.md, storyboard.md, subtitles.md 等）

**输出文件**：
```
outputs/{slug}/
├── topic.json                      # 结构化内容
├── notebooklm_clean_source.txt     # ⭐ 复制到 NotebookLM
├── notebooklm_prompt.md            # 工程版（包含使用说明）
├── internal_review.md              # 内部审核（不复制到 NotebookLM）
├── narration_script.md
├── storyboard.md
├── subtitles.md
├── qa_checklist.md
├── video_package.md
├── llm_generation_prompt.md        # LLM Mode: 生成的 prompt
├── llm_raw_response.txt            # LLM Mode: 原始返回
├── llm_error.txt                   # 错误时：API 错误记录
└── validation_errors.txt           # 错误时：校验错误记录
```

---

### 2. `llm_topic_enhancer.py` - LLM Topic Enhancer

将用户输入的题目转换为 enhanced topic JSON。

**作用**：
- 生成严格的 LLM prompt（enforces single narrator, white background, hand-drawn style）
- 调用 OpenAI-compatible API
- 解析和清理 JSON（自动去除 markdown code blocks）
- 验证 enhanced topic（20 个必需字段，6 scenes, 8-10 subtitle segments, 90-170 words）
- 错误处理：JSON parse 失败或 validation 失败时保存调试文件

**可以独立使用**：
```bash
python scripts/llm_topic_enhancer.py "为什么数字9总感觉最特别" --dry-run
```

---

## 输出文件说明

### 核心文件

| 文件 | 用途 | 是否复制到 NotebookLM |
|------|------|----------------------|
| **notebooklm_clean_source.txt** | 干净版本，只包含 20 个 NotebookLM 字段 | ✅ 复制 |
| **notebooklm_prompt.md** | 工程版，包含使用说明和元信息 | ❌ 不复制，用于备查 |
| **internal_review.md** | 内部审核：生成信息、内容指标、验证结果、质量检查清单 | ❌ 不复制 |
| **topic.json** | 结构化内容（JSON 格式） | ❌ 不复制 |

### LLM Mode 专用文件

| 文件 | 用途 |
|------|------|
| **llm_generation_prompt.md** | 发送给 LLM 的完整 prompt |
| **llm_raw_response.txt** | LLM 原始返回（未处理） |
| **llm_error.txt** | API 调用错误或配置错误 |
| **validation_errors.txt** | 结构化内容校验错误 |

### 辅助文件

- `video_package.md` - 项目管理文档
- `narration_script.md` - 旁白脚本
- `storyboard.md` - 分镜
- `subtitles.md` - 字幕
- `qa_checklist.md` - 质量检查清单

---

## 常见错误

### 1. Missing AI_VIDEO_LLM_API_KEY

**原因**：未配置 API key

**解决**：
```bash
# 复制示例配置
cp config/example.env .env

# 编辑 .env，设置 API key
nano .env

# 设置这一行：
AI_VIDEO_LLM_API_KEY=sk-your-actual-key-here

# 安装依赖
pip install -r requirements.txt
```

### 2. JSON parse failed

**原因**：LLM 返回的内容不是有效 JSON

**排查**：
1. 查看 `outputs/YOUR_SLUG/llm_raw_response.txt` - 检查 LLM 原始返回
2. 查看 `outputs/YOUR_SLUG/llm_error.txt` - 查看错误详情
3. 检查 LLM 是否返回了 markdown 代码块（系统会自动清理，但可能仍有格式问题）

**解决**：
- 尝试重新生成（有时是 LLM 随机性导致）
- 检查 `llm_generation_prompt.md` 是否正确
- 考虑调整 LLM temperature（降低可能提高稳定性）

### 3. Validation failed

**原因**：LLM 生成的 JSON 缺少必需字段或格式不正确

**排查**：
1. 查看 `outputs/YOUR_SLUG/validation_errors.txt` - 查看具体缺少哪些字段
2. 查看 `outputs/YOUR_SLUG/internal_review.md` - Validation Result 部分

**解决**：
- 尝试重新生成
- 检查 prompt 是否清晰
- 检查 LLM model 是否足够强（推荐 gpt-4o-mini 或 gpt-4o）

---

## 配置

### 环境变量（.env）

```bash
# 必需
AI_VIDEO_LLM_API_KEY=sk-...

# 可选
AI_VIDEO_LLM_BASE_URL=https://api.openai.com/v1    # 默认 OpenAI
AI_VIDEO_LLM_MODEL=gpt-4o-mini                     # 默认 gpt-4o-mini
AI_VIDEO_LLM_TEMPERATURE=0.7                       # 默认 0.7
AI_VIDEO_LLM_MAX_TOKENS=4096                       # 默认 4096
AI_VIDEO_LLM_TIMEOUT=60                            # 默认 60 秒
```

### 依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- `openai>=1.0.0` - OpenAI-compatible API client
- `python-dotenv>=1.0.0` - 自动加载 .env 文件

---

## 下一步

查看 [docs/phase_2a_usage.md](../docs/phase_2a_usage.md) 了解详细使用说明。
