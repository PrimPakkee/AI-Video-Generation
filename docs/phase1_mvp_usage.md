# Phase 1B MVP Usage Guide - 使用说明文档

## 文档说明

本文档说明如何运行 Phase 1B 增强版 MVP 脚本：`scripts/generate_video_package.py`

**当前模式**：Template Mode (Phase 1B - Enhanced Fields Support)
- 不调用任何外部 API
- 支持从增强字段生成可用内容
- 如果题目未包含增强字段，仍然生成 TODO 占位符

---

## 一、准备工作

### 1.1 确认环境

确保你的电脑已安装 Python 3.10+：

```bash
python --version
# 或者
python3 --version
```

如果显示 `Python 3.10.x` 或更高版本，说明环境正常。

### 1.2 打开项目文件夹

在 VS Code 中打开项目文件夹：
1. 打开 VS Code
2. 点击 `File` → `Open Folder...`
3. 选择 `AI Video Generation` 文件夹
4. 点击 `Open`

### 1.3 打开终端

在 VS Code 中打开终端：
- **方法 1**：按快捷键 `` Ctrl + ` ``（Windows/Linux）或 `` Cmd + ` ``（Mac）
- **方法 2**：点击菜单 `Terminal` → `New Terminal`

### 1.4 确认当前目录

在终端中输入以下命令确认当前目录是 `AI Video Generation`：

```bash
pwd
```

应该显示类似：
```
/Users/tal/Desktop/Claude Code/AI Video Generation
```

如果不是，使用 `cd` 命令切换到正确的目录：
```bash
cd "/Users/tal/Desktop/Claude Code/AI Video Generation"
```

---

## 二、运行脚本

### 2.1 查看所有可用选题

在生成 video package 之前，建议先查看所有可用的选题：

```bash
python scripts/generate_video_package.py --list-topics
```

输出示例：
```
🚀 AI Video Generation - Topic Library
============================================================

📂 正在加载选题库...
✓ 成功加载 20 个选题

ID     | 中文标题                                     | 英文标题                                     | 分类           | 时长     | 状态
------+--------------------------------------------+--------------------------------------------+--------------+--------+------------
✨001  | 连续5次正面后,下一次更可能反面吗                   | The Coin Toss Trap                         | 概率论        | 45s    | pending
  002  | 为什么大脑会在随机图案里看出人脸                    | Why Your Brain Sees Faces in Random Things | 视觉错觉      | 60s    | pending
  003  | 99%的人都会选错的三扇门问题                       | The 3 Doors Problem Everyone Gets Wrong    | 逻辑推理      | 90s    | pending
...

✨ = 已包含增强字段（可直接生成）

💡 使用方法：
   python scripts/generate_video_package.py --topic-id <ID>
   例如：python scripts/generate_video_package.py --topic-id 001
```

**说明**：
- ✨ 标记的选题已包含增强字段，生成的内容可直接使用（无 TODO 占位符）
- 未标记的选题会生成 TODO 占位符，需要人工填充

### 2.2 基本用法

运行以下命令生成 topic ID 为 `001` 的 video package：

```bash
python scripts/generate_video_package.py --topic-id 001
```

或者（如果 `python` 命令不可用）：
```bash
python3 scripts/generate_video_package.py --topic-id 001
```

### 2.3 覆盖已存在的文件夹

默认情况下，如果输出文件夹已存在，脚本会创建带时间戳的新文件夹（例如 `001_the_coin_toss_trap_20260513_165923`）。

如果你想直接覆盖已存在的文件夹，使用 `--overwrite` 参数：

```bash
python scripts/generate_video_package.py --topic-id 001 --overwrite
```

### 2.4 其他选题

你可以生成任何选题库中存在的题目：

```bash
# 生成 topic ID 002
python scripts/generate_video_package.py --topic-id 002

# 生成 topic ID 003
python scripts/generate_video_package.py --topic-id 003

# 生成 topic ID 020
python scripts/generate_video_package.py --topic-id 020
```

---

## 三、运行成功的标志

### 3.1 终端输出

#### 情况 A：选题已包含增强字段（例如 topic 001）

运行成功后，你应该看到类似以下输出：

```
🚀 AI Video Generation - Video Package Generator
模式：Template Mode（Phase 1B - Enhanced Fields Support）
============================================================

📂 正在加载选题库...
✓ 成功加载 20 个选题

🔍 正在查找选题 ID: 001...
✨ 找到选题：连续5次正面后,下一次更可能反面吗
   已包含增强字段，将生成可用内容

📁 正在创建输出文件夹...
✓ 输出文件夹：outputs/001_the_coin_toss_trap

📝 正在生成 video package 文件...
✓ 已生成：topic.json
✓ 已生成：video_package.md
✓ 已生成：notebooklm_prompt.md
✓ 已生成：narration_script.md
✓ 已生成：storyboard.md
✓ 已生成：subtitles.md
✓ 已生成：qa_checklist.md

============================================================
✅ Video Package 生成完成！

📦 输出文件夹：outputs/001_the_coin_toss_trap

📄 生成的文件：
  - topic.json
  - video_package.md
  - notebooklm_prompt.md
  - narration_script.md
  - storyboard.md
  - subtitles.md
  - qa_checklist.md

🎯 下一步操作：
  1. 打开 001_the_coin_toss_trap/notebooklm_prompt.md 查看生成的内容
  2. 检查内容是否需要微调
  3. 使用 qa_checklist.md 检查质量
  4. 复制完整 Prompt 到 NotebookLM 生成视频

💡 提示：此选题已包含增强字段，生成的内容可直接使用，无需填充 TODO。
```

#### 情况 B：选题未包含增强字段（例如 topic 002-020）

运行成功后，你应该看到类似以下输出：

```
🚀 AI Video Generation - Video Package Generator
模式：Template Mode（Phase 1B - Enhanced Fields Support）
============================================================

📂 正在加载选题库...
✓ 成功加载 20 个选题

🔍 正在查找选题 ID: 002...
⚠️  找到选题：为什么大脑会在随机图案里看出人脸
   未包含增强字段，将生成 TODO 占位符

📁 正在创建输出文件夹...
✓ 输出文件夹：outputs/002_why_your_brain_sees_faces_in_random_things

📝 正在生成 video package 文件...
✓ 已生成：topic.json
✓ 已生成：video_package.md
✓ 已生成：notebooklm_prompt.md
✓ 已生成：narration_script.md
✓ 已生成：storyboard.md
✓ 已生成：subtitles.md
✓ 已生成：qa_checklist.md

============================================================
✅ Video Package 生成完成！

📦 输出文件夹：outputs/002_why_your_brain_sees_faces_in_random_things

📄 生成的文件：
  - topic.json
  - video_package.md
  - notebooklm_prompt.md
  - narration_script.md
  - storyboard.md
  - subtitles.md
  - qa_checklist.md

🎯 下一步操作：
  1. 打开 002_why_your_brain_sees_faces_in_random_things/video_package.md 查看汇总信息
  2. 打开 002_why_your_brain_sees_faces_in_random_things/notebooklm_prompt.md 填充 TODO 部分
  3. 打开其他文件完善脚本、分镜、字幕
  4. 使用 qa_checklist.md 检查质量
  5. 复制完整 Prompt 到 NotebookLM 生成视频

💡 提示：当前为 Template Mode，生成的文件包含 TODO 占位符，需要人工填充。
   未来可以使用 LLM Mode 自动生成完整内容，或手动添加增强字段到 JSONL。
```

### 3.2 文件夹结构

在 VS Code 左边的 Explorer 中，你应该看到新的文件夹出现在 `outputs/` 下：

```
outputs/
└── 001_the_coin_toss_trap/
    ├── topic.json
    ├── video_package.md
    ├── notebooklm_prompt.md
    ├── narration_script.md
    ├── storyboard.md
    ├── subtitles.md
    └── qa_checklist.md
```

**如果没有看到新文件夹**：
- 右键点击 `outputs` 文件夹
- 选择 `Refresh` 或 `Reveal in File Explorer`

---

## 四、查看生成的文件

### 4.1 首先打开：video_package.md

在 VS Code 中双击打开 `outputs/001_the_coin_toss_trap/video_package.md`

这个文件是汇总信息，包括：
- 题目信息
- 推荐工作流模式
- 当前生成模式（Template Mode）
- 下一步生产步骤
- 文件清单

### 4.2 核心文件：notebooklm_prompt.md

打开 `outputs/001_the_coin_toss_trap/notebooklm_prompt.md`

这是最重要的文件，包含 **20 个标准字段**（对齐 `docs/reference_prompt_pattern.md`）：
1. **Title** - 英文标题
2. **Topic** - 题目分类
3. **Target platform** - 目标平台
4. **Target audience** - 目标受众
5. **Video length** - 视频时长
6. **Video format** - 视频形式
7. **Core concept** - 核心概念
8. **Narration style** ⭐⭐⭐ - 叙事风格（单人旁白要求）
9. **Video hook** - 视频钩子
10. **Puzzle setup** - 题目设置
11. **Question** - 问题
12. **Correct answer** - 正确答案
13. **Wrong intuition** - 错误直觉
14. **Key explanation** - 关键解释
15. **Main lesson** - 主要总结
16. **Narration draft** - 旁白草稿
17. **On-screen text plan** - 屏幕文字计划
18. **Visual style** ⭐⭐⭐ - 视觉风格要求
19. **Important requirements** ⭐⭐⭐ - 重要要求
20. **Call to action** - 行动号召

**当前状态（topic 001）**：
- ✅ 已包含增强字段，所有内容已填充
- ✅ 可以直接复制到 NotebookLM 使用
- ✅ 建议先检查内容是否需要微调

**当前状态（topic 002-020）**：
- ⚠️ 未包含增强字段，所有具体内容都标注了 `[TODO: ...]`
- ⚠️ 你需要手动填充这些 TODO 部分
- ⚠️ 填充完成后，复制整个文件内容到 NotebookLM

### 4.3 其他文件

- **narration_script.md**：旁白脚本草稿，按 7 个标准结构填充
- **storyboard.md**：6 个镜头的分镜草稿
- **subtitles.md**：字幕草稿，按时间段分段
- **qa_checklist.md**：质量检查清单，逐项检查

---

## 五、填充 TODO 并生成视频

### 5.1 填充步骤

1. **打开 notebooklm_prompt.md**
2. **逐个填充 TODO 部分**：
   - Hook：前 3 秒的吸引人问题
   - Problem Statement：完整题面
   - Correct Answer：正确答案 + 解释
   - Reasoning Process：3-5 步推理过程
   - Narration Script：完整旁白
   - Storyboard：6 个镜头的画面描述
   - Core Visual Consistency：描述核心图示如何保持一致

3. **检查风格要求**：
   - 确认是 single narrator monologue
   - 确认 visual style 描述包含 white/light graph-paper background
   - 确认 captions 要求 yellow highlight boxes
   - 确认 restrictions 部分明确禁止 dialogue/interview/podcast

4. **使用 qa_checklist.md 检查质量**：
   - 逐项检查，确保所有硬性要求（⭐）通过

### 5.2 复制到 NotebookLM

1. 打开 NotebookLM（https://notebooklm.google.com/）
2. 创建新项目或笔记
3. 将 `notebooklm_prompt.md` 的完整内容复制粘贴到 NotebookLM
4. 点击生成视频
5. 等待 NotebookLM 生成（通常 5-10 分钟）
6. 下载生成的视频

### 5.3 后期调整

如果 NotebookLM 生成的视频不理想：
1. 检查 Prompt 中的 CRITICAL RESTRICTIONS 是否足够明确
2. 修改 VISUAL STYLE REQUIREMENTS 中的描述
3. 重新生成

如果字幕太小或样式不对：
1. 在剪映中手动添加大字幕
2. 根据 `subtitles.md` 添加黄色高亮框

---

## 六、常见错误与解决方法

### 错误 1：找不到 JSONL 文件

**错误信息**：
```
❌ 错误：找不到选题库文件：/path/to/data/topic_library_sample.jsonl
请确保 data/topic_library_sample.jsonl 存在。
```

**原因**：选题库文件不存在或路径错误

**解决方法**：
1. 确认你在正确的目录：
   ```bash
   pwd
   ```
   应该显示 `AI Video Generation` 文件夹路径

2. 检查 `data/topic_library_sample.jsonl` 文件是否存在：
   ```bash
   ls data/topic_library_sample.jsonl
   ```

3. 如果文件不存在，说明项目文件不完整，请重新检查项目结构

---

### 错误 2：Topic ID 不存在

**错误信息**：
```
❌ 错误：找不到 ID 为 '999' 的选题

可用的选题 ID：
  - 001: 连续5次正面后,下一次更可能反面吗
  - 002: 为什么大脑会在随机图案里看出人脸
  ...
```

**原因**：输入的 topic ID 不存在于选题库中

**解决方法**：
1. 查看终端输出的可用 ID 列表
2. 选择一个存在的 ID 重新运行：
   ```bash
   python scripts/generate_video_package.py --topic-id 001
   ```

---

### 错误 3：Python 命令不可用

**错误信息**：
```
command not found: python
```

**原因**：系统中 Python 命令名称可能是 `python3` 而非 `python`

**解决方法**：
使用 `python3` 命令：
```bash
python3 scripts/generate_video_package.py --topic-id 001
```

---

### 错误 4：JSONL 某行解析失败

**错误信息**：
```
警告：第 5 行 JSON 解析失败：Expecting property name enclosed in double quotes
```

**原因**：JSONL 文件中某一行的 JSON 格式错误

**解决方法**：
1. 打开 `data/topic_library_sample.jsonl`
2. 检查第 5 行（或错误提示的行号）
3. 确保该行是合法的 JSON 格式（可以用在线 JSON 验证工具检查）
4. 修复后重新运行脚本

---

### 错误 5：Outputs 没有刷新

**现象**：脚本运行成功，但 VS Code Explorer 中看不到新文件夹

**原因**：VS Code 文件树没有自动刷新

**解决方法**：
- **方法 1**：右键点击 `outputs` 文件夹，选择 `Refresh`
- **方法 2**：按快捷键 `Ctrl+R`（Windows/Linux）或 `Cmd+R`（Mac）刷新 Explorer
- **方法 3**：关闭并重新打开 VS Code

---

### 错误 6：生成文件夹已存在

**现象**：脚本运行后，输出文件夹名称带时间戳，例如 `001_the_coin_toss_trap_20260513_143520`

**原因**：之前已经生成过同名文件夹，脚本自动添加时间戳避免覆盖

**解决方法**：
- **方法 1**：使用新生成的带时间戳的文件夹（最新的）
- **方法 2**：删除旧文件夹后重新运行：
  ```bash
  rm -rf outputs/001_the_coin_toss_trap
  python scripts/generate_video_package.py --topic-id 001
  ```

---

## 七、下一步计划

### 当前阶段（Phase 1B - Enhanced Fields Support）
- ✅ 已完成：本地文件生成，验证流程
- ✅ 已完成：支持从增强字段生成可用内容
- ✅ 已完成：--list-topics 和 --overwrite 参数
- ✅ 已完成：20-field NotebookLM Prompt 标准结构
- ✅ 不调用任何外部 API
- ✅ Topic 001 已包含增强字段，可直接使用

### 下一阶段（Phase 1C - 批量增强字段）
- ⏳ 待开发：为更多选题添加增强字段
- ⏳ 可选方案 1：人工填充（高质量，但耗时）
- ⏳ 可选方案 2：使用 LLM 辅助生成（需要接入 API）

### 未来阶段（Phase 2 - LLM Mode）
- ⏳ 待开发：接入 ChatGPT / Claude API
- ⏳ 自动填充 TODO 部分
- ⏳ 生成完整的 video package（无需人工填充）

### 使用 LLM Mode 的命令（未来）
```bash
# 未来的命令示例（当前不可用）
python scripts/generate_video_package.py --topic-id 002 --mode llm
```

---

## 八、附录：文件说明

### topic.json
- 选题的原始 JSON 信息
- 格式化输出，方便查看
- 包含所有选题库字段

### video_package.md
- 汇总信息文件
- 包括题目信息、推荐模式、下一步操作
- 适合快速了解整个 package

### notebooklm_prompt.md
- **最重要的文件**
- 可以直接复制到 NotebookLM 生成视频
- 包含所有必要的 Prompt 结构和风格要求
- 当前带 TODO 占位符，需要人工填充

### narration_script.md
- 旁白脚本草稿
- 按 7 个标准结构（Hook、Problem Setup、Wrong Intuition、Key Reasoning、Concept Name、Answer Reveal、Takeaway & CTA）
- 包含旁白风格指南

### storyboard.md
- 分镜草稿
- 标准 6 个镜头结构
- 每个镜头包含时间戳、旁白、字幕、画面描述、风格限制

### subtitles.md
- 字幕草稿
- 按时间段分段（例如：00:00-00:03, 00:03-00:07）
- 标注哪些关键词需要黄色高亮框

### qa_checklist.md
- 质量检查清单
- 7 大部分、50+ 检查项
- 硬性要求（⭐）必须全部通过
- 适合上线前逐项检查

---

**文档版本**：v2.0  
**编写日期**：2026-05-13  
**适用阶段**：Phase 1B - Enhanced Fields Support  
**更新日志**：
- v2.0 (2026-05-13): Phase 1B 完成，支持增强字段，添加 --list-topics 和 --overwrite 参数
- v1.0 (2026-05-13): Phase 1A 初始版本，Template Mode 基础功能

**下次更新**：Phase 1C 或 Phase 2 开发完成后
