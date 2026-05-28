# AI Video Generation - Prompt Schema 设计文档

## 一、Schema 概述

本文档定义了 AI 教育短视频生产资料的标准化输出结构。每条视频必须包含 **15 个核心字段**，确保信息完整、风格一致、质量可控。

### Schema 用途
1. **标准化输出**：确保每条视频资料包含所有必要信息
2. **质量控制**：通过结构化字段检查内容完整性
3. **流程对接**：方便后续工具（NotebookLM、剪映）读取和使用
4. **数据分析**：便于统计视频表现和优化策略

### Schema 应用场景
- 人工填充模板（MVP 阶段）
- ChatGPT API 自动生成（V2 阶段）
- 批量处理选题库（V2-V3 阶段）
- 质量检查和审核（所有阶段）

## 二、完整 Schema 定义

### 2.1 基础信息字段（5 个）

#### 字段 1: `topic_info`
**说明**：题目的基本信息  
**数据类型**：Object  
**子字段**：
```yaml
topic_info:
  id: string                    # 选题库中的唯一标识，例如："001"
  title_cn: string              # 中文标题
  title_en: string              # 英文标题（用于 NotebookLM）
  category: string              # 分类：概率论 / 视觉错觉 / 逻辑推理 / 数学悖论等
  core_concept: string          # 核心概念，例如："Gambler's Fallacy"
```

**示例**：
```yaml
topic_info:
  id: "001"
  title_cn: "连续5次正面后,下一次更可能反面吗"
  title_en: "The Coin Toss Trap"
  category: "概率论"
  core_concept: "Gambler's Fallacy"
```

#### 字段 2: `video_positioning`
**说明**：视频的平台、受众、时长定位  
**数据类型**：Object  
**子字段**：
```yaml
video_positioning:
  platform: list[string]        # 目标平台：["TikTok", "YouTube Shorts", "Instagram Reels", "小红书"]
  target_audience: string       # 目标受众："12-18岁海外学生" / "学生家长"
  language: string              # 语言："English" / "Chinese"
  duration: string              # 目标时长："45s" / "60s" / "90s"
  difficulty: string            # 难度："easy" / "medium" / "hard"
```

**示例**：
```yaml
video_positioning:
  platform: ["TikTok", "YouTube Shorts"]
  target_audience: "12-18岁海外学生和家长"
  language: "English"
  duration: "45s"
  difficulty: "medium"
```

#### 字段 3: `hook`
**说明**：视频开头的钩子（前 3 秒吸引注意力的问题）  
**数据类型**：String  
**字符限制**：10-30 个单词（英文）或 15-40 个字（中文）  
**设计原则**：反直觉、惊人、引发好奇

**示例**：
```
"If a coin lands heads 5 times in a row, is tails more likely next?"
```

#### 字段 4: `problem_statement`
**说明**：完整的题面陈述，清晰说明题目条件  
**数据类型**：String  
**字符限制**：30-100 个单词（英文）  
**设计原则**：简洁、清晰、无歧义

**示例**：
```
"You flip a fair coin 5 times, and it lands heads every single time. 
Now you're about to flip it a 6th time. Is tails more likely than heads?"
```

#### 字段 5: `correct_answer`
**说明**：正确答案 + 简短解释  
**数据类型**：Object  
**子字段**：
```yaml
correct_answer:
  answer: string                # 简短答案，例如："No, still 50-50"
  brief_explanation: string     # 一句话解释，例如："Each flip is independent"
```

**示例**：
```yaml
correct_answer:
  answer: "No, it's still 50% heads and 50% tails"
  brief_explanation: "Each coin flip is an independent event with no memory of past results"
```

### 2.2 内容生产字段（5 个）

#### 字段 6: `reasoning_process`
**说明**：详细的推理过程，分步骤讲解  
**数据类型**：List[Object]  
**步骤数量**：3-5 步  
**子字段**：
```yaml
reasoning_process:
  - step: int                   # 步骤编号：1, 2, 3...
    title: string               # 步骤标题，例如："Common Misconception"
    content: string             # 步骤内容
    visual_cue: string          # 对应的画面提示
```

**示例**：
```yaml
reasoning_process:
  - step: 1
    title: "Common Misconception"
    content: "Most people think tails is 'due' to happen after 5 heads"
    visual_cue: "Show question mark with '6th flip?'"
    
  - step: 2
    title: "The Truth About Probability"
    content: "Each coin flip is an independent event"
    visual_cue: "Show one coin with 'independent event' label"
    
  - step: 3
    title: "Why It's Always 50-50"
    content: "The coin has no memory. Past results don't affect future flips"
    visual_cue: "Show tree diagram with all branches at 50%-50%"
    
  - step: 4
    title: "The Gambler's Fallacy"
    content: "This mistake is called the Gambler's Fallacy"
    visual_cue: "Show 'Gambler's Fallacy' in large text"
```

#### 字段 7: `narration_script`
**说明**：完整的单人旁白口播稿  
**数据类型**：String  
**字符限制**：根据 `duration` 确定：
- 45 秒 ≈ 90-135 个单词（英文）
- 60 秒 ≈ 120-180 个单词（英文）
- 90 秒 ≈ 180-270 个单词（英文）

**设计原则**：
- 必须是 **single narrator（单人旁白）**
- 语气轻松、友好、教育性
- 节奏：每秒 2-3 个单词（英文）
- 与 `reasoning_process` 对应

**示例**：
```
"If a coin lands heads 5 times in a row, is tails more likely next? 
Most people say yes. But here's the truth: each coin flip is independent. 
The coin has no memory. Every single flip is still 50-50, no matter what 
happened before. This mistake? It's called the Gambler's Fallacy. 
Past results don't change future odds. The answer: still 50% heads, 
50% tails. Follow for more mind-bending facts!"
```

#### 字段 8: `on_screen_text`
**说明**：屏幕字幕建议（大而清晰的关键文字）  
**数据类型**：List[Object]  
**子字段**：
```yaml
on_screen_text:
  - timestamp: string           # 时间戳，例如："0-3s"
    text: string                # 字幕内容
    style: string               # 样式：normal / emphasized / answer
```

**示例**：
```yaml
on_screen_text:
  - timestamp: "0-3s"
    text: "连续5次正面?"
    style: "normal"
    
  - timestamp: "3-8s"
    text: "下一次更可能反面吗?"
    style: "emphasized"
    
  - timestamp: "25-30s"
    text: "赌徒谬误"
    style: "emphasized"
    
  - timestamp: "35-40s"
    text: "答案: 仍然50-50"
    style: "answer"
```

#### 字段 9: `storyboard`
**说明**：画面分镜 / 每个镜头的画面描述  
**数据类型**：List[Object]  
**镜头数量**：5-8 个  
**子字段**：
```yaml
storyboard:
  - scene: int                  # 镜头编号：1, 2, 3...
    timestamp: string           # 时间范围，例如："0-3s"
    visual_description: string  # 画面描述（英文，供 NotebookLM 使用）
    on_screen_text: string      # 该镜头的字幕
```

**示例**：
```yaml
storyboard:
  - scene: 1
    timestamp: "0-3s"
    visual_description: "A coin flipping in the air, landing heads 5 times in a row. White background, clean black line art."
    on_screen_text: "连续5次正面?"
    
  - scene: 2
    timestamp: "3-8s"
    visual_description: "A question mark appears next to a 6th coin. Text overlay: '6th flip?'"
    on_screen_text: "下一次更可能反面吗?"
    
  - scene: 3
    timestamp: "8-15s"
    visual_description: "One coin with 'independent event' label. Simple diagram showing the coin has two sides."
    on_screen_text: "每次都是独立事件"
    
  - scene: 4
    timestamp: "15-25s"
    visual_description: "Tree diagram showing each flip has 50% heads and 50% tails. Clean black lines, blue nodes."
    on_screen_text: "正面50% 反面50%"
    
  - scene: 5
    timestamp: "25-35s"
    visual_description: "Large text: 'Gambler's Fallacy'. White background."
    on_screen_text: "赌徒谬误"
    
  - scene: 6
    timestamp: "35-40s"
    visual_description: "The 6th coin with '50%-50%' label. Emphasized answer."
    on_screen_text: "答案: 仍然50-50"
    
  - scene: 7
    timestamp: "40-45s"
    visual_description: "Think Academy logo with 'Follow for more' text."
    on_screen_text: "关注我们学更多"
```

#### 字段 10: `notebooklm_prompt`
**说明**：可直接复制到 NotebookLM 的完整 Prompt  
**数据类型**：String（Markdown 格式）  
**内容结构**：整合以上所有字段，加上风格限制和禁止事项

**示例**：见 `templates/notebooklm_prompt_template.md`

### 2.3 风格控制字段（3 个）

#### 字段 11: `visual_style`
**说明**：视觉风格要求  
**数据类型**：Object  
**子字段**：
```yaml
visual_style:
  background: string            # 背景："White background ONLY"
  illustration_style: string    # 插图风格："Clean black line art, simple diagrams"
  color_palette: list[string]   # 配色方案：["White", "Black", "Blue (#0066FF)"]
  consistency_note: string      # 一致性要求：描述核心图示如何保持一致
```

**示例**：
```yaml
visual_style:
  background: "White background ONLY"
  illustration_style: "Clean black line art, educational-style diagrams"
  color_palette: ["White (#FFFFFF)", "Black (#000000)", "Blue (#0066FF)"]
  consistency_note: "The coin should always be drawn as a simple circle with 'H' on one side and 'T' on the other, silver outline, black line art"
```

#### 字段 12: `restrictions`
**说明**：禁止事项（明确告诉 NotebookLM 不要做什么）  
**数据类型**：Object  
**子字段**：
```yaml
restrictions:
  narration_format:
    - "DO NOT create a dialogue between two or more people"
    - "DO NOT create an interview format"
    - "DO NOT create a podcast-style discussion"
    - "MUST be a single narrator monologue"
    
  visual_format:
    - "DO NOT use dark or black backgrounds"
    - "DO NOT use complex textures or photorealistic images"
    - "DO NOT use horror elements"
    - "DO NOT use irrelevant decorations or random characters"
    
  content:
    - "DO NOT sacrifice accuracy for entertainment"
    - "DO NOT include culturally specific references that may not translate"
```

**示例**：
```yaml
restrictions:
  narration_format:
    - "This MUST be a single narrator monologue"
    - "DO NOT create a dialogue, interview, or podcast format"
    
  visual_format:
    - "White background ONLY. No dark backgrounds"
    - "Clean line art ONLY. No photorealistic images"
    - "Simple diagrams ONLY. No complex textures"
    
  content:
    - "Answer must be logically correct"
    - "Reasoning process must be complete and clear"
```

#### 字段 13: `qa_checklist`
**说明**：质量检查清单（上线前必查项）  
**数据类型**：List[Object]  
**子字段**：
```yaml
qa_checklist:
  - category: string            # 检查类别
    item: string                # 检查项
    status: boolean             # 是否通过：true / false
    note: string                # 备注
```

**示例**：
```yaml
qa_checklist:
  - category: "Content Accuracy"
    item: "答案逻辑正确"
    status: true
    note: "已验证答案为 50-50"
    
  - category: "Content Accuracy"
    item: "推理过程完整"
    status: true
    note: "4 个推理步骤，逻辑清晰"
    
  - category: "Narration Format"
    item: "单人旁白（非双人对话）"
    status: true
    note: "全程 single narrator"
    
  - category: "Visual Style"
    item: "白底线稿（非黑色背景）"
    status: true
    note: "所有镜头都是白色背景"
    
  - category: "Visual Style"
    item: "字幕大而清晰"
    status: true
    note: "字幕占屏幕 1/4"
    
  - category: "Visual Consistency"
    item: "核心图示前后一致"
    status: true
    note: "硬币始终为简单圆圈 + H/T"
    
  - category: "Forbidden Elements"
    item: "无双人对话/访谈/播客"
    status: true
    note: "确认"
    
  - category: "Forbidden Elements"
    item: "无黑色背景/恐怖元素"
    status: true
    note: "确认"
    
  - category: "Logic Flow"
    item: "画面与推理对应"
    status: true
    note: "每个推理步骤都有对应画面"
```

### 2.4 元数据字段（2 个）

#### 字段 14: `production_metadata`
**说明**：制作元数据  
**数据类型**：Object  
**子字段**：
```yaml
production_metadata:
  created_date: string          # 创建日期："2026-05-13"
  created_by: string            # 创建人："产品实习生"
  version: string               # 版本号："v1.0"
  status: string                # 状态："draft" / "reviewed" / "approved" / "in_production" / "completed"
  output_path: string           # 输出路径："outputs/001_The_Coin_Toss_Trap_2026-05-13.md"
```

**示例**：
```yaml
production_metadata:
  created_date: "2026-05-13"
  created_by: "Think Academy 产品实习生"
  version: "v1.0"
  status: "draft"
  output_path: "outputs/001_The_Coin_Toss_Trap_2026-05-13.md"
```

#### 字段 15: `performance_tracking`
**说明**：视频表现追踪（后续填充）  
**数据类型**：Object  
**子字段**：
```yaml
performance_tracking:
  platform_links:               # 各平台链接
    tiktok: string
    youtube: string
    instagram: string
  metrics:                      # 表现指标（后续填充）
    views: int
    completion_rate: float
    likes: int
    shares: int
    comments: int
  insights:                     # 数据洞察（后续总结）
    what_worked: string
    what_to_improve: string
```

**示例**（初始为空）：
```yaml
performance_tracking:
  platform_links:
    tiktok: ""
    youtube: ""
    instagram: ""
  metrics:
    views: 0
    completion_rate: 0.0
    likes: 0
    shares: 0
    comments: 0
  insights:
    what_worked: "TBD"
    what_to_improve: "TBD"
```

## 三、完整 Schema 示例（YAML 格式）

```yaml
# AI Video Generation - Video Production Package Schema

# 1. 基础信息
topic_info:
  id: "001"
  title_cn: "连续5次正面后,下一次更可能反面吗"
  title_en: "The Coin Toss Trap"
  category: "概率论"
  core_concept: "Gambler's Fallacy"

# 2. 视频定位
video_positioning:
  platform: ["TikTok", "YouTube Shorts"]
  target_audience: "12-18岁海外学生和家长"
  language: "English"
  duration: "45s"
  difficulty: "medium"

# 3. 开头钩子
hook: "If a coin lands heads 5 times in a row, is tails more likely next?"

# 4. 完整题面
problem_statement: |
  You flip a fair coin 5 times, and it lands heads every single time. 
  Now you're about to flip it a 6th time. Is tails more likely than heads?

# 5. 正确答案
correct_answer:
  answer: "No, it's still 50% heads and 50% tails"
  brief_explanation: "Each coin flip is an independent event with no memory of past results"

# 6. 推理过程
reasoning_process:
  - step: 1
    title: "Common Misconception"
    content: "Most people think tails is 'due' to happen after 5 heads"
    visual_cue: "Show question mark with '6th flip?'"
    
  - step: 2
    title: "The Truth About Probability"
    content: "Each coin flip is an independent event"
    visual_cue: "Show one coin with 'independent event' label"
    
  - step: 3
    title: "Why It's Always 50-50"
    content: "The coin has no memory. Past results don't affect future flips"
    visual_cue: "Show tree diagram with all branches at 50%-50%"
    
  - step: 4
    title: "The Gambler's Fallacy"
    content: "This mistake is called the Gambler's Fallacy"
    visual_cue: "Show 'Gambler's Fallacy' in large text"

# 7. 旁白文案
narration_script: |
  If a coin lands heads 5 times in a row, is tails more likely next? 
  Most people say yes. But here's the truth: each coin flip is independent. 
  The coin has no memory. Every single flip is still 50-50, no matter what 
  happened before. This mistake? It's called the Gambler's Fallacy. 
  Past results don't change future odds. The answer: still 50% heads, 
  50% tails. Follow for more mind-bending facts!

# 8. 屏幕字幕
on_screen_text:
  - timestamp: "0-3s"
    text: "5 heads in a row?"
    style: "normal"
  - timestamp: "3-8s"
    text: "Is tails more likely next?"
    style: "emphasized"
  - timestamp: "8-15s"
    text: "Each flip is independent"
    style: "normal"
  - timestamp: "15-25s"
    text: "Heads 50% Tails 50%"
    style: "normal"
  - timestamp: "25-35s"
    text: "Gambler's Fallacy"
    style: "emphasized"
  - timestamp: "35-40s"
    text: "Answer: Still 50-50"
    style: "answer"
  - timestamp: "40-45s"
    text: "Follow for more!"
    style: "normal"

# 9. 画面分镜
storyboard:
  - scene: 1
    timestamp: "0-3s"
    visual_description: "A coin flipping in the air, landing heads 5 times in a row. White background, clean black line art."
    on_screen_text: "5 heads in a row?"
    
  - scene: 2
    timestamp: "3-8s"
    visual_description: "A question mark appears next to a 6th coin. Text overlay: '6th flip?'"
    on_screen_text: "Is tails more likely next?"
    
  - scene: 3
    timestamp: "8-15s"
    visual_description: "One coin with 'independent event' label. Simple diagram showing the coin has two sides."
    on_screen_text: "Each flip is independent"
    
  - scene: 4
    timestamp: "15-25s"
    visual_description: "Tree diagram showing each flip has 50% heads and 50% tails. Clean black lines, blue nodes."
    on_screen_text: "Heads 50% Tails 50%"
    
  - scene: 5
    timestamp: "25-35s"
    visual_description: "Large text: 'Gambler's Fallacy'. White background."
    on_screen_text: "Gambler's Fallacy"
    
  - scene: 6
    timestamp: "35-40s"
    visual_description: "The 6th coin with '50%-50%' label. Emphasized answer."
    on_screen_text: "Answer: Still 50-50"
    
  - scene: 7
    timestamp: "40-45s"
    visual_description: "Think Academy logo with 'Follow for more' text."
    on_screen_text: "Follow for more!"

# 10. NotebookLM Prompt（见 templates/notebooklm_prompt_template.md）
notebooklm_prompt: "[完整 Prompt，见模板文件]"

# 11. 视觉风格
visual_style:
  background: "White background ONLY"
  illustration_style: "Clean black line art, educational-style diagrams"
  color_palette: ["White (#FFFFFF)", "Black (#000000)", "Blue (#0066FF)"]
  consistency_note: "The coin should always be drawn as a simple circle with 'H' on one side and 'T' on the other, silver outline, black line art"

# 12. 禁止事项
restrictions:
  narration_format:
    - "This MUST be a single narrator monologue"
    - "DO NOT create a dialogue, interview, or podcast format"
  visual_format:
    - "White background ONLY. No dark backgrounds"
    - "Clean line art ONLY. No photorealistic images"
  content:
    - "Answer must be logically correct"
    - "Reasoning process must be complete"

# 13. 质量检查
qa_checklist:
  - category: "Content Accuracy"
    item: "答案逻辑正确"
    status: true
  - category: "Narration Format"
    item: "单人旁白"
    status: true
  - category: "Visual Style"
    item: "白底线稿"
    status: true
  - category: "Visual Style"
    item: "字幕大而清晰"
    status: true
  - category: "Visual Consistency"
    item: "核心图示一致"
    status: true

# 14. 制作元数据
production_metadata:
  created_date: "2026-05-13"
  created_by: "Think Academy 产品实习生"
  version: "v1.0"
  status: "draft"
  output_path: "outputs/001_The_Coin_Toss_Trap_2026-05-13.md"

# 15. 表现追踪（后续填充）
performance_tracking:
  platform_links:
    tiktok: ""
    youtube: ""
  metrics:
    views: 0
    completion_rate: 0.0
  insights:
    what_worked: "TBD"
```

## 四、Schema 使用指南

### 4.1 MVP 阶段（人工填充）
1. 打开 `templates/notebooklm_prompt_template.md`
2. 按照 Schema 定义，逐个字段填充内容
3. 保存到 `outputs/` 文件夹

### 4.2 V2 阶段（API 自动生成）
1. 调用 ChatGPT API，传入选题信息
2. API 返回符合 Schema 的 JSON/YAML 数据
3. 自动保存到 `outputs/` 文件夹

### 4.3 质量检查
1. 检查所有必填字段是否完整
2. 检查 `qa_checklist` 是否全部通过
3. 检查 `restrictions` 是否遵守

---

**文档版本**：v1.0  
**编写日期**：2026-05-13  
**适用范围**：所有 Think Academy AI 教育短视频生产资料  
**下次审阅**：V2 阶段开发前
