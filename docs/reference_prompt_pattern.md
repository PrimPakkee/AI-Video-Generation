# Reference Prompt Pattern - NotebookLM Prompt 标准格式

## 文档说明

本文档总结了已成功用于 NotebookLM 生成视频的 Prompt 样例结构。这些 Prompt 经过实战验证，生成的视频风格稳定、单人旁白稳定、画面风格稳定、推理结构稳定。

**核心原则**：
- **成功样例比失败样例更重要**
- **结构稳定性胜过内容自由度**
- **明确约束胜过隐含期望**

**应用范围**：
- 本项目生成 NotebookLM Prompt 的核心参考
- `generate_video_package.py` 生成 `notebooklm_prompt.md` 时必须对齐此结构
- 未来 LLM Mode 也应基于此 pattern 生成，而非让模型自由发挥

---

## 标准结构（20 个一级字段）

### 1. Title
**说明**：英文标题，短、清楚、适合短视频传播

**要求**：
- 10-60 个字符
- 吸引人、反直觉、引发好奇
- 适合 TikTok / YouTube Shorts 标题

**示例**：
```
The Coin Toss Trap
The Birthday Paradox
Why Your Brain Sees Faces Everywhere
```

---

### 2. Topic
**说明**：题目所属知识点或核心概念

**要求**：
- 简洁标签式
- 便于分类和检索

**示例**：
```
Probability Puzzle
Independent Events
Gambler's Fallacy
Visual Perception
Cognitive Bias
```

---

### 3. Target platform
**说明**：目标短视频平台

**标准格式**：
```
TikTok, YouTube Shorts, Instagram Reels
```

**注意**：三个平台通常一起写，逗号分隔

---

### 4. Target audience
**说明**：目标受众

**标准格式**：
```
Students, parents, and viewers who enjoy short math puzzles, probability puzzles, brain tricks, visual reasoning, or everyday science.
```

**变体**：
- 可以根据题目类型微调，例如：
  - `math puzzles` → `logic puzzles`
  - `probability puzzles` → `visual illusions`
  - `brain tricks` → `counterintuitive facts`

**核心受众**：
- 12-18 岁学生
- 学生家长
- 喜欢教育短视频的观众

---

### 5. Video length
**说明**：视频目标时长

**标准格式**：
```
45 to 60 seconds
```
或
```
50 to 65 seconds
```

**建议范围**：
- 简单题目：30-45 秒
- 中等题目：45-60 秒
- 复杂题目：60-90 秒

---

### 6. Video format
**说明**：视频形式

**标准格式**：
```
Short-form educational video.
```

**不要写**：
- Documentary
- Long-form explanation
- Tutorial series

---

### 7. Core concept
**说明**：用一段话说明这个视频真正讲的核心概念，不只是重复标题

**要求**：
- 1-3 句话
- 说明为什么这个题目值得做成视频
- 说明观众会学到什么

**示例**：
```
This video explains the Gambler's Fallacy, which is the mistaken belief that past random events affect future random events. Many people believe that after seeing five heads in a row, tails is more likely on the next toss. This video shows why that is incorrect: each coin toss is independent, and a fair coin has no memory.
```

---

### 8. Narration style ⭐⭐⭐ 最重要
**说明**：旁白风格，必须明确强调单人旁白

**标准格式**（必须包含以下所有条款）：
```
- Use a single narrator only.
- The video must be a one-person explanatory monologue.
- The narrator should directly explain the puzzle to the viewer.
- Do not use dialogue.
- Do not use two hosts.
- Do not use multiple speakers.
- Do not use podcast style.
- Do not use interview style.
- Do not create a conversation between characters.
- Do not include back-and-forth discussion.
```

**为什么重要**：
- NotebookLM 默认倾向生成播客式双人对话
- 必须用明确的负面约束来避免
- 这是确保视频风格稳定的核心要素

---

### 9. Video hook
**说明**：3 秒内抓住注意力的开头

**要求**：
- 1-2 句话
- 反直觉、惊人、引发好奇
- 能在 3 秒内讲完

**示例**：
```
A coin lands heads five times in a row. Is tails more likely next?
```

**公式**：
- 陈述一个惊人事实 + 提出一个反直觉问题

---

### 10. Puzzle setup / Scene setup
**说明**：给出完整题面或场景

**要求**：
- 清晰陈述题目条件
- 不要留下模糊空间
- 适合视频脚本使用

**示例**：
```
A fair coin is tossed five times. The results are Heads, Heads, Heads, Heads, Heads. Now the coin will be tossed one more time.
```

---

### 11. Question
**说明**：明确提问，不能含糊

**要求**：
- 一句话
- 直接、清晰
- 适合屏幕字幕显示

**示例**：
```
Is tails more likely on the next toss?
```

---

### 12. Correct answer
**说明**：直接给正确答案

**要求**：
- 简短、明确
- 先给答案，再给解释
- 不要绕弯子

**示例**：
```
No. The next toss is still 50 percent heads and 50 percent tails.
```

---

### 13. Wrong intuition
**说明**：指出大多数人会怎么想，以及为什么这个直觉是错的

**要求**：
- 1-2 句话
- 先说错误直觉是什么
- 再说为什么错

**示例**：
```
After five heads in a row, many people feel tails is due. This is incorrect because each coin toss is independent, and the coin does not remember the previous results.
```

---

### 14. Key explanation
**说明**：清楚解释推理过程

**要求**：
- 分步骤，每步都清楚
- 适合短视频讲解
- 不能只给结论，要有推理路径
- 3-5 个推理步骤

**示例**：
```
Step 1: Five heads feels surprising
When you see five heads in a row, it feels unusual. This makes people think the pattern must change.

Step 2: The wrong intuition is that tails is due
Many people believe that after several heads, tails becomes more likely. This is called the Gambler's Fallacy.

Step 3: Each toss is independent
If the coin is fair, each toss is a separate event. The coin does not know what happened before.

Step 4: A fair coin has no memory
The coin does not try to balance itself. It has exactly two sides, and each side has a 50 percent chance every single time.

Step 5: The sixth toss is still 50/50
Before the sixth toss, there are still only two outcomes: heads or tails. Each has a 50 percent chance, no matter what happened in the previous five tosses.
```

---

### 15. Main lesson / Final lesson
**说明**：总结视频真正想教会观众的东西

**要求**：
- 1-2 句话
- 升华主题
- 不只是重复答案

**示例**：
```
Random events do not try to balance themselves immediately. A fair coin has no memory, and past results do not change future probabilities.
```

---

### 16. Narration draft
**说明**：完整英文单人旁白脚本

**要求**：
- **Single narrator monologue**（最重要）
- 不要双人对话
- 不要访谈
- 不要播客
- 语言简单清晰
- 适合 12-18 岁学生和家长理解
- 根据 video length 调整词数：
  - 45 秒 ≈ 90-135 词
  - 60 秒 ≈ 120-180 词

**结构**：
1. Hook（0-3s）
2. Problem setup（3-10s）
3. Question（10-15s）
4. Wrong intuition（15-20s）
5. Key explanation（20-40s）
6. Answer reveal（40-45s）
7. Main lesson（45-50s）
8. CTA（50-55s）

**示例**：
```
A coin lands heads five times in a row. Heads, heads, heads, heads, heads. Now it will be tossed one more time. Is tails more likely next? Most people feel like the answer is yes. After all, heads has happened too many times, so tails feels due. But that is the trap. If the coin is fair, the next toss is still fifty-fifty. Why? Because each coin toss is independent. The coin does not remember the last five results. It does not know that heads just happened five times. Before the next toss, there are still only two outcomes: heads or tails. Each has a 50 percent chance. So tails is not more likely. Heads is not less likely. The trick is simple: random events do not have memory. Follow for more probability traps and counterintuitive math puzzles.
```

---

### 17. On-screen text plan
**说明**：逐屏幕列出字幕或屏幕大字

**要求**：
- 每屏要短，适合短视频画面
- 突出关键词
- 与旁白同步
- 标注哪些词需要 yellow highlight boxes

**格式**：
```
Timestamp | Text | Highlight
```

**示例**：
```
00:00-00:03 | HEADS 5 times in a row... | "HEADS 5"
00:03-00:06 | Is TAILS more likely next? | "TAILS"
00:06-00:10 | Most people think tails is due. | "tails is due"
00:10-00:14 | But that is the trap. | "trap"
00:14-00:19 | Each toss is independent. | "independent"
00:19-00:24 | The coin has no memory. | "no memory"
00:24-00:31 | Next toss: Heads = 50%, Tails = 50% | "50%"
00:31-00:38 | Past results do not change the next toss. | "do not change"
00:38-00:45 | Answer: No. Tails is not more likely. | "No"
00:45-00:52 | Random events do not remember. | "do not remember"
```

---

### 18. Visual style ⭐⭐⭐ 最重要
**说明**：画面风格要求

**标准格式**（必须包含以下所有条款）：
```
✅ MUST HAVE:
- Minimal white background or white/light graph-paper background.
- Clean doodle / hand-drawn educational style.
- Modern educational style.
- Large readable English text.
- Clear on-screen captions.
- Yellow highlight boxes for key words when helpful.
- Simple motion only.
- Consistent core diagram throughout the video.

❌ DO NOT INCLUDE:
- No realistic humans.
- No dialogue bubbles.
- No podcast visuals (two people sitting, microphones, headphones).
- No interview visuals (interviewer and interviewee).
- No dark background.
- No decorative clutter.
- No random objects.
- No unrelated characters.
```

**为什么重要**：
- 确保视觉风格一致
- 避免 NotebookLM 生成双人播客画面
- 避免黑色背景
- 避免无关装饰

---

### 19. Important requirements ⭐⭐⭐ 最重要
**说明**：列出绝对不能错的地方

**标准格式**（必须包含以下核心条款）：
```
- The explanation must be logically correct.
- The answer must match the puzzle.
- The visuals must support the reasoning, not distract from it.
- The video must not become a dialogue, interview, podcast, or two-host conversation.
- The core diagram (e.g., the coin) must remain consistent across all scenes.
- Do not change the puzzle setup or add extra conditions.
- Do not give the wrong answer.
- Do not present the wrong intuition as the correct answer.
- Do not create visuals that contradict the explanation.
```

**扩展条款**（根据具体题目添加）：
- 如果是硬币题目：不要画赌场、赌桌、钱堆
- 如果是生日题目：不要画蛋糕、派对、礼物
- 如果是人脸识别题目：不要画真实人脸照片

---

### 20. Call to action
**说明**：短视频结尾 CTA

**要求**：
- 简短、友好
- 引导关注、点赞、评论

**标准格式**：
```
Follow for more [主题] and [相关主题].
```

**示例**：
```
Follow for more probability traps and counterintuitive math puzzles.
Follow for more visual illusions and brain tricks.
Follow for more everyday science and surprising facts.
```

---

## 核心设计原则

### 1. 明确约束胜过隐含期望
**错误做法**：
```
The video should be educational and engaging.
```

**正确做法**：
```
- Use a single narrator only.
- Do not use dialogue.
- Do not use two hosts.
- Do not use podcast style.
```

### 2. 负面约束必不可少
NotebookLM 的默认行为是生成播客式双人对话，因此必须用大量负面约束来纠正。

**必须包含的负面约束**：
- No dialogue
- No two hosts
- No podcast style
- No interview style
- No conversation between characters

### 3. 视觉风格约束同样重要
**必须包含的视觉约束**：
- White background（避免黑色背景）
- No realistic humans（避免真人照片）
- No podcast visuals（避免播客画面：两人、麦克风、耳机）
- No dialogue bubbles（避免对话气泡）

### 4. 核心图示一致性
**必须明确描述**：
- 核心图示是什么（例如：硬币、树状图、人脸图标）
- 如何保持一致（例如：始终用同样的简笔画风格）
- 不要改变什么（例如：不要从线稿变成写实照片）

### 5. 结构化胜过自由发挥
**为什么需要 20 个一级字段**：
- 确保所有必要信息都被包含
- 确保生成的 Prompt 结构一致
- 便于后续批量生产和质量检查
- 便于 LLM Mode 按结构生成

---

## 成功样例的共同特征

### ✅ 成功样例通常具备：
1. **单人旁白**：全程只有一个声音在讲解
2. **白底简洁**：白色或浅色背景，简洁图示
3. **大字清晰**：字幕大而清晰，关键词高亮
4. **推理清楚**：逐步推理，画面与推理对应
5. **风格一致**：核心图示从头到尾保持一致
6. **无冗余元素**：没有无关装饰、人物、动物

### ❌ 失败样例通常出现：
1. **双人对话**：两个人在讨论题目（播客风格）
2. **黑色背景**：深色背景或复杂纹理
3. **字幕太小**：字幕难以阅读
4. **推理跳跃**：直接给答案，没有推理过程
5. **风格漂移**：前面是线稿，后面变成照片
6. **无关元素**：赌场、钱堆、派对等与题目无关的视觉元素

---

## 应用指南

### 对于 Template Mode
当前 `generate_video_package.py` 在 Template Mode 下：
- 优先从 `topic_library_sample.jsonl` 读取增强字段
- 如果字段存在，填充到 `notebooklm_prompt.md` 对应位置
- 如果字段缺失，保留 TODO 占位符
- 生成的结构必须对齐本 pattern

### 对于 LLM Mode（未来）
当实现 LLM Mode 时：
- 让 LLM 按照本 pattern 的 20 个一级字段生成内容
- 不要让 LLM 自由发挥结构
- 明确告诉 LLM 每个字段的要求和示例
- 重点强调 Narration style、Visual style、Important requirements 三个关键字段

### 对于人工填充
当人工填充 TODO 时：
- 参考本 pattern 的示例格式
- 确保 Narration style 包含所有负面约束
- 确保 Visual style 包含所有视觉约束
- 确保 Important requirements 覆盖所有硬性要求

---

## 版本历史

**v1.0**（2026-05-13）：
- 初始版本
- 总结已成功的 NotebookLM Prompt 结构
- 定义 20 个一级字段
- 明确核心设计原则

**下次更新计划**：
- 增加更多成功样例分析
- 补充不同题目类型的变体
- 增加失败样例对比

---

**文档版本**：v1.0  
**编写日期**：2026-05-13  
**适用范围**：所有 Think Academy AI 教育短视频 NotebookLM Prompt  
**强制执行**：Template Mode 和 LLM Mode 必须对齐此 pattern  
**参考来源**：已成功用于 NotebookLM 的 Prompt 样例
