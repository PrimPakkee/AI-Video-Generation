# Phase 2A Usage Guide - Title-to-NotebookLM Prompt

## 概述

Phase 2A 实现了从题目到 NotebookLM prompt 的自动化流程：

```
用户输入题目 
→ LLM 生成 enhanced topic JSON 
→ 自动生成 notebooklm_clean_source.txt 
→ 复制到 NotebookLM 生成视频
```

## 快速开始

### 1. 配置 API Key

```bash
# 复制示例配置
cp config/example.env .env

# 编辑 .env 文件
# 将 AI_VIDEO_LLM_API_KEY=put_your_api_key_here 
# 改为你的真实 API key

# 加载环境变量
source .env  # bash/zsh
# 或者
set -a; source .env; set +a  # 更通用
```

### 2. Dry-run 测试（推荐）

先用 dry-run 模式测试，不消耗 API 额度：

```bash
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --dry-run \
  --output-slug number_9_test
```

输出：
```
🚀 AI Video Generation - LLM Mode (Phase 2A)
============================================================

📝 Input Title: 为什么数字9总感觉最特别
   Mode: Dry-run (no API call)

📁 Output slug: number_9_test
   Planned output: outputs/number_9_test

🤖 Calling LLM Topic Enhancer...

📝 Generating LLM prompt for topic: 为什么数字9总感觉最特别
✅ Saved LLM prompt to: outputs/number_9_test/llm_generation_prompt.md

⚠️  Dry-run mode: Stopping here. No API call will be made.

✅ Dry-run complete!
   Generated files:
     - outputs/number_9_test/llm_generation_prompt.md

💡 提示：Dry-run 不调用 API，只生成 prompt。
   移除 --dry-run 参数以真实调用 LLM。
```

这会生成：
- `outputs/number_9_test/llm_generation_prompt.md` - 查看这个文件确认 prompt 是否正确

### 3. 真实 LLM 生成

确认 dry-run 正常后，移除 `--dry-run` 参数：

```bash
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --output-slug number_9
```

这会：
1. 调用 LLM API 生成 enhanced topic JSON
2. 验证 JSON 格式和内容
3. 生成所有输出文件

生成的文件：
```
outputs/number_9/
├── topic.json                      # Enhanced topic JSON
├── notebooklm_clean_source.txt    # ⭐ 复制这个到 NotebookLM
├── notebooklm_prompt.md            # 完整版本（包含元信息）
├── internal_review.md              # 内部审核文件
├── video_package.md                # 项目管理文件
├── narration_script.md             # 旁白脚本
├── storyboard.md                   # 分镜
├── subtitles.md                    # 字幕
├── qa_checklist.md                 # 质量检查清单
├── llm_generation_prompt.md        # LLM prompt 记录
└── llm_raw_response.txt            # LLM 原始返回
```

### 4. 复制到 NotebookLM

1. 打开 `outputs/number_9/notebooklm_clean_source.txt`
2. 复制完整内容
3. 粘贴到 NotebookLM
4. 生成视频

**重要**：只复制 `notebooklm_clean_source.txt`，不要复制 `internal_review.md` 或其他工程文件。

## 命令行参数

### Phase 2A (LLM Mode) 参数

```bash
--title TEXT              # 题目（中文或英文），必需
--mode llm                # 使用 LLM mode，必需
--dry-run                 # Dry-run 模式，不调用 API，可选
--mock-response PATH      # Mock response 文件路径（用于测试，不调用 API），可选
--output-slug SLUG        # 输出文件夹名称，可选（不指定则自动生成）
--overwrite               # 覆盖已存在的文件夹，可选
```

**--mock-response 说明**：
- 用于本地测试完整链路（title → topic.json → notebooklm_clean_source.txt）
- 不调用真实 API，直接读取 mock JSON 文件
- 会执行 JSON 验证和完整 package 生成
- 适合在没有 API key 时测试后半段流程

### Phase 1B (Template Mode) 参数

```bash
--topic-id ID         # 从 JSONL 读取的 topic ID
--overwrite           # 覆盖已存在的文件夹
```

### 通用参数

```bash
--list-topics         # 列出所有可用 topics
```

## 使用示例

### 示例 1：数学题目

```bash
python scripts/generate_video_package.py \
  --title "为什么0.999...等于1" \
  --mode llm \
  --output-slug infinite_decimal
```

### 示例 2：物理题目

```bash
python scripts/generate_video_package.py \
  --title "Why does a mirror flip left and right but not up and down?" \
  --mode llm \
  --output-slug mirror_puzzle
```

### 示例 3：概率题目

```bash
python scripts/generate_video_package.py \
  --title "蒙提霍尔问题：换门还是不换" \
  --mode llm \
  --output-slug monty_hall
```

### 示例 4：Mock Response 测试

```bash
python scripts/generate_video_package.py \
  --title "为什么数字9总感觉最特别" \
  --mode llm \
  --mock-response tests/fixtures/number_9_response.json \
  --output-slug number_9_mock \
  --overwrite
```

**说明**：
- 不需要配置 API key
- 不调用真实 API
- 测试完整链路：title → topic.json → notebooklm_clean_source.txt
- 适合本地开发和测试

## 环境变量配置

### 必需配置

```bash
AI_VIDEO_LLM_API_KEY=your_api_key_here
```

### 可选配置

```bash
# 使用其他模型
AI_VIDEO_LLM_MODEL=gpt-4o           # 默认 gpt-4o-mini

# 使用其他 API endpoint
AI_VIDEO_LLM_BASE_URL=https://your-api-endpoint.com/v1

# 调整 temperature
AI_VIDEO_LLM_TEMPERATURE=0.8        # 默认 0.7

# 调整 max tokens
AI_VIDEO_LLM_MAX_TOKENS=4096        # 默认 4096

# 调整 timeout
AI_VIDEO_LLM_TIMEOUT=90             # 默认 60 秒
```

## 错误排查

### 错误：Missing AI_VIDEO_LLM_API_KEY

**原因**：环境变量未设置

**解决**：
```bash
# 确认 .env 文件存在
ls -la .env

# 确认 API key 已填入
cat .env | grep API_KEY

# 重新加载环境变量
source .env
```

### 错误：JSON parse error

**原因**：LLM 返回的内容不是有效 JSON

**排查**：
1. 查看 `outputs/YOUR_SLUG/llm_raw_response.txt`
2. 检查 LLM 是否返回了 markdown 代码块
3. 检查 JSON 格式是否正确

**解决**：
- 尝试重新生成
- 如果持续失败，检查 `llm_generation_prompt.md` 是否正确

### 错误：Validation failed

**原因**：LLM 生成的 JSON 缺少必需字段或格式不正确

**排查**：
1. 查看 `internal_review.md` 中的 Validation Result
2. 查看具体缺少哪些字段或哪些验证规则未通过

**解决**：
- 调整 LLM temperature（降低可能提高稳定性）
- 检查 prompt 是否清晰
- 尝试不同的题目表述

## 质量检查

生成后，检查这些文件：

1. **notebooklm_clean_source.txt**
   - 20 个字段是否完整
   - 内容是否逻辑正确
   - 是否符合单人旁白风格

2. **internal_review.md**
   - Validation Result 是否全部通过
   - Word count 是否在推荐范围
   - Timeline 是否覆盖 50-60 秒

3. **qa_checklist.md**
   - 逐项检查质量标准

## 与 Phase 1B 对比

| 特性 | Phase 1B (Template Mode) | Phase 2A (LLM Mode) |
|------|---------------------------|---------------------|
| 输入 | Topic ID（从 JSONL） | 题目（任意题目） |
| LLM 调用 | 不调用 | 调用 LLM API |
| 输出 | 完整 video package | 完整 video package + clean source |
| 适用场景 | 已有 enhanced topic | 任意新题目 |
| 速度 | 秒级 | 取决于 API 响应（通常 10-30 秒） |
| 成本 | 免费 | API token 费用 |

## 最佳实践

1. **先用 dry-run 测试**
   - 确认 prompt 生成正确
   - 避免浪费 API 额度

2. **检查生成质量**
   - 使用 internal_review.md 记录质量问题
   - 使用 qa_checklist.md 系统化检查

3. **保存成功的配置**
   - 记录好用的题目表述方式
   - 记录有效的 LLM 参数配置

4. **批量生成时注意**
   - API rate limit
   - Token 消耗成本
   - 生成质量一致性

## 下一步

- Phase 2B: 批量处理（批量题目输入，并发 LLM 调用）
- Phase 3: 视觉和音频生成
- Phase 4: 端到端 mp4 输出
