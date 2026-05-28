# Think Academy AI 教育短视频 - 视觉风格参考手册

## 文档说明

本文档详细描述 Think Academy AI 教育短视频的实际视觉风格规范。这些规范基于 NotebookLM 生成的视频风格，适用于所有视频生产流程（无论是 NotebookLM Mode 还是 Direct Video Pipeline Mode）。

---

## 一、核心视觉风格原则

### 1.1 背景风格

**✅ 必须使用：**
- **White or light graph-paper background（白色或浅色方格纸背景）**
  - 纯白色背景（#FFFFFF）
  - 或浅灰色方格纸背景（类似学校草稿纸）
  - 方格纸的格子要淡、不抢眼（透明度约 10-20%）

**❌ 禁止使用：**
- ❌ 黑色背景（Dark background）
- ❌ 深色背景（任何深色调）
- ❌ 复杂纹理背景（木纹、金属、布料等）
- ❌ 渐变背景（从一个颜色过渡到另一个颜色）
- ❌ 照片背景（真实场景）

**视觉参考**：
```
┌─────────────────────────────────┐
│ ┊   ┊   ┊   ┊   ┊   ┊   ┊   ┊  │ 
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈│
│ ┊   ┊   ┊   ┊   ┊   ┊   ┊   ┊  │ 
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈│
│ ┊   Content Here   ┊   ┊   ┊  │ 
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈│
│ ┊   ┊   ┊   ┊   ┊   ┊   ┊   ┊  │ 
└─────────────────────────────────┘
浅色方格纸背景，格子淡而均匀
```

---

### 1.2 插图风格

**✅ 必须使用：**
- **Clean doodle / hand-drawn educational style（简洁涂鸦/手绘教育风格）**
  - 手绘感线条（不是完全笔直的几何线条）
  - 简洁但不幼稚
  - 教育性强，一目了然
  - 像在白纸上用黑色马克笔画的草图

**❌ 禁止使用：**
- ❌ 纯几何线稿（过于冷漠、技术化）
- ❌ 写实照片（Photorealistic images）
- ❌ 3D 渲染（3D renders）
- ❌ 卡通人物（Cartoon characters，除非与题目直接相关）
- ❌ 复杂插画（Overly detailed illustrations）

**视觉参考**：
```
手绘硬币示例：
    .-'''-.
  .'       '.
 /     H     \    ← 手绘感曲线，不是完美圆形
|             |
 \           /
  '.       .'
    '-...-'

手绘箭头示例：
    ↗  ← 稍微不规则，有手绘感
   ↑
  ↖
```

---

### 1.3 配色方案

**主色调**：
- **背景**：白色（#FFFFFF）或浅灰色（#F5F5F5）
- **线条和文字**：黑色（#000000）或深灰色（#333333）
- **强调色**：黄色（#FFD700）用于高亮框
- **辅助色**：
  - 蓝色（#0066FF）用于关键数字
  - 红色（#FF0000）用于错误或警告
  - 绿色（#00CC00）用于正确答案

**配色示例**：
```
硬币题目：
- 硬币：黑色手绘线条
- "正面" 标记：蓝色
- "反面" 标记：灰色
- 关键数字"50%"：黄色高亮框
- 背景：白色或浅色方格纸

概率树状图：
- 树枝：黑色手绘线条
- 节点：蓝色圆圈
- 概率数字：黑色文字 + 黄色高亮框
- 背景：白色
```

---

### 1.4 图标风格

**✅ 必须使用：**
- **Cute but not childish icons（可爱但不幼稚的图标）**
  - 简洁、友好
  - 适合 12-18 岁学生
  - 不要过于卡通化（像给 5 岁小孩看的）
  - 不要过于严肃（像学术论文）

**示例**：
```
✅ 好的图标：
  .--.      简洁的灯泡（代表想法）
 ( o  )
  '--'

✅ 好的图标：
  ? !       简洁的问号和感叹号
  
❌ 不好的图标：
  😀🎉      过于幼稚的 emoji
  
❌ 不好的图标：
  [严肃的学术图表]  过于复杂
```

---

## 二、字幕设计规范

### 2.1 字幕大小和位置

**✅ 必须使用：**
- **Large centered English captions（大而居中的英文字幕）**
  - 字号：占屏幕高度的 **1/4 到 1/3**（非常大）
  - 位置：**屏幕正中央**或中下部
  - 对齐方式：居中对齐

**❌ 禁止使用：**
- ❌ 小字幕（占屏幕 < 1/5）
- ❌ 左对齐或右对齐（除非特殊设计需要）
- ❌ 屏幕顶部字幕（会被平台 UI 遮挡）

**字幕大小参考**：
```
┌───────────────────────────────┐
│                               │
│       [小画面元素]             │
│                               │
│     ═══════════════════       │
│     ║  50% HEADS   ║       │ ← 字幕占屏幕 1/4-1/3
│     ║  50% TAILS   ║       │
│     ═══════════════════       │
│                               │
│                               │
└───────────────────────────────┘
```

### 2.2 字幕样式

**基础样式**：
- **字体**：Sans-serif（例如：Arial、Helvetica、Roboto、Montserrat）
- **字重**：Bold（粗体）
- **颜色**：黑色（#000000）
- **背景**：无背景或白色半透明背景
- **描边**：无需描边（因为背景是白色）

**关键词高亮**：
- **Yellow highlight boxes for key words（关键词用黄色高亮框）**
  - 重要数字：例如 "50%"、"5 times"
  - 核心概念：例如 "Gambler's Fallacy"
  - 答案：例如 "Still 50-50"
  - 黄色背景框：#FFD700 或 #FFEB3B，透明度 70-80%

**字幕高亮示例**：
```
普通字幕：
  Each flip is independent

关键词高亮：
  Each flip is ▄▄▄▄▄▄▄▄▄▄▄
                independent
                ▀▀▀▀▀▀▀▀▀▀▀
                ↑ 黄色高亮框
```

### 2.3 字幕内容

**原则**：
- 每个镜头 1-2 句
- 突出关键词（数字、答案、概念名称）
- 与旁白同步
- 简洁有力

**示例**：
```
Scene 1: "5 heads in a row?"
Scene 2: "Is tails more likely?"
Scene 3: "Each flip is INDEPENDENT"     ← 关键词大写
Scene 4: "50% HEADS  50% TAILS"         ← 数字黄色高亮
Scene 5: "GAMBLER'S FALLACY"            ← 概念名称大写 + 黄色高亮
Scene 6: "Answer: STILL 50-50"          ← 答案黄色高亮
```

---

## 三、动画和运动规范

### 3.1 动画原则

**✅ 必须使用：**
- **Simple motion（简单动效）**
  - 淡入淡出（Fade in / Fade out）
  - 缩放（Zoom in / Zoom out）
  - 平移（Pan left / Pan right）
  - 手绘动画（元素逐渐"画"出来）

**❌ 禁止使用：**
- ❌ 复杂 3D 动画
- ❌ 旋转动画（除非与题目相关，例如旋转的舞者）
- ❌ 爆炸、闪光等过度效果
- ❌ 快速闪烁（可能引起不适）

### 3.2 动画速度

- **淡入淡出**：0.3-0.5 秒
- **缩放**：0.5-1 秒
- **平移**：1-2 秒
- **手绘动画**：根据元素复杂度，1-3 秒

### 3.3 过渡效果

- 镜头之间：淡入淡出（0.3 秒）
- 元素出现：从无到有，淡入（0.3 秒）
- 元素消失：从有到无，淡出（0.3 秒）

---

## 四、核心图示一致性

### 4.1 一致性原则

**✅ 必须做到：**
- **Consistent core diagrams（核心图示前后一致）**
  - 同一个物体（例如硬币）在所有镜头中必须保持一致的外观
  - 一致性包括：形状、大小、颜色、线条风格

**❌ 禁止做法：**
- ❌ 第 1 个镜头硬币是金色的，第 3 个镜头变成银色的
- ❌ 第 2 个镜头人脸是线稿，第 5 个镜头变成写实照片
- ❌ 第 3 个镜头树状图是垂直的，第 6 个镜头变成水平的

### 4.2 常见核心图示规范

#### 硬币（Coin）
```
   .-'''-.
 .'   H   '.     ← 简洁的圆形，手绘感
|           |
 '.       .'
   '-...-'

正面标记：H（Heads）
反面标记：T（Tails）
线条：黑色手绘
填充：白色或浅灰色
```

#### 人脸（Face，用于 Pareidolia 题目）
```
  .---.
 /  o o  \    ← 两个点代表眼睛
|    ^    |   ← 一个小点代表鼻子
 \  ___  /    ← 一条线代表嘴巴
  '-----'

不要画复杂的人脸
保持简洁、符号化
```

#### 概率树（Probability Tree）
```
       ○              ← 节点：蓝色圆圈
      / \
     /   \            ← 树枝：黑色手绘线条
    ○     ○
   / \   / \
  H   T H   T         ← 叶子：结果标记

所有树状图使用同样的结构
节点大小一致
线条风格一致
```

---

## 五、叙事形式规范

### 5.1 旁白形式

**✅ 必须使用：**
- **Single narrator monologue（单人旁白独白）**
  - 一个清晰、友好的声音从头到尾讲解
  - 语气：轻松但专业，好奇但权威

**❌ 绝对禁止：**
- ❌ **No dialogue（无双人对话）**
  - 不要 "Person A: ... Person B: ..."
- ❌ **No podcast（无播客）**
  - 不要 "Host: ... Guest: ..."
- ❌ **No interview（无访谈）**
  - 不要 "Interviewer: ... Interviewee: ..."
- ❌ **No realistic humans（无写实人物）**
  - 不要出现真人照片或视频
  - 不要 3D 人物模型
  - 如果需要人物，使用简笔画

### 5.2 旁白语气

**语气特点**：
- 轻松（Casual）但专业（Professional）
- 好奇（Curious）但权威（Authoritative）
- 友好（Friendly）但不卖萌（Not overly cute）
- 教育性（Educational）但不说教（Not preachy）

**节奏**：
- 正常语速：每秒 2-3 个单词（英文）
- 在关键信息处放慢
- 在答案揭晓前制造悬念

---

## 六、禁止元素清单

### 6.1 禁止的视觉元素

- ❌ **No dark background（无黑色背景）**
- ❌ **No unrelated decorations（无无关装饰）**
  - 不要随机的星星、爱心、花朵
  - 不要无关的边框、纹理
- ❌ **No realistic humans（无写实人物）**
  - 不要真人照片
  - 不要 3D 人物
- ❌ **No random animals（无随机动物）**
  - 除非与题目直接相关
- ❌ **No horror elements（无恐怖元素）**
  - 不要恐怖图片、阴森气氛
- ❌ **No complex textures（无复杂纹理）**
  - 不要金属质感、木纹、布料
- ❌ **No photorealistic images（无写实照片）**

### 6.2 禁止的叙事形式

- ❌ **No dialogue（无双人对话）**
- ❌ **No podcast（无播客）**
- ❌ **No interview（无访谈）**
- ❌ **No conversation（无多人讨论）**

---

## 七、实际案例参考

### 案例 1：硬币题目（The Coin Toss Trap）

**Scene 1（0-3s）**：
- **画面**：5 枚硬币依次出现，全部显示 "H"（正面）
- **背景**：白色或浅色方格纸
- **字幕**："5 heads in a row?"（居中，大字）
- **动画**：硬币逐个淡入，手绘动画

**Scene 2（3-8s）**：
- **画面**：第 6 枚硬币出现，上方有问号
- **背景**：同 Scene 1
- **字幕**："Is tails more likely?"（居中，大字）
- **动画**：问号闪烁

**Scene 3（8-15s）**：
- **画面**：一枚硬币 + "INDEPENDENT" 标签
- **背景**：同 Scene 1
- **字幕**："Each flip is INDEPENDENT"（关键词黄色高亮）
- **动画**："INDEPENDENT" 标签淡入

**Scene 4（15-25s）**：
- **画面**：概率树状图，每次分支都标注 50%-50%
- **背景**：同 Scene 1
- **字幕**："50% HEADS  50% TAILS"（数字黄色高亮）
- **动画**：树状图逐步"画"出来

**Scene 5（25-35s）**：
- **画面**："GAMBLER'S FALLACY" 大字
- **背景**：同 Scene 1
- **字幕**：（与画面相同）
- **动画**：文字逐字出现，黄色高亮框包围

**Scene 6（35-40s）**：
- **画面**：第 6 枚硬币 + "50%-50%" 标记
- **背景**：同 Scene 1
- **字幕**："Answer: STILL 50-50"（黄色高亮框）
- **动画**：答案放大强调

**Scene 7（40-45s）**：
- **画面**：Think Academy Logo + "Follow for more"
- **背景**：同 Scene 1
- **字幕**："Follow for more!"
- **动画**：Logo 淡入

---

### 案例 2：人脸识别题目（Why Your Brain Sees Faces）

**核心图示**：
```
  .---.
 /  o o  \     ← 简笔画人脸（Pareidolia）
|    ^    |
 \  ___  /
  '-----'
```

**风格要求**：
- 所有"人脸"都用同样的简笔画风格
- 不要出现写实人脸照片
- 背景：白色或浅色方格纸
- 字幕：大而居中，关键词（"Pareidolia"）黄色高亮

---

## 八、NotebookLM Prompt 风格要求模板

在每个 NotebookLM Prompt 中必须包含以下段落：

```markdown
## VISUAL STYLE REQUIREMENTS

### Background
- MUST USE: White or light graph-paper background ONLY
- DO NOT USE: Dark backgrounds, black backgrounds, complex textures, gradient backgrounds

### Illustration Style
- MUST USE: Clean doodle / hand-drawn educational style
- Think of it as: sketches drawn on white paper with a black marker
- Cute but not childish, simple but not boring
- DO NOT USE: Photorealistic images, 3D renders, overly detailed illustrations

### Color Palette
- Background: White (#FFFFFF) or light gray graph paper
- Lines and text: Black (#000000) or dark gray
- Highlight: Yellow (#FFD700) for key words and answers
- Accent colors: Blue (#0066FF) for numbers, Red (#FF0000) for errors, Green (#00CC00) for correct answers

### Icons and Symbols
- Cute but not childish icons
- Simple hand-drawn style
- Appropriate for 12-18 year old students

### Captions (On-Screen Text)
- MUST BE: Large and centered (占屏幕 1/4-1/3)
- Font: Bold Sans-serif (例如 Arial, Roboto)
- Color: Black text
- Highlight key words with yellow background box (#FFD700)

### Animation
- Simple motion ONLY: fade in/out, zoom, pan, hand-drawn animation
- DO NOT USE: Complex 3D animations, spinning, explosions, flashing effects

### Core Diagram Consistency
[描述核心图示的具体外观，例如：
"The coin should ALWAYS be drawn as a simple hand-drawn circle with 'H' on one side and 'T' on the other. 
Maintain the same size, line style, and appearance throughout all scenes."]

## FORBIDDEN ELEMENTS

### Visual
- ❌ Dark or black backgrounds
- ❌ Photorealistic images or 3D renders
- ❌ Realistic human faces or bodies
- ❌ Random decorations (stars, hearts, flowers)
- ❌ Horror elements
- ❌ Complex textures

### Narration
- ❌ Dialogue between two or more people
- ❌ Podcast-style discussion
- ❌ Interview format
- ❌ Conversation

### Critical
- MUST BE: Single narrator monologue with one voice throughout
```

---

**文档版本**：v1.0  
**编写日期**：2026-05-13  
**适用于**：所有 Think Academy AI 教育短视频  
**强制执行**：无论使用 NotebookLM Mode 还是 Direct Video Pipeline Mode  
**参考来源**：NotebookLM 实际生成的视频风格

---

## 附录：快速检查清单

在生成视频或 Prompt 前，快速检查以下项目：

- [ ] 背景是白色或浅色方格纸？
- [ ] 插图风格是手绘涂鸦感？
- [ ] 字幕够大（占屏幕 1/4-1/3）且居中？
- [ ] 关键词用黄色高亮框？
- [ ] 核心图示前后一致？
- [ ] 动画简单（淡入淡出、缩放、平移）？
- [ ] 旁白是单人独白？
- [ ] 无双人对话、播客、访谈？
- [ ] 无黑色背景、写实照片、复杂纹理？
- [ ] 无无关装饰、随机人物/动物？

**全部通过 → 符合 Think Academy AI 视频风格**
