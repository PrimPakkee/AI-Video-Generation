# NotebookLM Prompt - {title}

> **使用说明**：将 `{占位符}` 替换为实际内容，然后复制整个 Prompt 到 NotebookLM。
> **重要**：本模板严格对齐 `docs/reference_prompt_pattern.md` 定义的 20 个一级字段。

---

## Title

{english_title}

---

## Topic

{topic}

---

## Target platform

TikTok, YouTube Shorts, Instagram Reels

---

## Target audience

Students, parents, and viewers who enjoy short math puzzles, probability puzzles, brain tricks, visual reasoning, or everyday science.

---

## Video length

{target_duration} seconds

---

## Video format

Short-form educational video.

---

## Core concept

{core_concept_explanation}

---

## Narration style

⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

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

---

## Video hook

{hook}

---

## Puzzle setup

{problem_statement}

---

## Question

{question}

---

## Correct answer

{correct_answer}

---

## Wrong intuition

{wrong_intuition}

---

## Key explanation

{reasoning_steps}

---

## Main lesson

{takeaway}

---

## Narration draft

⭐ **CRITICAL**: This MUST be a **single narrator monologue**. Do NOT create dialogue, interview, or podcast format.

{narration_script}

**Narration requirements**:
- **Single narrator only** - one clear, friendly voice throughout
- **Tone**: Casual but authoritative, curious but confident, friendly but not overly cute
- **Pacing**: 2-3 words per second (English), slow down at key reveals
- **Word count**: Approximately {word_count} words for {target_duration} seconds

---

## On-screen text plan

⭐ **CRITICAL**: Text must be **large and clear** (at least 1/5 of screen height). Use **yellow highlight boxes** for key words.

{subtitle_segments}

**Format**:
```
Timestamp | Text | Highlight
00:00-00:03 | [Opening text] | [Key words to highlight in yellow]
00:03-00:08 | [Question text] | [Key words to highlight in yellow]
...
```

---

## Visual style

⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

### ✅ MUST HAVE:

**Background**:
- Minimal white background or white/light graph-paper background.
- Pure white (#FFFFFF) OR light gray graph paper (#F5F5F5 with subtle grid lines at 10-20% opacity).

**Illustration Style**:
- Clean doodle / hand-drawn educational style.
- Modern educational style.
- Hand-drawn lines (slightly irregular, not perfectly geometric).
- Simple but not childish, cute but not overly cute.
- Think of it as: sketches drawn on white paper with a black marker.

**Text & Captions**:
- Large readable English text (at least 1/4 to 1/3 of screen height).
- Clear on-screen captions.
- Yellow highlight boxes for key words when helpful.
- Bold Sans-serif font (Arial, Roboto, Montserrat).
- Black text (#000000) on white/light background.

**Animation**:
- Simple motion only.
- Fade in / fade out (0.3-0.5s).
- Zoom in / zoom out (0.5-1s).
- Pan left / pan right (1-2s).
- Hand-drawn animation (elements gradually "draw" themselves).

**Core Visual Consistency**:
- Consistent core diagram throughout the video.
- {core_visual_consistency}

### ❌ DO NOT INCLUDE:

- No realistic humans.
- No dialogue bubbles.
- No podcast visuals (two people sitting, microphones, headphones).
- No interview visuals (interviewer and interviewee).
- No dark background.
- No black background.
- No decorative clutter.
- No random objects.
- No unrelated characters.
- No photorealistic images or 3D renders.
- No perfect geometric shapes (use hand-drawn style instead).
- No horror elements or scary visuals.
- No complex 3D animations, spinning (unless relevant), explosions, flashing effects.

---

## Important requirements

⭐⭐⭐ **CRITICAL - MANDATORY REQUIREMENTS** ⭐⭐⭐

### Logical Correctness:
- The explanation must be logically correct.
- The answer must match the puzzle.
- Do not change the puzzle setup or add extra conditions.
- Do not give the wrong answer.
- Do not present the wrong intuition as the correct answer.

### Visual Requirements:
- The visuals must support the reasoning, not distract from it.
- The core diagram (e.g., the coin, the tree diagram, the face icon) must remain consistent across all scenes.
- Do not create visuals that contradict the explanation.

### Format Requirements:
- The video must not become a dialogue, interview, podcast, or two-host conversation.
- Use single narrator monologue only.
- Do not use multiple speakers or back-and-forth discussion.

### Topic-Specific Requirements:
{notebooklm_specific_instructions}

---

## Call to action

{cta}

**Standard format**:
```
Follow for more [topic area] and [related topic area].
```

Examples:
- Follow for more probability traps and counterintuitive math puzzles.
- Follow for more visual illusions and brain tricks.
- Follow for more everyday science and surprising facts.

---

## QUALITY CHECKLIST

Before finalizing, verify all items below:

### ⭐ Hard Requirements (Must ALL Pass):
- [ ] **Content Accuracy**: Is the answer logically correct? Is the reasoning complete and verifiable?
- [ ] **Single Narrator**: Is this a monologue, NOT a dialogue/interview/podcast?
- [ ] **White Background**: Are all scenes on a white or light graph-paper background (no dark backgrounds)?
- [ ] **Hand-Drawn Style**: Are all visuals clean doodle / hand-drawn educational style (no photorealistic images)?
- [ ] **Large Text**: Are on-screen captions large and clear (at least 1/5 screen height)?
- [ ] **Yellow Highlights**: Are key words highlighted with yellow boxes?
- [ ] **Visual Consistency**: Are core diagrams consistent throughout?
- [ ] **No Forbidden Elements**: No dialogue, no dark backgrounds, no podcast visuals, no realistic humans?
- [ ] **Logic Flow**: Does each visual correspond to the reasoning step?
- [ ] **Answer Correctness**: Does the final answer match the correct answer to the puzzle?

### Optional Improvements:
- [ ] **Hook Strength**: Does the hook grab attention in the first 3 seconds?
- [ ] **Pacing**: Is the narration paced well (2-3 words per second)?
- [ ] **Clarity**: Are all reasoning steps clear and easy to follow?
- [ ] **Engagement**: Does the video maintain viewer interest throughout?

---

## PRODUCTION NOTES

### Think Academy Brand Guidelines:
- This is an educational content brand for international audiences.
- Content must be scientifically accurate and pedagogically sound.
- Visual style must be clean, modern, and minimalist.
- Tone must be accessible but not dumbed down.

### Target Platform Best Practices:
- **TikTok/YouTube Shorts**: Hook in first 3 seconds, answer by 40 seconds.
- **Instagram Reels**: Strong visual identity, large text overlays.
- **All Platforms**: High retention requires clear structure and payoff.

---

**Template Version**: v2.0  
**Last Updated**: 2026-05-13  
**Aligned With**: docs/reference_prompt_pattern.md (20-field standard)  
**For**: Think Academy AI Educational Short Videos  
**Generation Mode**: Template Mode (Phase 1B)

---

## 填充完成后的使用步骤

1. ✅ 确认所有 `{占位符}` 都已替换为实际内容
2. ✅ 检查 Quality Checklist 中的所有 ⭐ 硬性要求
3. ✅ 复制整个 Prompt（从 "Title" 到 "Call to action"）
4. ✅ 粘贴到 NotebookLM 并生成视频
5. ✅ 下载生成的视频，检查是否符合风格要求
6. ✅ 如有需要，在剪映中进行后期调整
7. ✅ 更新选题库状态为 "completed"
