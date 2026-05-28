# AI Video Generation - 完整工作流文档

## 一、工作流总览

本项目支持两种工作模式：

### 模式 A：NotebookLM Prompt Mode（当前版本）
```
输入题目 
→ 生成 NotebookLM Prompt 
→ 人工复制到 NotebookLM 
→ NotebookLM 生成视频 
→ 在剪映中后期调整 
→ 输出 mp4 视频
```
**适用阶段**：V0（人工填充）、V1（自动生成 Prompt）、V2（批量处理）

### 模式 B：Direct Video Pipeline Mode（未来版本）
```
输入题目 
→ 自动生成脚本、分镜 
→ 自动生成画面提示词 
→ 调用图片/视频生成 API 
→ 调用 TTS 生成旁白音频 
→ 自动生成字幕文件 
→ ffmpeg 自动合成 
→ 输出 mp4 视频
```
**适用阶段**：V3（半自动）、V4（全自动）

---

## 二、模式 A：NotebookLM Prompt Mode（当前支持）

### 工作流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                         输入层                                   │
│  从选题库选择一个题目（或手动输入新题目）                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    处理层（V0 为人工，V1+ 为自动）                │
│  1. 打开 NotebookLM Prompt 模板                                  │
│  2. 填充题目信息到模板                                            │
│  3. 填充分镜模板                                                  │
│  4. 检查 QA Checklist                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         输出层                                   │
│  完整的视频生产资料（15 个标准字段）                              │
│  保存到 outputs/ 文件夹                                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      外部工具使用                                 │
│  1. 复制 Prompt 到 NotebookLM 生成视频                           │
│  2. （可选）Gamma 生成图 + 即梦 AI 让图动起来                    │
│  3. 在剪映中合成视频、口播、字幕                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 二、详细步骤说明

### 阶段 1：选题准备（5 分钟）

#### 步骤 1.1：从选题库选择题目
1. 打开 `data/topic_library_sample.jsonl`（JSONL 格式，每行一个 JSON object）
2. 筛选条件：
   - `status` = `pending`（未使用的题目）
   - `visual_feasibility` = `high` 或 `medium`（可视化难度不要太高）
   - `viral_potential` = `high`（优先选传播潜力高的）
3. 选定一个题目，记下 `id`、`title_cn`、`title_en`、`core_concept`

**示例**：
```
id: 001
category: 概率论
title_cn: 连续5次正面后,下一次更可能反面吗
title_en: The Coin Toss Trap
core_concept: Gambler's Fallacy（赌徒谬误）
target_duration: 45s
```

#### 步骤 1.2：确认题目信息完整
检查题目是否包含：
- [ ] 清晰的问题陈述
- [ ] 明确的答案
- [ ] 可视化的推理过程
- [ ] 适合短视频平台（30-90秒）

### 阶段 2：生成视频生产资料（20 分钟）

#### 步骤 2.1：填充 NotebookLM Prompt 模板
1. 打开 `templates/notebooklm_prompt_template.md`
2. 复制整个模板到新文件（或文本编辑器）
3. 将 `[题目]` 等占位符替换为实际内容：

**填充字段清单**：
- `[Topic]` → 题目中文 + 英文
- `[Core Concept]` → 核心概念（例如：Gambler's Fallacy）
- `[Platform]` → 目标平台（例如：TikTok, YouTube Shorts）
- `[Target Audience]` → 受众（例如：海外学生和家长）
- `[Video Duration]` → 时长（例如：45 seconds）
- `[Hook]` → 开头钩子（前 3 秒的问题）
- `[Problem Statement]` → 完整题面
- `[Correct Answer]` → 正确答案 + 简短解释
- `[Reasoning Process]` → 分步骤推理（3-5 步）
- `[Narration Script]` → 完整的旁白文案
- `[On-Screen Text]` → 屏幕字幕建议
- `[Storyboard]` → 画面分镜（见步骤 2.2）
- `[Visual Style]` → 视觉风格要求（白底线稿、简洁图示）
- `[Restrictions]` → 禁止事项（双人对话、黑色背景等）

#### 步骤 2.2：填充分镜模板
1. 打开 `templates/storyboard_template.md`
2. 根据题目设计 5-8 个镜头：

**分镜设计原则**：
- **镜头 1（0-3s）**：开头钩子 + 题目
- **镜头 2-3（3-15s）**：题面陈述 + 条件展示
- **镜头 4-6（15-35s）**：推理过程（逐步可视化）
- **镜头 7（35-40s）**：答案揭晓
- **镜头 8（40-45s）**：总结 + Call-to-Action

**示例（硬币题目）**：
```
Scene 1 (0-3s): 一枚硬币连续5次正面朝上 | "连续5次正面后,下一次呢?"
Scene 2 (3-8s): 白底上出现"第6次更可能是反面吗?" | 字幕："大多数人会说:是!"
Scene 3 (8-15s): 展示硬币的正反两面 | 字幕:"每次抛硬币都是独立事件"
Scene 4 (15-25s): 用树状图展示每次概率都是50% | 字幕:"正面50% 反面50%"
Scene 5 (25-35s): 标注"赌徒谬误" | 字幕:"过去的结果不影响未来"
Scene 6 (35-40s): 答案:"第6次仍然是50%正面 50%反面" | 大字幕:"答案:仍然50-50"
Scene 7 (40-45s): "关注我们学更多" | Think Academy logo
```

#### 步骤 2.3：生成旁白文案
根据分镜，写一段 **单人旁白** 文案：

**旁白文案要求**：
- 语气：轻松、好奇、教育性
- 节奏：每秒 2-3 个单词（英文）
- 结构：问题 → 常见误解 → 推理 → 答案 → 总结
- 时长：与目标视频时长一致（例如 45 秒约 90-135 个单词）

**示例**：
```
"If a coin lands heads 5 times in a row, is tails more likely next? Most people say yes. But here's the truth: each coin flip is independent. The coin has no memory. Every single flip is still 50-50. This mistake? It's called the Gambler's Fallacy. Past results don't change future odds. The answer: still 50% heads, 50% tails. Follow for more mind-bending facts!"
```

#### 步骤 2.4：设计屏幕字幕
从旁白中提取 **关键文字**，设计大字幕：

**字幕设计原则**：
- 大而清晰（占屏幕 1/4-1/3）
- 突出关键词（数字、答案、概念名称）
- 每个镜头 1-2 句字幕
- 与旁白同步

**示例**：
```
Scene 1: "连续5次正面?"
Scene 2: "下一次更可能反面吗?"
Scene 3: "每次都是独立事件"
Scene 4: "正面50% 反面50%"
Scene 5: "赌徒谬误"
Scene 6: "答案:仍然50-50"
```

### 阶段 3：质量检查（10 分钟）

#### 步骤 3.1：使用 QA Checklist
打开 `templates/qa_checklist_template.md`，逐项检查：

**必查项**：
- [ ] **答案正确性**：推理逻辑是否正确？答案是否准确？
- [ ] **单人旁白**：是否为 single narrator？没有双人对话/访谈/播客？
- [ ] **白底线稿**：视觉风格是否为白底、简洁线稿？
- [ ] **字幕清晰**：字幕是否大而清晰？是否突出关键信息？
- [ ] **图示一致**：核心图示（例如硬币）是否前后一致？
- [ ] **无禁止元素**：是否避免了黑色背景、恐怖风格、无关装饰？
- [ ] **画面与推理对应**：每个镜头的画面是否与推理步骤对应？
- [ ] **时长合理**：是否在 30-90 秒范围内？

**不合格处理**：
- 如果任何一项不通过，返回步骤 2 修改
- 特别注意答案正确性和单人旁白，这是硬性要求

#### 步骤 3.2：风格一致性检查
对照 `docs/style_guide.md`，确认：
- [ ] 符合 Think Academy AI 品牌风格
- [ ] 适合目标平台（TikTok / YouTube Shorts）
- [ ] 受众定位正确（海外学生和家长）

### 阶段 4：保存和输出（5 分钟）

#### 步骤 4.1：保存完整资料
在 `outputs/` 文件夹中创建新文件：

**文件命名规则**：
```
outputs/[id]_[title_en]_[date].md
```

**示例**：
```
outputs/001_The_Coin_Toss_Trap_2026-05-13.md
```

**文件内容结构**：
```markdown
# [Title EN] - Video Production Package

## 1. Topic Information
- **Chinese Title**: [题目中文]
- **English Title**: [题目英文]
- **Core Concept**: [核心概念]
- **Category**: [分类]
- **Duration**: [时长]

## 2. NotebookLM Prompt
[完整的 NotebookLM Prompt，可直接复制]

## 3. Storyboard
[完整分镜]

## 4. Narration Script
[旁白文案]

## 5. On-Screen Text
[字幕建议]

## 6. QA Checklist
[质量检查结果]

## 7. Production Notes
[制作备注]
```

#### 步骤 4.2：更新选题库状态
回到 `data/topic_library_sample.jsonl`，将该题目的 `status` 从 `pending` 改为 `in_production`。

**注意**：JSONL 文件每行是一个 JSON object，修改时需要保持 JSON 格式正确。

### 阶段 5：外部工具使用（人工完成）

#### 步骤 5.1：NotebookLM 生成视频
1. 打开 NotebookLM
2. 复制 `outputs/` 中的完整 Prompt
3. 粘贴到 NotebookLM，点击生成
4. 等待生成（通常 5-10 分钟）
5. 下载生成的视频

#### 步骤 5.2（可选）：增强视觉效果
如果 NotebookLM 生成的画面不够理想：
1. 在 Gamma 生成静态图（根据分镜描述）
2. 用即梦 AI 让图片动起来
3. 准备用于剪映合成

#### 步骤 5.3：剪映合成
1. 导入 NotebookLM 生成的视频（或 Gamma + 即梦 AI 的素材）
2. 导入旁白音频（可用 ChatGPT TTS 或人工录制）
3. 添加字幕（根据 On-Screen Text 建议）
4. 调整时长、过渡效果
5. 导出最终视频

#### 步骤 5.4：更新选题库状态
视频完成后，将 `status` 改为 `completed`。

## 三、批量生产流程

### 场景：一周内产出 20 条视频

#### 批量流程优化建议
1. **Day 1-2：批量选题**
   - 从选题库筛选 20 个题目
   - 按 `category` 分组（例如：5 个概率论、5 个视觉错觉、5 个逻辑推理、5 个数学悖论）

2. **Day 3-4：批量生成资料**
   - 使用模板批量填充
   - 每个题目 20-30 分钟
   - 总计约 7-10 小时

3. **Day 5：质量检查**
   - 逐个检查 QA Checklist
   - 修改不合格的资料

4. **Day 6-7：外部工具生成**
   - 批量复制到 NotebookLM
   - 在剪映中批量合成

## 四、常见问题与解决方案

### 问题 1：NotebookLM 生成的视频风格不对（例如：双人对话）
**原因**：Prompt 中的 Restrictions 不够明确  
**解决**：在 Prompt 中强调：
```
CRITICAL: This MUST be a single narrator monologue. 
DO NOT create a dialogue, interview, or podcast format.
```

### 问题 2：视频答案错误
**原因**：推理过程在 Prompt 中表述不清  
**解决**：在 Prompt 中详细列出推理步骤，逐步验证逻辑

### 问题 3：视觉风格不一致（有时白底，有时黑底）
**原因**：Visual Style 描述不够详细  
**解决**：在 Prompt 中明确：
```
Visual Style: White background, clean black line art, simple diagrams.
DO NOT use dark background, complex textures, or photorealistic images.
```

### 问题 4：字幕太小，看不清
**原因**：NotebookLM 自动生成的字幕较小  
**解决**：在剪映中手动添加大字幕，覆盖原字幕

### 问题 5：核心图示前后不一致（例如：硬币一会儿金色一会儿银色）
**原因**：NotebookLM 每次生成的图示略有差异  
**解决**：在 Prompt 中明确图示的外观特征，例如：
```
The coin should always be drawn as a simple circle with "H" on one side and "T" on the other, silver color, black outline.
```

## 五、效率提升建议

### 当前流程（MVP）：每条视频约 40 分钟
- 选题：5 分钟
- 生成资料：20 分钟
- 质量检查：10 分钟
- 保存输出：5 分钟

### V2 流程（自动化后）：每条视频约 5 分钟
- 输入题目：1 分钟
- ChatGPT API 自动生成：2 分钟
- 人工检查：2 分钟

### V3 流程（全流程集成后）：每条视频约 10 分钟（包含视频生成）
- 输入题目：1 分钟
- 自动生成资料 + 视频：8 分钟
- 人工检查和微调：1 分钟

## 六、模式 B：Direct Video Pipeline Mode（未来版本）

> **注意**：此模式为未来计划，当前版本（V0）不支持。预计在 V3 阶段实现。

### 工作流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                         输入层                                   │
│  从选题库选择题目 或 直接输入题目文本                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 1: 脚本生成                             │
│  调用 ChatGPT API 生成：                                         │
│  - 题目重写与英文标题                                             │
│  - 核心概念                                                      │
│  - 开头钩子                                                      │
│  - 完整题面                                                      │
│  - 正确答案                                                      │
│  - 详细推理过程（3-5 步）                                        │
│  - 单人旁白口播稿                                                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 2: 分镜生成                             │
│  调用 ChatGPT API 生成：                                         │
│  - 5-8 个镜头的画面描述                                          │
│  - 每个镜头的时间戳                                               │
│  - 每个镜头的字幕                                                 │
│  - 每个镜头的画面提示词（prompt for image/video generation）     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 3: 素材生成                             │
│  并行执行：                                                      │
│  1. TTS 生成旁白音频（ElevenLabs / Azure TTS）                  │
│  2. 图片生成（DALL-E / Stable Diffusion）                       │
│  3. 视频片段生成（Runway / Pika / Luma AI）                     │
│  4. 字幕文件生成（根据旁白生成 SRT）                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 4: 视频合成                             │
│  使用 ffmpeg：                                                   │
│  - 按时间轴排列画面素材                                           │
│  - 叠加旁白音频                                                   │
│  - 烧录字幕                                                       │
│  - 添加过渡效果                                                   │
│  - 输出 mp4 视频                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 5: 质量检查与优化                        │
│  - 自动质量评分（内容准确性、视觉风格、时长）                     │
│  - 如果不合格，返回 Phase 1 重新生成                             │
│  - 如果合格，保存到 outputs/ 文件夹                              │
└─────────────────────────────────────────────────────────────────┘
```

### 详细步骤说明

#### Phase 1: 脚本生成（2-3 分钟）
**输入**：题目文本（例如："连续5次正面后,下一次更可能反面吗"）

**处理**：
```python
python scripts/generate_script.py --topic "题目文本"
```

**输出**：
- `outputs/{id}_script.json` - 包含所有脚本字段的 JSON 文件

#### Phase 2: 分镜生成（1-2 分钟）
**输入**：Phase 1 的脚本

**处理**：
```python
python scripts/generate_storyboard.py --script outputs/{id}_script.json
```

**输出**：
- `outputs/{id}_storyboard.json` - 包含所有镜头描述的 JSON 文件
- 每个镜头包含画面提示词（prompt for image/video generation）

#### Phase 3: 素材生成（5-8 分钟，并行执行）
**输入**：Phase 2 的分镜

**处理**：
```python
# 并行执行以下命令
python scripts/generate_audio.py --script outputs/{id}_script.json
python scripts/generate_visuals.py --storyboard outputs/{id}_storyboard.json
python scripts/generate_subtitles.py --script outputs/{id}_script.json
```

**输出**：
- `outputs/{id}/audio.mp3` - 旁白音频
- `outputs/{id}/scene_01.mp4` - 镜头 1 的视频片段
- `outputs/{id}/scene_02.mp4` - 镜头 2 的视频片段
- ...
- `outputs/{id}/subtitles.srt` - 字幕文件

#### Phase 4: 视频合成（1-2 分钟）
**输入**：Phase 3 的所有素材

**处理**：
```python
python scripts/assemble_video.py --project outputs/{id}/
```

**输出**：
- `outputs/{id}/{id}_final.mp4` - 最终视频

#### Phase 5: 质量检查（自动）
**处理**：
```python
python scripts/quality_check.py --video outputs/{id}/{id}_final.mp4
```

**检查项**：
- 视频时长是否符合目标（30-90 秒）
- 音频和画面是否同步
- 字幕是否准确
- 视觉风格是否符合规范
- 旁白是否为单人

**输出**：
- `outputs/{id}/qa_report.json` - 质量检查报告

---

### 完整命令（一键执行）

**单个视频**：
```bash
python scripts/run_pipeline.py --topic "连续5次正面后,下一次更可能反面吗" --mode direct
```

**批量生产**：
```bash
python scripts/run_pipeline.py --batch --input data/topic_library_sample.jsonl --mode direct
```

---

### 模式 A vs 模式 B 对比

| 维度 | 模式 A (NotebookLM) | 模式 B (Direct Pipeline) |
|------|---------------------|--------------------------|
| **当前可用性** | ✅ V0 可用（人工填充） | ❌ V3+ 才可用 |
| **自动化程度** | 中（V1+ 自动生成 Prompt，但仍需人工复制） | 高（全自动） |
| **视频质量** | 高（NotebookLM 已优化） | 中（初期可能不如 NotebookLM） |
| **批量生产效率** | 低（需要人工复制粘贴） | 高（完全自动化） |
| **成本** | 低（NotebookLM 免费） | 高（需要多个 API） |
| **依赖外部工具** | 是（NotebookLM、剪映） | 否（完全自主） |
| **适用场景** | 重点视频、高质量要求 | 批量生产、快速迭代 |

---

## 七、附录：实际案例

### 案例 1：硬币题目（The Coin Toss Trap）
- **题目**：连续5次正面后,下一次更可能反面吗
- **核心概念**：Gambler's Fallacy
- **时长**：45 秒
- **亮点**：用树状图清晰展示每次概率都是 50%
- **教训**：第一版生成了双人对话，修改 Prompt 后成功

### 案例 2：人脸识别题目（Why Your Brain Sees Faces）
- **题目**：为什么大脑会在随机图案里看出人脸
- **核心概念**：Pareidolia（空想性错视）
- **时长**：60 秒
- **亮点**：用简单图形（三点两线）展示人脸识别机制
- **教训**：NotebookLM 生成的图示不够简洁，后续用 Gamma 重新生成

---

**文档版本**：v1.0  
**编写日期**：2026-05-13  
**适用于**：MVP 阶段（人工填充模板）  
**下次更新**：V2 阶段（自动化生成）
