#!/usr/bin/env python3
"""
LLM Topic Enhancer - Phase 2A

将用户输入的题目转换为 enhanced topic JSON。

功能：
- 接收题目（中文/英文）
- 构造严格的 LLM prompt
- 调用 OpenAI-compatible API
- 解析和验证返回的 JSON
- 支持 dry-run（不调用 API）

Usage:
    from llm_topic_enhancer import LLMTopicEnhancer

    enhancer = LLMTopicEnhancer()
    topic_json = enhancer.enhance_topic("为什么数字9总感觉最特别", dry_run=False)
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

# Auto-load .env file if it exists (must be before accessing os.getenv)
try:
    from dotenv import load_dotenv
    # Load .env from project root
    project_root = Path(__file__).parent.parent
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, continue with system environment variables
    pass


# AI Review Rubric - v0.4.6 Calibrated (Fixed Structure)
# 固定的质检维度定义,前端展示所需的完整元数据
AI_REVIEW_RUBRIC = [
    {
        "key": "completeness",
        "criterion": "Completeness",
        "weight": "15%",
        "max_score": 15,
        "evaluation_focus": "Check whether the prompt contains all necessary modules, including title, topic, target platform, target audience, video length, core concept, hook, full puzzle setup, question, correct answer, reasoning, narration, on-screen text, visual style, format requirements, constraints, and call to action."
    },
    {
        "key": "logical_correctness",
        "criterion": "Logical Correctness",
        "weight": "20%",
        "max_score": 20,
        "evaluation_focus": "Check whether the puzzle logic, answer, reasoning steps, and explanation are correct. Penalize mathematical mistakes, conceptual errors, contradictions, missing conditions, or mismatch between the question and answer."
    },
    {
        "key": "notebooklm_usability",
        "criterion": "NotebookLM Usability",
        "weight": "15%",
        "max_score": 15,
        "evaluation_focus": "Check whether the prompt is suitable as NotebookLM Copied Text input. It should be clear, structured, executable, and free from irrelevant engineering metadata, database paths, internal comments, or debugging information."
    },
    {
        "key": "visual_directability",
        "criterion": "Visual Directability",
        "weight": "10%",
        "max_score": 10,
        "evaluation_focus": "Check whether the prompt gives enough visual direction, including clean white-background line-art style, clear diagrams, subtitles, scene progression, visual consistency, and restrictions against irrelevant decorative visuals."
    },
    {
        "key": "short_video_suitability",
        "criterion": "Short-video Suitability",
        "weight": "10%",
        "max_score": 10,
        "evaluation_focus": "Check whether the prompt is suitable for TikTok, YouTube Shorts, and Instagram Reels. It should have a strong hook, compact pacing, short-video structure, and a clear ending."
    },
    {
        "key": "single_narrator_compliance",
        "criterion": "Single-narrator Compliance",
        "weight": "10%",
        "max_score": 10,
        "evaluation_focus": "Check whether the prompt clearly requires single narrator / monologue narration and avoids dialogue, interview, podcast, two-host conversation, multiple speakers, or back-and-forth discussion."
    },
    {
        "key": "educational_clarity",
        "criterion": "Educational Clarity",
        "weight": "10%",
        "max_score": 10,
        "evaluation_focus": "Check whether the prompt explains the core idea clearly for students, parents, and general short-video viewers. It should be easy to follow and avoid unnecessary complexity."
    },
    {
        "key": "risk_error_control",
        "criterion": "Risk & Error Control",
        "weight": "10%",
        "max_score": 10,
        "evaluation_focus": "Check whether the prompt includes safeguards against wrong answers, altered puzzle conditions, visual contradictions, irrelevant scenes, excessive decoration, inconsistent diagrams, or misleading explanations."
    }
]


class LLMTopicEnhancer:
    """使用 LLM 将题目增强为完整的 topic JSON"""

    def __init__(self, provider=None, base_url=None, model=None, api_key=None):
        """
        初始化 LLM Topic Enhancer

        Args:
            provider: LLM 提供商 (默认从环境变量读取)
            base_url: API base URL (默认从环境变量读取)
            model: 模型名称 (默认从环境变量读取)
            api_key: API key (默认从环境变量读取)
        """
        self.provider = provider or os.getenv('AI_VIDEO_LLM_PROVIDER', 'openai_compatible')
        self.base_url = base_url or os.getenv('AI_VIDEO_LLM_BASE_URL', 'https://api.openai.com/v1')
        self.model = model or os.getenv('AI_VIDEO_LLM_MODEL', 'gpt-4o-mini')
        self.api_key = api_key or os.getenv('AI_VIDEO_LLM_API_KEY')

        # Optional parameters
        self.temperature = float(os.getenv('AI_VIDEO_LLM_TEMPERATURE', '0.7'))
        self.max_tokens = int(os.getenv('AI_VIDEO_LLM_MAX_TOKENS', '4096'))
        self.timeout = int(os.getenv('AI_VIDEO_LLM_TIMEOUT', '60'))

        # Response format: json_object (default) or none
        self.response_format = os.getenv('AI_VIDEO_LLM_RESPONSE_FORMAT', 'json_object').lower()

        # Prompt mode: full (default) or compact (for debugging)
        self.prompt_mode = os.getenv('AI_VIDEO_LLM_PROMPT_MODE', 'full').lower()

    def check_api_key(self):
        """检查 API key 是否配置"""
        if not self.api_key or self.api_key == 'put_your_api_key_here':
            return False
        return True

    def generate_llm_prompt(self, title):
        """
        生成 LLM prompt

        Args:
            title: 用户输入的题目

        Returns:
            完整的 LLM prompt 字符串
        """
        # Check prompt mode
        if self.prompt_mode == 'compact':
            return self._generate_compact_prompt(title)
        else:
            return self._generate_full_prompt(title)

    def _generate_full_prompt(self, title):
        """
        生成完整版 LLM prompt（正式生产环境使用）

        Args:
            title: 用户输入的题目

        Returns:
            完整的 LLM prompt 字符串
        """
        prompt = dedent(f"""\
        You are an expert educational video content generator for Think Academy's AI educational short video project.

        Your task: Transform the given topic title into a complete, production-ready video content package in JSON format.

        **Input Topic**: {title}

        **Output Requirements**:

        1. **Format**: Output ONLY valid JSON. No markdown, no explanations, no extra text.

        2. **Required Fields**:
        - id: A unique 3-digit ID (e.g., "002", "003")
        - title_cn: Chinese title
        - title_en: English title (engaging and concise)
        - topic_label_en: Category label (e.g., "Probability Puzzle / Gambler's Fallacy")
        - category: Main category (e.g., "概率论", "几何", "数论")
        - core_concept: Core concept being taught
        - target_duration: "50-60s" (fixed)
        - difficulty: "easy", "medium", or "hard"
        - visual_feasibility: "low", "medium", or "high"
        - viral_potential: "low", "medium", or "high"
        - status: "pending"
        - full_problem: Complete problem statement
        - question: The main question to answer
        - correct_answer: The correct answer (brief, clear)
        - short_explanation: 1-3 sentences explaining the core concept
        - wrong_intuition: Common misconception (1-2 sentences)
        - overview_cn: Chinese content overview (200-400 characters), explaining the video design approach naturally. Should cover: what problem the video addresses, how it opens, how the puzzle is designed, how reasoning unfolds, how visuals work, and what viewers should understand. Write in a natural explanatory style, not as a mechanical checklist. Must be specific to this topic, not a generic template.
        - reasoning_steps: Array of 4-6 reasoning steps, each with:
          * step: step number (1, 2, 3...)
          * step_title: Short title
          * explanation: Clear explanation
        - hook: Opening hook (1-2 sentences, ~10-15 words)
        - takeaway: Key takeaway (1-2 sentences)
        - cta: Call to action (e.g., "Follow for more [topic] puzzles")
        - narration_script: Full narration script (110-150 words total, English)
        - subtitle_segments: Array of 8-10 subtitle segments, each with:
          * timestamp: "00:00-00:04" format
          * text: Subtitle text
          * highlight_words: Key words to highlight
        - storyboard_scenes: Array of exactly 6 scenes, each with:
          * scene_id: 1, 2, 3, 4, 5, 6
          * timestamp: Scene timing (e.g., "00:00-00:04")
          * narration: What the narrator says during this scene
          * onscreen_text: Text displayed on screen
          * visual_description: Detailed visual description
          * style_restrictions: Style guidelines for this scene
        - core_visual_consistency: Description of the core visual element that stays consistent
        - notebooklm_specific_instructions: Any special instructions for NotebookLM

        3. **Video Style Requirements** (CRITICAL - MUST FOLLOW):

        **Narration**:
        - Single narrator ONLY
        - One-person explanatory monologue
        - Direct explanation to viewer
        - NO dialogue between characters
        - NO two hosts
        - NO multiple speakers
        - NO podcast style
        - NO interview style
        - NO back-and-forth discussion

        **Visual Style**:
        - White or light graph-paper background
        - Clean doodle / hand-drawn educational style
        - Modern educational style
        - Use simple hand-drawn shapes. Avoid photorealistic or 3D-rendered objects
        - Simple but not childish
        - Use large readable English text. Key phrases should be prominent, but should not cover the main diagram
        - Yellow highlight boxes for key words
        - Black text (#000000) on white/light background
        - Bold Sans-serif font (Arial, Roboto, Montserrat)
        - Consistent core diagram throughout

        **Animations** (simple only):
        - Fade in/out (0.3-0.5s)
        - Zoom in/out (0.5-1s)
        - Pan left/right (1-2s)
        - Hand-drawn animation (elements gradually "draw" themselves)

        **Forbidden Elements**:
        - NO realistic humans (unless topic absolutely requires)
        - NO dialogue bubbles
        - NO podcast visuals
        - NO interview visuals
        - NO dark background
        - NO black background
        - NO decorative clutter
        - NO random objects/characters
        - NO photorealistic images
        - NO 3D renders
        - NO horror elements
        - NO complex 3D animations, spinning, explosions

        4. **Content Requirements**:
        - Logically correct explanation
        - Suitable for TikTok / YouTube Shorts / Instagram Reels
        - Target audience: Students, parents, math/science enthusiasts
        - Duration: 50-60 seconds
        - Narration: 110-150 words (English)
        - Storyboard: Exactly 6 scenes
        - Subtitles: 8-10 segments covering full 50-60s timeline
        - Visuals must support reasoning, not distract
        - Clear, engaging hook at the start
        - Satisfying answer reveal

        **Quality Pattern** (CRITICAL - FOLLOW FOR EVERY TOPIC):
        - Follow the structure: hook → concrete setup → wrong intuition → reveal → visual proof → final lesson
        - For every new title, create a concrete and drawable puzzle setup
        - The wrong intuition must be short, memorable, and screen-friendly
        - Include a visual proof or reveal step that NotebookLM can draw
        - Each reasoning step should correspond to a visual scene
        - Generate topic-specific requirements to prevent wrong answers or wrong visuals
        - Do not copy previous examples. Only imitate their structure and specificity

        5. **Timeline Requirements**:
        - Subtitle segments should span 00:00 to approximately 00:58
        - Storyboard scenes should span 00:00 to approximately 00:58
        - Each subtitle segment: 4-8 seconds
        - Scene distribution (example):
          * Scene 1: 00:00-00:04 (Hook)
          * Scene 2: 00:04-00:11 (Setup)
          * Scene 3: 00:11-00:20 (Wrong intuition)
          * Scene 4: 00:20-00:34 (Key reasoning)
          * Scene 5: 00:34-00:46 (Answer/continuation)
          * Scene 6: 00:46-00:58 (Takeaway/CTA)

        **Output Format**:
        Return ONLY the JSON object. No markdown code blocks, no explanations.
        Ensure all JSON strings are properly escaped.
        Ensure the JSON is valid and can be parsed by json.loads().

        Begin your response with {{ and end with }}.
        """)

        return prompt

    def _generate_compact_prompt(self, title):
        """
        生成简化版 LLM prompt（仅用于调试/测试）

        Args:
            title: 用户输入的题目

        Returns:
            简化的 LLM prompt 字符串
        """
        prompt = dedent(f"""\
        Create a structured outline for a 50-60 second educational video.

        Topic: {title}

        Generate a JSON object with these fields:

        1. Basic Info:
        - title_cn: Chinese title
        - title_en: English title (engaging, concise)
        - category: Main category (e.g., "概率论", "几何", "数论")
        - core_concept: Main concept being taught

        2. Content:
        - full_problem: Complete problem statement
        - question: Main question to answer
        - correct_answer: Correct answer (brief)
        - short_explanation: 1-2 sentences explaining the concept
        - wrong_intuition: Common misconception (1-2 sentences)
        - reasoning_steps: Array of 4-6 steps, each with:
          * step: step number
          * step_title: Short title
          * explanation: Clear explanation

        3. Script:
        - hook: Opening hook (~10-15 words)
        - takeaway: Key takeaway (1-2 sentences)
        - narration_script: Complete script in English (110-150 words)
        - subtitle_segments: Array of 8-10 segments with timestamp, text, highlight_words
        - storyboard_scenes: Array of 6 scenes with scene_id, timestamp, narration, onscreen_text, visual_description

        Timeline: 00:00 to 00:58, typical scene: 8-12 seconds each.

        Return only valid JSON. Start with {{ and end with }}.
        """)

        return prompt

    def call_llm_api(self, prompt, dry_run=False):
        """
        调用 LLM API

        Args:
            prompt: LLM prompt
            dry_run: 如果为 True，不真实调用 API

        Returns:
            LLM 返回的文本
        """
        if dry_run:
            print("⚠️  Dry-run mode: No API call will be made.")
            return None

        if not self.check_api_key():
            raise ValueError(
                "Missing AI_VIDEO_LLM_API_KEY.\n"
                "Please create .env from config/example.env and set your API key.\n\n"
                "Quick setup:\n"
                "  cp config/example.env .env\n"
                "  # Edit .env and add your API key\n"
                "  # Then re-run the command"
            )

        try:
            # Import OpenAI client (only when needed)
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "openai package not found. Install with: pip install openai"
                )

            # Initialize client
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )

            print(f"🤖 Calling LLM API...")
            print(f"   Provider: {self.provider}")
            print(f"   Model: {self.model}")
            print(f"   Base URL: {self.base_url}")
            print(f"   Prompt mode: {self.prompt_mode}")
            print(f"   Prompt length: {len(prompt)} characters")
            print(f"   Max tokens: {self.max_tokens}")
            print(f"   Timeout: {self.timeout}s")

            messages = [
                {
                    "role": "system",
                    "content": "You are an expert educational video content generator. Output valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            # Build base payload with temperature
            base_payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }

            print(f"   Temperature: {self.temperature} (will attempt)")

            # Determine if we should use JSON mode
            use_json_mode = self.response_format == "json_object"
            if use_json_mode:
                print(f"   JSON mode: enabled (will attempt)")
            else:
                print(f"   JSON mode: disabled by config")

            json_mode_used = False

            # Try API call with full parameters
            try:
                if use_json_mode:
                    print(f"   Attempting API call with temperature + JSON mode...")
                    response = client.chat.completions.create(
                        **base_payload,
                        response_format={"type": "json_object"}
                    )
                    json_mode_used = True
                    print(f"✅ Temperature sent, JSON mode sent")
                else:
                    print(f"   Attempting API call with temperature only...")
                    response = client.chat.completions.create(**base_payload)
                    print(f"✅ Temperature sent")

            except Exception as e:
                error_str = str(e).lower()

                # Check if error is about unsupported temperature parameter
                if "unsupported parameter" in error_str and "temperature" in error_str:
                    print(f"⚠️  Temperature parameter not supported, retrying without it...")
                    # Remove temperature and retry
                    retry_payload = {k: v for k, v in base_payload.items() if k != "temperature"}

                    try:
                        if use_json_mode:
                            response = client.chat.completions.create(
                                **retry_payload,
                                response_format={"type": "json_object"}
                            )
                            json_mode_used = True
                            print(f"✅ Temperature skipped after unsupported error, JSON mode sent")
                        else:
                            response = client.chat.completions.create(**retry_payload)
                            print(f"✅ Temperature skipped after unsupported error")
                    except Exception as retry_e:
                        retry_error_str = str(retry_e).lower()
                        # If JSON mode also fails
                        if "response_format" in retry_error_str or "json_object" in retry_error_str or "not supported" in retry_error_str:
                            print(f"⚠️  JSON mode also not supported, retrying with neither...")
                            response = client.chat.completions.create(**retry_payload)
                            json_mode_used = False
                            print(f"✅ Temperature skipped after unsupported error, JSON mode skipped after unsupported error")
                        else:
                            raise

                # Check if error is about unsupported response_format
                elif "response_format" in error_str or "json_object" in error_str or "not supported" in error_str:
                    print(f"⚠️  JSON mode not supported, retrying without it...")
                    # Retry without response_format but keep temperature
                    response = client.chat.completions.create(**base_payload)
                    json_mode_used = False
                    print(f"✅ Temperature sent, JSON mode skipped after unsupported error")

                else:
                    # Other error, re-raise
                    raise

            # Extract response text
            print(f"🔍 Debug: Response object type: {type(response)}")
            print(f"🔍 Debug: Response has choices: {hasattr(response, 'choices')}")

            # Check if response has standard OpenAI structure
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content

                # Handle empty content
                if not response_text:
                    print(f"⚠️  Warning: Response content is empty")
                    print(f"🔍 Debug: Full response: {response}")
                    print(f"🔍 Debug: Message: {response.choices[0].message}")
                    raise ValueError("LLM returned empty response content")

                print(f"✅ LLM response received ({len(response_text)} characters)")
                if json_mode_used:
                    print(f"   JSON mode: enabled")
                else:
                    print(f"   JSON mode: not available (regular mode used)")

                return response_text
            else:
                print(f"❌ Unexpected response structure")
                print(f"🔍 Debug: Full response: {response}")
                raise ValueError("API response does not have expected structure")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error calling LLM API: {e}")

            # Check for timeout errors
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise Exception(
                    f"模型响应超时（当前超时设置：{self.timeout}秒）。\n"
                    f"建议：\n"
                    f"  1. 降低 prompt 长度或简化要求\n"
                    f"  2. 增加 AI_VIDEO_LLM_TIMEOUT 设置（当前：{self.timeout}秒）\n"
                    f"  3. 切换到非 pro/推理模型（如 gpt-4o-mini）以获得更快响应\n"
                    f"原始错误：{error_msg}"
                )

            raise

    def call_chat_messages_api(self, messages, temperature=None, require_json=True):
        """
        Call LLM API with custom messages (for AI Review, Regenerate, etc.)

        This method reuses the compatibility logic from call_llm_api() but allows
        passing custom messages instead of a single prompt string.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Optional temperature (default: None = use self.temperature)
            require_json: Whether to request JSON output (default: True)

        Returns:
            LLM response text (message content)
        """
        if not self.check_api_key():
            raise ValueError(
                "Missing AI_VIDEO_LLM_API_KEY.\n"
                "Please create .env from config/example.env and set your API key.\n\n"
                "Quick setup:\n"
                "  cp config/example.env .env\n"
                "  # Edit .env and add your API key\n"
                "  # Then re-run the command"
            )

        try:
            # Import OpenAI client (only when needed)
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "openai package not found. Install with: pip install openai"
                )

            # Initialize client
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout
            )

            # Use provided temperature or default
            temp = temperature if temperature is not None else self.temperature

            # Build base payload
            base_payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": temp
            }

            # Determine if we should use JSON mode
            use_json_mode = require_json and self.response_format == "json_object"
            json_mode_used = False

            # Try API call with full parameters
            try:
                if use_json_mode:
                    response = client.chat.completions.create(
                        **base_payload,
                        response_format={"type": "json_object"}
                    )
                    json_mode_used = True
                else:
                    response = client.chat.completions.create(**base_payload)

            except Exception as e:
                error_str = str(e).lower()

                # Check if error is about unsupported temperature parameter
                if "unsupported parameter" in error_str and "temperature" in error_str:
                    # Remove temperature and retry
                    retry_payload = {k: v for k, v in base_payload.items() if k != "temperature"}

                    try:
                        if use_json_mode:
                            response = client.chat.completions.create(
                                **retry_payload,
                                response_format={"type": "json_object"}
                            )
                            json_mode_used = True
                        else:
                            response = client.chat.completions.create(**retry_payload)
                    except Exception as retry_e:
                        retry_error_str = str(retry_e).lower()
                        # If JSON mode also fails
                        if "response_format" in retry_error_str or "json_object" in retry_error_str or "not supported" in retry_error_str:
                            response = client.chat.completions.create(**retry_payload)
                            json_mode_used = False
                        else:
                            raise

                # Check if error is about unsupported response_format
                elif "response_format" in error_str or "json_object" in error_str or "not supported" in error_str:
                    # Retry without response_format but keep temperature
                    response = client.chat.completions.create(**base_payload)
                    json_mode_used = False

                else:
                    # Other error, re-raise
                    raise

            # Extract response text
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content

                # Handle empty content
                if not response_text:
                    raise ValueError("LLM returned empty response content")

                return response_text
            else:
                raise ValueError("API response does not have expected structure")

        except Exception as e:
            error_msg = str(e)

            # Check for timeout errors
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise Exception(
                    f"LLM API timeout (current: {self.timeout}s).\n"
                    f"Suggestions:\n"
                    f"  1. Simplify the prompt or reduce length\n"
                    f"  2. Increase AI_VIDEO_LLM_TIMEOUT (current: {self.timeout}s)\n"
                    f"  3. Switch to faster model (e.g., gpt-4o-mini)\n"
                    f"Original error: {error_msg}"
                )

            raise

    def parse_json_response(self, response_text):
        """
        解析 LLM 返回的 JSON

        Args:
            response_text: LLM 返回的文本

        Returns:
            解析后的 JSON 对象
        """
        if not response_text:
            raise ValueError("LLM returned empty response")

        text = response_text.strip()

        # Strategy 1: Try direct JSON parse (if response is pure JSON)
        try:
            topic_json = json.loads(text)
            print(f"✅ JSON parsed successfully (direct)")
            return topic_json
        except json.JSONDecodeError:
            pass  # Try other strategies

        # Strategy 2: Remove markdown code blocks
        cleaned_text = text
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith('```'):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()

        try:
            topic_json = json.loads(cleaned_text)
            print(f"✅ JSON parsed successfully (after removing code blocks)")
            return topic_json
        except json.JSONDecodeError:
            pass  # Try next strategy

        # Strategy 3: Extract JSON from mixed text (find first { to last })
        try:
            first_brace = text.find('{')
            last_brace = text.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_text = text[first_brace:last_brace+1]
                topic_json = json.loads(json_text)
                print(f"✅ JSON parsed successfully (extracted from mixed text)")
                return topic_json
        except json.JSONDecodeError:
            pass  # All strategies failed

        # All strategies failed
        print(f"❌ JSON parse error: All parsing strategies failed")
        print(f"   Response preview (first 200 chars): {text[:200]}")
        print(f"\n💡 Debug tip: Check llm_raw_response.txt for full LLM output")
        raise ValueError(f"Failed to parse JSON response after trying multiple strategies")

    def add_fixed_fields(self, topic):
        """
        补充固定字段（不需要 LLM 生成的标准内容）

        Args:
            topic: LLM 生成的 topic JSON

        Returns:
            补充后的完整 topic JSON
        """
        # Add standard metadata fields if missing
        if 'id' not in topic:
            topic['id'] = '999'  # Placeholder, will be assigned later

        if 'topic_label_en' not in topic:
            # Derive from title_en and category
            category = topic.get('category', 'General')
            topic['topic_label_en'] = f"{topic.get('title_en', 'Untitled')} / {category}"

        if 'target_duration' not in topic:
            topic['target_duration'] = '50-60s'

        if 'difficulty' not in topic:
            topic['difficulty'] = 'medium'

        if 'visual_feasibility' not in topic:
            topic['visual_feasibility'] = 'medium'

        if 'viral_potential' not in topic:
            topic['viral_potential'] = 'medium'

        if 'status' not in topic:
            topic['status'] = 'pending'

        # Add standard CTA if missing
        if 'cta' not in topic:
            category = topic.get('category', 'puzzles')
            topic['cta'] = f"Follow for more {category}!"

        # Add standard NotebookLM instructions (fixed style constraints)
        if 'notebooklm_specific_instructions' not in topic:
            topic['notebooklm_specific_instructions'] = [
                "Use a clean white or light background throughout the video",
                "Use simple hand-drawn or line-art educational visuals only",
                "Keep all visuals focused on the reasoning process and key concepts",
                "Use large, readable English text for all on-screen text and key ideas",
                "Maintain one consistent narrator voice throughout (single person explaining)",
                "Avoid complex animations or distracting visual effects",
                "Show reasoning steps clearly with visual diagrams"
            ]

        # Add core visual consistency if missing
        if 'core_visual_consistency' not in topic:
            topic['core_visual_consistency'] = (
                "Clean white background with simple black line drawings. "
                "All visuals should be minimalist educational diagrams that support the narration. "
                "Text should be large and clearly readable."
            )

        # Add style_restrictions to each storyboard scene if missing
        if 'storyboard_scenes' in topic:
            for scene in topic['storyboard_scenes']:
                if 'style_restrictions' not in scene:
                    scene['style_restrictions'] = (
                        "White background, simple line art, minimal text, "
                        "educational diagram style, single narrator"
                    )

        return topic

    def validate_enhanced_topic(self, topic):
        """
        验证 enhanced topic JSON

        Args:
            topic: 解析后的 topic JSON

        Returns:
            (is_valid, errors) tuple
        """
        errors = []

        # Required fields (all 21 fields, overview_cn is recommended but not strictly required for backwards compatibility)
        required_fields = [
            'title_cn', 'title_en', 'topic_label_en', 'category',
            'core_concept', 'target_duration', 'full_problem', 'question',
            'correct_answer', 'short_explanation', 'wrong_intuition',
            'reasoning_steps', 'hook', 'takeaway', 'cta',
            'narration_script', 'subtitle_segments', 'storyboard_scenes',
            'core_visual_consistency', 'notebooklm_specific_instructions'
        ]

        # overview_cn is recommended but optional for validation (will use fallback if missing)
        recommended_fields = ['overview_cn']

        # Check recommended fields (warn but don't fail)
        for field in recommended_fields:
            if field not in topic or not topic[field]:
                print(f"⚠️  Warning: Recommended field '{field}' is missing or empty. Will use fallback.")

        for field in required_fields:
            if field not in topic:
                errors.append(f"Missing required field: {field}")
            elif not topic[field]:
                errors.append(f"Empty required field: {field}")

        # Validate reasoning_steps
        if 'reasoning_steps' in topic:
            steps = topic['reasoning_steps']
            if not isinstance(steps, list):
                errors.append("reasoning_steps must be an array")
            elif len(steps) < 4:
                errors.append(f"reasoning_steps must have at least 4 steps (found {len(steps)})")
            else:
                # Validate each step has required fields
                for i, step in enumerate(steps):
                    if 'step' not in step:
                        errors.append(f"reasoning_steps[{i}] missing 'step' field")
                    if 'step_title' not in step:
                        errors.append(f"reasoning_steps[{i}] missing 'step_title' field")
                    if 'explanation' not in step:
                        errors.append(f"reasoning_steps[{i}] missing 'explanation' field")

        # Validate storyboard_scenes
        if 'storyboard_scenes' in topic:
            scenes = topic['storyboard_scenes']
            if not isinstance(scenes, list):
                errors.append("storyboard_scenes must be an array")
            elif len(scenes) != 6:
                errors.append(f"storyboard_scenes must have exactly 6 scenes (found {len(scenes)})")
            else:
                # Validate each scene has required fields
                for i, scene in enumerate(scenes):
                    if 'scene_id' not in scene:
                        errors.append(f"storyboard_scenes[{i}] missing 'scene_id' field")
                    if 'timestamp' not in scene:
                        errors.append(f"storyboard_scenes[{i}] missing 'timestamp' field")
                    if 'narration' not in scene:
                        errors.append(f"storyboard_scenes[{i}] missing 'narration' field")
                    if 'onscreen_text' not in scene:
                        errors.append(f"storyboard_scenes[{i}] missing 'onscreen_text' field")
                    if 'visual_description' not in scene:
                        errors.append(f"storyboard_scenes[{i}] missing 'visual_description' field")

        # Validate subtitle_segments
        if 'subtitle_segments' in topic:
            segments = topic['subtitle_segments']
            if not isinstance(segments, list):
                errors.append("subtitle_segments must be an array")
            elif len(segments) < 8:
                errors.append(f"subtitle_segments must have at least 8 segments (found {len(segments)})")

        # Validate narration_script word count (relaxed: 90-170)
        if 'narration_script' in topic:
            script = topic['narration_script']
            word_count = len(script.split())
            if word_count < 90:
                errors.append(f"narration_script too short ({word_count} words, recommended 110-150)")
            elif word_count > 170:
                errors.append(f"narration_script too long ({word_count} words, recommended 110-150)")

        # Validate critical fields not empty
        critical_fields = ['correct_answer', 'wrong_intuition', 'notebooklm_specific_instructions']
        for field in critical_fields:
            if field in topic and not str(topic[field]).strip():
                errors.append(f"Critical field '{field}' is empty")

        is_valid = len(errors) == 0
        return is_valid, errors

    def enhance_topic(self, title, output_folder=None, dry_run=False):
        """
        完整流程：将题目转换为 enhanced topic JSON

        Args:
            title: 用户输入的题目
            output_folder: 输出文件夹（保存 llm_generation_prompt.md 和 llm_raw_response.txt）
            dry_run: 是否为 dry-run 模式

        Returns:
            enhanced topic JSON (如果 dry_run=True，返回 None)
        """
        # 1. Generate LLM prompt
        print(f"\n📝 Generating LLM prompt for topic: {title}")
        prompt = self.generate_llm_prompt(title)

        # Save prompt to file
        if output_folder:
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)

            prompt_file = output_folder / "llm_generation_prompt.md"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(f"# LLM Generation Prompt\n\n")
                f.write(f"**Topic**: {title}\n\n")
                f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Provider**: {self.provider}\n\n")
                f.write(f"**Model**: {self.model}\n\n")
                f.write(f"---\n\n")
                f.write(prompt)
            print(f"✅ Saved LLM prompt to: {prompt_file}")

        if dry_run:
            print("\n⚠️  Dry-run mode: Stopping here. No API call will be made.")
            return None

        # 2. Call LLM API
        response_text = self.call_llm_api(prompt, dry_run=dry_run)

        # Save raw response
        if output_folder and response_text:
            response_file = output_folder / "llm_raw_response.txt"
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write(f"# LLM Raw Response\n\n")
                f.write(f"**Topic**: {title}\n\n")
                f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Provider**: {self.provider}\n\n")
                f.write(f"**Model**: {self.model}\n\n")
                f.write(f"---\n\n")
                f.write(response_text)
            print(f"✅ Saved raw response to: {response_file}")

        # 3. Parse JSON
        try:
            topic_json = self.parse_json_response(response_text)

            # Add fixed fields if using compact mode (full mode should have all fields from LLM)
            if self.prompt_mode == 'compact':
                print(f"✅ Adding fixed fields (style constraints, metadata)...")
                topic_json = self.add_fixed_fields(topic_json)

        except ValueError as e:
            # JSON parse failed - save error file
            if output_folder:
                error_file = output_folder / "llm_error.txt"
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(f"# LLM Error\n\n")
                    f.write(f"**Error Type**: JSON Parse Error\n\n")
                    f.write(f"**Error Message**: {str(e)}\n\n")
                    f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"---\n\n")
                    f.write(f"Check llm_raw_response.txt for full LLM output.\n")
                print(f"✓ Saved error details to: {error_file}")
            raise

        # 4. Validate
        is_valid, errors = self.validate_enhanced_topic(topic_json)

        if not is_valid:
            print(f"\n❌ Validation failed with {len(errors)} errors:")
            for error in errors:
                print(f"   - {error}")

            # Save validation errors
            if output_folder:
                error_file = output_folder / "validation_errors.txt"
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Validation Errors\n\n")
                    f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"**Total Errors**: {len(errors)}\n\n")
                    f.write(f"---\n\n")
                    for error in errors:
                        f.write(f"- {error}\n")
                print(f"✓ Saved validation errors to: {error_file}")

            raise ValueError(f"Enhanced topic validation failed with {len(errors)} errors. See validation_errors.txt")

        print(f"\n✅ Enhanced topic validation passed")

        return topic_json

    def regenerate_prompt(
        self,
        title: str,
        current_raw_text: str,
        current_overview_cn: str,
        user_feedback: str,
        output_folder=None,
        dry_run=False
    ):
        """
        Based on current prompt and user feedback, regenerate a new version

        Args:
            title: Topic title
            current_raw_text: Current NotebookLM prompt text
            current_overview_cn: Current overview in Chinese
            user_feedback: User's feedback for regeneration
            output_folder: Output folder for saving logs
            dry_run: Dry-run mode flag

        Returns:
            Dict with: {
                "title": str,
                "topic": str,
                "raw_text": str (new complete NotebookLM Prompt),
                "overview_cn": str (new overview),
                "change_summary_cn": str (summary of changes),
                "core_concept": str,
                "video_length": str,
                "target_platform": str,
                "target_audience": str
            }
        """
        # Generate regenerate prompt
        print(f"\n📝 Generating regenerate prompt for: {title}")
        prompt = self._generate_regenerate_prompt(
            title, current_raw_text, current_overview_cn, user_feedback
        )

        # Save prompt to file
        if output_folder:
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)

            prompt_file = output_folder / "llm_regenerate_prompt.md"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(f"# LLM Regenerate Prompt\n\n")
                f.write(f"**Topic**: {title}\n\n")
                f.write(f"**Feedback**: {user_feedback}\n\n")
                f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"---\n\n")
                f.write(prompt)
            print(f"✅ Saved regenerate prompt to: {prompt_file}")

        if dry_run:
            print("\n⚠️  Dry-run mode: Stopping here. No API call will be made.")
            return None

        # Call LLM API
        response_text = self.call_llm_api(prompt, dry_run=dry_run)

        # Save raw response
        if output_folder and response_text:
            response_file = output_folder / "llm_regenerate_response.txt"
            with open(response_file, 'w', encoding='utf-8') as f:
                f.write(f"# LLM Regenerate Response\n\n")
                f.write(f"**Topic**: {title}\n\n")
                f.write(f"**Feedback**: {user_feedback}\n\n")
                f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"---\n\n")
                f.write(response_text)
            print(f"✅ Saved regenerate response to: {response_file}")

        # Parse JSON
        try:
            result_json = self.parse_json_response(response_text)
            print(f"\n✅ Regenerate result parsed successfully")
            return result_json
        except ValueError as e:
            # JSON parse failed
            if output_folder:
                error_file = output_folder / "llm_regenerate_error.txt"
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(f"# LLM Regenerate Error\n\n")
                    f.write(f"**Error Type**: JSON Parse Error\n\n")
                    f.write(f"**Error Message**: {str(e)}\n\n")
                    f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                print(f"✓ Saved error details to: {error_file}")
            raise

    def _generate_regenerate_prompt(
        self, title: str, current_raw_text: str, current_overview_cn: str, user_feedback: str
    ) -> str:
        """
        Generate LLM prompt for regenerating based on current version and feedback

        Args:
            title: Topic title
            current_raw_text: Current NotebookLM prompt
            current_overview_cn: Current overview in Chinese
            user_feedback: User's feedback

        Returns:
            Complete LLM prompt string
        """
        prompt = dedent(f"""\
        You are an expert educational video content generator for NotebookLM video prompts.

        **Task**: Regenerate an improved NotebookLM Prompt based on the current version and user feedback.

        **Topic**: {title}

        **Current NotebookLM Prompt**:
        {current_raw_text}

        **Current Overview (Chinese)**:
        {current_overview_cn}

        **User Feedback**:
        {user_feedback}

        **Your Task**:
        Based on the current prompt and user feedback, generate an IMPROVED version that:
        1. Addresses all points in the user feedback
        2. Preserves effective elements from the current version
        3. Maintains all critical NotebookLM style constraints
        4. Outputs a COMPLETE new NotebookLM Prompt (not just changes)

        **Critical Style Constraints** (MUST MAINTAIN):

        **Narration**:
        - Single narrator ONLY (one-person explanatory monologue)
        - NO dialogue, NO two hosts, NO multiple speakers
        - NO podcast style, NO interview style

        **Visual Style**:
        - White or light graph-paper background
        - Clean doodle / hand-drawn educational style
        - Large readable English text
        - Yellow highlight boxes for key words
        - Black text on white/light background
        - Consistent core diagram throughout

        **Forbidden Elements**:
        - NO realistic humans (unless absolutely necessary)
        - NO dialogue bubbles
        - NO podcast/interview visuals
        - NO dark background
        - NO photorealistic images or 3D renders
        - NO complex animations

        **Output Format**:
        Return ONLY valid JSON with the following structure:

        {{
          "title": "<topic title>",
          "topic": "<brief topic description>",
          "raw_text": "<COMPLETE new NotebookLM Prompt as a single string>",
          "overview_cn": "<new Chinese overview explaining the video design approach>",
          "change_summary_cn": "<Chinese summary of what changed compared to previous version>",
          "core_concept": "<core concept>",
          "video_length": "50-60s",
          "target_platform": "TikTok / YouTube Shorts / Instagram Reels",
          "target_audience": "<target audience>"
        }}

        **Requirements for raw_text**:
        - Must be a COMPLETE NotebookLM Prompt (not partial)
        - Must include all sections: Title, Topic, Target platform, Target audience, Video length, Core concept, Puzzle setup, Question, Correct answer, Wrong intuition, Reasoning, Narration Script, On-screen text, Visual style, Important requirements
        - Must be logically correct
        - Must follow single narrator monologue style
        - Must maintain white/light background educational style

        **Requirements for change_summary_cn**:
        - Must be in Chinese
        - Must explain what changed compared to the previous version
        - Should be 100-300 characters
        - Should be specific and helpful for the user
        - Example: "本次重新生成主要根据用户反馈强化了开头的吸引力，将原本较抽象的解释改成了更生活化的场景。同时补充了更明确的分步推理结构，并在视觉设计中增加了关键数字高亮和对比画面，帮助观众更快理解核心逻辑。"

        **Output Format**:
        Return ONLY the JSON object. No markdown code blocks, no explanations.
        Begin your response with {{ and end with }}.
        """)

        return prompt

    def _normalize_review_data(self, review_data):
        """
        Normalize and fix common issues in AI Review JSON response

        Args:
            review_data: Parsed JSON review data

        Returns:
            Normalized review data with fixes applied
        """
        if not isinstance(review_data, dict):
            return review_data

        # Fix rows array issues
        if "rows" in review_data and isinstance(review_data["rows"], list):
            for row in review_data["rows"]:
                if not isinstance(row, dict):
                    continue

                # Convert string scores to integers
                if "score" in row and isinstance(row["score"], str):
                    try:
                        row["score"] = int(row["score"])
                    except (ValueError, TypeError):
                        pass

                if "max_score" in row and isinstance(row["max_score"], str):
                    try:
                        row["max_score"] = int(row["max_score"])
                    except (ValueError, TypeError):
                        pass

                # Auto-generate llm_score if missing
                if "llm_score" not in row or not row["llm_score"]:
                    score = row.get("score", 0)
                    max_score = row.get("max_score", 0)
                    row["llm_score"] = f"{score}/{max_score}"

                # Add default comment if missing
                if "llm_comment" not in row or not row["llm_comment"]:
                    row["llm_comment"] = "No detailed comment provided."

        # Convert string total_score to integer
        if "total_score" in review_data and isinstance(review_data["total_score"], str):
            try:
                review_data["total_score"] = int(review_data["total_score"])
            except (ValueError, TypeError):
                pass

        # Auto-calculate total_score if missing or invalid
        if "total_score" not in review_data or not isinstance(review_data["total_score"], int):
            if "rows" in review_data and isinstance(review_data["rows"], list):
                total = 0
                for row in review_data["rows"]:
                    if isinstance(row, dict) and "score" in row:
                        try:
                            total += int(row["score"])
                        except (ValueError, TypeError):
                            pass
                review_data["total_score"] = total
                print(f"⚠️  Auto-calculated total_score: {total}")

        # Add default overall_review if missing
        if "overall_review" not in review_data or not review_data["overall_review"]:
            score = review_data.get("total_score", 0)
            if score >= 95:
                default_review = f"Excellent prompt with a score of {score}/100. Very few improvements needed."
            elif score >= 85:
                default_review = f"Strong prompt with a score of {score}/100. Some minor refinements recommended."
            elif score >= 70:
                default_review = f"Acceptable prompt with a score of {score}/100. Several areas could be improved."
            else:
                default_review = f"Prompt scored {score}/100. Significant improvements needed."
            review_data["overall_review"] = default_review
            print(f"⚠️  Auto-generated overall_review")

        return review_data

    def analyze_prompt_quality_flags(self, raw_prompt: str) -> dict:
        """
        Analyze prompt for obvious quality issues

        Returns dict of flags:
        {
            "title_missing_or_too_short": bool,
            "topic_missing_or_too_short": bool,
            "no_clear_question": bool,
            "no_correct_answer": bool,
            "no_reasoning_steps": bool,
            "no_visual_plan": bool,
            "no_single_narrator_constraint": bool,
            "too_generic": bool,
            "suspiciously_short_prompt": bool,
            "incomplete_sections": bool
        }
        """
        prompt_lower = raw_prompt.lower()
        flags = {}

        # 1. title_missing_or_too_short
        title_section = ""
        if "## title" in prompt_lower:
            title_start = prompt_lower.find("## title")
            next_section = prompt_lower.find("##", title_start + 8)
            if next_section == -1:
                title_section = raw_prompt[title_start:].strip()
            else:
                title_section = raw_prompt[title_start:next_section].strip()

        title_content = title_section.replace("## Title", "").replace("## title", "").strip()
        flags["title_missing_or_too_short"] = (
            len(title_content) < 8 or
            title_content.lower() in ["wh", "why", "test", "untitled", "title", ""] or
            "##" not in raw_prompt.lower() or
            "title" not in prompt_lower
        )

        # 2. topic_missing_or_too_short
        flags["topic_missing_or_too_short"] = (
            "topic" not in prompt_lower or
            (len(prompt_lower.split("topic")[-1].split("##")[0].strip()) < 20 if "topic" in prompt_lower else True)
        )

        # 3. no_clear_question
        flags["no_clear_question"] = (
            "question" not in prompt_lower and
            "?" not in raw_prompt[:1500]  # No question mark in first 1500 chars
        )

        # 4. no_correct_answer
        flags["no_correct_answer"] = (
            "correct answer" not in prompt_lower and
            "answer:" not in prompt_lower and
            "solution:" not in prompt_lower
        )

        # 5. no_reasoning_steps
        flags["no_reasoning_steps"] = (
            "reasoning" not in prompt_lower and
            "explanation" not in prompt_lower and
            "step" not in prompt_lower and
            "why" not in prompt_lower
        )

        # 6. no_visual_plan
        flags["no_visual_plan"] = (
            "visual" not in prompt_lower and
            "scene" not in prompt_lower and
            "storyboard" not in prompt_lower and
            "on-screen" not in prompt_lower
        )

        # 7. no_single_narrator_constraint
        flags["no_single_narrator_constraint"] = (
            "single narrator" not in prompt_lower and
            "monologue" not in prompt_lower and
            ("dialogue" in prompt_lower or "conversation" in prompt_lower or "podcast" in prompt_lower)
        )

        # 8. too_generic
        specific_indicators = [
            any(char.isdigit() for char in raw_prompt),  # Has numbers
            "example" in prompt_lower or "specific" in prompt_lower,
            "such as" in prompt_lower or "e.g." in prompt_lower
        ]
        flags["too_generic"] = sum(specific_indicators) < 2

        # 9. suspiciously_short_prompt
        flags["suspiciously_short_prompt"] = len(raw_prompt) < 1500

        # 10. incomplete_sections
        section_headers = prompt_lower.count("##")
        section_with_content = sum(1 for line in raw_prompt.split("\n") if line.strip() and not line.strip().startswith("#"))
        flags["incomplete_sections"] = section_headers > 5 and section_with_content < section_headers * 3

        return flags

    def apply_strict_score_caps(self, review_data: dict, quality_flags: dict) -> dict:
        """
        Apply hard caps to scores based on quality flags

        Args:
            review_data: Review data with scores
            quality_flags: Dict of quality issues

        Returns:
            Modified review data with capped scores
        """
        rows = review_data.get("rows", [])
        total_score = review_data.get("total_score", 0)

        # Count severe flags
        severe_flags_count = sum([
            quality_flags.get("title_missing_or_too_short", False),
            quality_flags.get("no_correct_answer", False),
            quality_flags.get("no_clear_question", False),
            quality_flags.get("no_reasoning_steps", False),
            quality_flags.get("suspiciously_short_prompt", False)
        ])

        # Apply individual dimension caps
        for row in rows:
            criterion = row.get("criterion", "")
            score = row.get("score", 0)
            max_score = row.get("max_score", 10)
            cap_applied = False
            cap_reason = ""

            # 1. title_missing_or_too_short
            if quality_flags.get("title_missing_or_too_short"):
                if criterion == "Completeness" and score > 9:
                    row["score"] = 9
                    cap_applied = True
                    cap_reason = "the title is missing or too short"
                elif criterion == "NotebookLM Usability" and score > 10:
                    row["score"] = 10
                    cap_applied = True
                    cap_reason = "the title is missing or too short"
                elif criterion == "Educational Clarity" and score > 6:
                    row["score"] = 6
                    cap_applied = True
                    cap_reason = "the title is missing or too short"

            # 2. no_correct_answer
            if quality_flags.get("no_correct_answer"):
                if criterion == "Logical Correctness" and score > 10:
                    row["score"] = 10
                    cap_applied = True
                    cap_reason = "correct answer is missing"
                elif criterion == "Risk & Error Control" and score > 5:
                    row["score"] = 5
                    cap_applied = True
                    cap_reason = "correct answer is missing"

            # 3. no_reasoning_steps
            if quality_flags.get("no_reasoning_steps"):
                if criterion == "Logical Correctness" and score > 12:
                    row["score"] = 12
                    cap_applied = True
                    cap_reason = "reasoning steps are missing"
                elif criterion == "Educational Clarity" and score > 6:
                    row["score"] = 6
                    cap_applied = True
                    cap_reason = "reasoning steps are missing"

            # 4. no_clear_question
            if quality_flags.get("no_clear_question"):
                if criterion == "Completeness" and score > 10:
                    row["score"] = 10
                    cap_applied = True
                    cap_reason = "clear question is missing"
                elif criterion == "Logical Correctness" and score > 13:
                    row["score"] = 13
                    cap_applied = True
                    cap_reason = "clear question is missing"

            # 5. no_visual_plan
            if quality_flags.get("no_visual_plan"):
                if criterion == "Visual Directability" and score > 5:
                    row["score"] = 5
                    cap_applied = True
                    cap_reason = "visual plan is missing"
                elif criterion == "Short-video Suitability" and score > 7:
                    row["score"] = 7
                    cap_applied = True
                    cap_reason = "visual plan is missing"

            # 6. no_single_narrator_constraint
            if quality_flags.get("no_single_narrator_constraint"):
                if criterion == "Single-narrator Compliance" and score > 5:
                    row["score"] = 5
                    cap_applied = True
                    cap_reason = "single narrator constraint is missing"

            # 7. too_generic
            if quality_flags.get("too_generic"):
                if criterion == "Visual Directability" and score > 7:
                    row["score"] = 7
                    cap_applied = True
                    cap_reason = "content is too generic"
                elif criterion == "Educational Clarity" and score > 7:
                    row["score"] = 7
                    cap_applied = True
                    cap_reason = "content is too generic"

            # Update llm_score and add cap note to comment
            if cap_applied:
                row["llm_score"] = f"{row['score']}/{max_score}"
                if not row.get("llm_comment", "").endswith("."):
                    row["llm_comment"] = row.get("llm_comment", "") + "."
                row["llm_comment"] += f" Strict cap applied: {cap_reason}."

        # Recalculate total score
        new_total = sum(row.get("score", 0) for row in rows)

        # Apply total score caps
        original_total = new_total

        if quality_flags.get("title_missing_or_too_short") and new_total > 72:
            new_total = 72

        if quality_flags.get("no_correct_answer") and new_total > 65:
            new_total = 65

        if quality_flags.get("no_reasoning_steps") and new_total > 70:
            new_total = 70

        if quality_flags.get("no_clear_question") and new_total > 70:
            new_total = 70

        if quality_flags.get("no_visual_plan") and new_total > 78:
            new_total = 78

        if quality_flags.get("suspiciously_short_prompt") and new_total > 70:
            new_total = 70

        if quality_flags.get("too_generic") and new_total > 82:
            new_total = 82

        if severe_flags_count >= 3 and new_total > 68:
            new_total = 68

        if severe_flags_count >= 5 and new_total > 55:
            new_total = 55

        # If total was capped, proportionally reduce all scores
        if new_total < original_total and original_total > 0:
            scale_factor = new_total / original_total
            for row in rows:
                old_score = row.get("score", 0)
                new_score = int(old_score * scale_factor)
                if new_score != old_score:
                    row["score"] = new_score
                    row["llm_score"] = f"{new_score}/{row.get('max_score', 10)}"

        review_data["total_score"] = new_total
        review_data["rows"] = rows

        return review_data

    def calibrate_score_comment_consistency(self, review_data: dict) -> dict:
        """
        Calibrate scores when comments contain negative words but scores are high

        Args:
            review_data: Review data

        Returns:
            Calibrated review data
        """
        negative_words_mild = ["however", "minor gap", "could improve", "could be more", "should include", "not enough", "needs"]
        negative_words_severe = ["missing", "unclear", "incomplete", "generic", "underspecified", "not explicit", "lacks", "weak", "vague"]

        rows = review_data.get("rows", [])

        for row in rows:
            comment = row.get("llm_comment", "").lower()
            score = row.get("score", 0)
            max_score = row.get("max_score", 10)
            score_ratio = score / max_score if max_score > 0 else 0

            has_mild_negative = any(word in comment for word in negative_words_mild)
            has_severe_negative = any(word in comment for word in negative_words_severe)

            # If score is too high despite negative words
            if has_severe_negative and score_ratio >= 0.9:
                # Reduce to 65-75% of max
                new_score = int(max_score * 0.70)
                if new_score < score:
                    row["score"] = new_score
                    row["llm_score"] = f"{new_score}/{max_score}"
                    if not row.get("llm_comment", "").endswith("."):
                        row["llm_comment"] += "."
                    row["llm_comment"] += " Score calibrated downward because the review comment identified a concrete weakness."

            elif has_mild_negative and score_ratio >= 0.95:
                # Reduce to 80-85% of max
                new_score = int(max_score * 0.83)
                if new_score < score:
                    row["score"] = new_score
                    row["llm_score"] = f"{new_score}/{max_score}"
                    if not row.get("llm_comment", "").endswith("."):
                        row["llm_comment"] += "."
                    row["llm_comment"] += " Score calibrated downward because the review comment identified a concrete weakness."

        # Recalculate total score
        review_data["total_score"] = sum(row.get("score", 0) for row in rows)
        review_data["rows"] = rows

        return review_data

    def _build_review_table_from_llm_scores(self, llm_data):
        """
        Merge LLM simplified output with fixed rubric to build complete review table

        Args:
            llm_data: LLM output in format:
                {
                    "scores": [{"key": "completeness", "score": 13, "comment": "..."}],
                    "overall_review": "..."
                }

        Returns:
            Complete review data in frontend-compatible format:
            {
                "rows": [
                    {
                        "criterion": "Completeness",
                        "weight": "15%",
                        "evaluation_focus": "...",
                        "max_score": 15,
                        "score": 13,
                        "llm_score": "13/15",
                        "llm_comment": "..."
                    },
                    ...
                ],
                "total_score": 89,
                "overall_review": "..."
            }
        """
        if not isinstance(llm_data, dict):
            raise ValueError("LLM data must be a dict")

        if "scores" not in llm_data or not isinstance(llm_data["scores"], list):
            raise ValueError("LLM data must contain 'scores' array")

        # Build key-to-score mapping
        score_map = {}
        for item in llm_data["scores"]:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            score = item.get("score")
            comment = item.get("comment", "")
            if key:
                score_map[key] = {"score": score, "comment": comment}

        # Merge with fixed rubric
        rows = []
        total_score = 0

        for dim in AI_REVIEW_RUBRIC:
            key = dim["key"]
            score_data = score_map.get(key, {"score": 0, "comment": "No comment provided."})
            score = score_data["score"]
            comment = score_data["comment"]

            # Validate and normalize score
            if not isinstance(score, int):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0

            # Ensure score within bounds
            max_score = dim["max_score"]
            if score < 0:
                score = 0
            if score > max_score:
                score = max_score

            total_score += score

            # Build complete row
            rows.append({
                "criterion": dim["criterion"],
                "weight": dim["weight"],
                "evaluation_focus": dim["evaluation_focus"],
                "max_score": max_score,
                "score": score,
                "llm_score": f"{score}/{max_score}",
                "llm_comment": comment if comment else "No comment provided."
            })

        # Get overall review
        overall_review = llm_data.get("overall_review", "")
        if not overall_review:
            # Auto-generate if missing
            if total_score >= 95:
                overall_review = f"Excellent prompt with a score of {total_score}/100."
            elif total_score >= 85:
                overall_review = f"Strong prompt with a score of {total_score}/100."
            elif total_score >= 70:
                overall_review = f"Acceptable prompt with a score of {total_score}/100."
            else:
                overall_review = f"Prompt scored {total_score}/100."

        return {
            "rows": rows,
            "total_score": total_score,
            "overall_review": overall_review
        }

    def review_prompt(self, raw_prompt, dry_run=False):
        """
        Generate AI Review for a NotebookLM prompt

        Args:
            raw_prompt: The complete NotebookLM prompt to review
            dry_run: If True, return mock data without calling LLM

        Returns:
            dict with review data:
            {
                "rows": [...],
                "total_score": 89,
                "overall_review": "..."
            }
        """
        if dry_run:
            return {
                "rows": [
                    {
                        "criterion": "Completeness",
                        "weight": "15%",
                        "evaluation_focus": "Check whether the prompt contains all necessary modules...",
                        "max_score": 15,
                        "score": 13,
                        "llm_score": "13/15",
                        "llm_comment": "The prompt includes most required modules."
                    }
                ],
                "total_score": 85,
                "overall_review": "The prompt is generally strong. [Dry run mock data]"
            }

        # Build review prompt
        system_prompt = self._build_review_system_prompt()
        user_prompt = self._build_review_user_prompt(raw_prompt)

        # Prepare messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Call LLM using reusable method
        try:
            print(f"🤖 Calling LLM API for AI Review (Calibrated)...")
            print(f"   Model: {self.model}")
            print(f"   Temperature: 0 (for consistent evaluation)")

            # Call with temperature=0 for consistent evaluation
            response_text = self.call_chat_messages_api(
                messages=messages,
                temperature=0,
                require_json=True
            )

            print(f"✅ AI Review response received ({len(response_text)} characters)")

            # Parse JSON response (with cleaning and error handling)
            try:
                llm_data = self.parse_json_response(response_text)
            except Exception as parse_error:
                # Enhanced error logging for JSON parse failures
                print(f"❌ JSON parse error: {str(parse_error)}")
                print(f"   Response length: {len(response_text)} characters")
                print(f"   First 1000 chars:\n{response_text[:1000]}")
                print(f"   Last 1000 chars:\n{response_text[-1000:]}")
                raise

            # Validate simplified LLM response structure
            if not isinstance(llm_data, dict):
                raise ValueError("AI Review response is not a valid JSON object")

            if "scores" not in llm_data:
                raise ValueError("AI Review response missing 'scores' field")

            if not isinstance(llm_data.get("scores"), list):
                raise ValueError("AI Review 'scores' field must be an array")

            if len(llm_data.get("scores", [])) != 8:
                raise ValueError(f"AI Review response has {len(llm_data.get('scores', []))} score entries, expected 8")

            print(f"✅ AI Review LLM response parsed ({len(llm_data['scores'])} dimensions)")

            # Analyze prompt quality flags
            quality_flags = self.analyze_prompt_quality_flags(raw_prompt)
            flagged_issues = [k for k, v in quality_flags.items() if v]
            if flagged_issues:
                print(f"⚠️  Quality flags detected: {', '.join(flagged_issues)}")

            # Merge LLM simplified output with fixed rubric
            review_data = self._build_review_table_from_llm_scores(llm_data)

            # Apply strict score caps based on quality flags
            print(f"📊 Pre-calibration total: {review_data['total_score']}/100")
            review_data = self.apply_strict_score_caps(review_data, quality_flags)
            print(f"📊 Post-caps total: {review_data['total_score']}/100")

            # Calibrate score-comment consistency
            review_data = self.calibrate_score_comment_consistency(review_data)
            print(f"📊 Final total: {review_data['total_score']}/100")

            print(f"✅ AI Review generated: {review_data['total_score']}/100")
            return review_data

        except Exception as e:
            error_msg = f"AI Review generation failed: {str(e)}"
            print(f"❌ {error_msg}")
            raise Exception(error_msg)

    def _build_review_system_prompt(self):
        """Build system prompt for AI Review - v0.4.6.9 Strict Mode"""
        return dedent("""
        You are a strict QA reviewer for NotebookLM educational short-video prompts.
        Your job is to find concrete weaknesses, execution risks, missing details, and logical problems.

        Do not be polite or generous.
        Do not reward surface-level structure.
        A high score requires concrete, topic-specific, directly executable content.

        If the prompt has incomplete title, missing answer, weak reasoning, vague visuals, or generic instructions, assign a significantly lower score.

        You must return strict JSON only. No markdown code blocks, no explanations.
        Your response must be a valid JSON object starting with { and ending with }.
        """).strip()

    def _build_review_user_prompt(self, raw_prompt):
        """Build simplified user prompt - v0.4.6.5 Refactored (LLM only returns scores and comments)"""

        # Build rubric description from fixed structure
        rubric_descriptions = []
        for idx, dim in enumerate(AI_REVIEW_RUBRIC, 1):
            rubric_descriptions.append(f"""
### {idx}. {dim['criterion']} ({dim['max_score']} points, weight: {dim['weight']})
**Key**: `{dim['key']}`
**Focus**: {dim['evaluation_focus']}
""".strip())

        rubric_text = "\n\n".join(rubric_descriptions)

        return dedent(f"""
        Evaluate the following NotebookLM prompt according to the strict rubric below.

        **CRITICAL EVALUATION PRINCIPLES**:
        1. **Evidence-Based Scoring**: Each score must be based on concrete evidence from the prompt text.
        2. **Do NOT default to full score**: Full score requires excellence with no meaningful improvement needed.
        3. **Do NOT reward keyword presence only**: Score based on quality, specificity, executability, and correctness.
        4. **Identify CONCRETE weaknesses**: Every comment must cite specific evidence and specific problems.
        5. **Be strict and critical**: If a comment contains "however", "minor gap", "could improve", "missing", "unclear", "incomplete", "generic", the score should be reduced by at least 15-25% of max.

        **GENERAL SCORING SCALE**:
        - **95-100 of max**: Exceptional. The prompt is complete, topic-specific, logically correct, visually executable, and requires almost no human revision. This score should be RARE.
        - **88-94% of max**: Very strong. The prompt is usable and detailed, but still has minor issues, missing specificity, or small execution risks.
        - **78-87% of max**: Good / usable. The prompt can probably be used, but several parts are generic, incomplete, underspecified, or need manual refinement.
        - **65-77% of max**: Needs revision. The prompt has useful structure, but important details are weak, vague, missing, or not sufficiently tied to the topic.
        - **50-64% of max**: Weak. The prompt is incomplete or hard to execute. Several key modules are missing or shallow.
        - **Below 50%**: Poor. The prompt is mostly unusable, logically broken, or missing core educational content.

        **IMPORTANT**:
        If a criterion has any meaningful weakness, do NOT give full marks.
        If a comment contains "minor gap", "could improve", "missing", "unclear", "incomplete", "generic", "underspecified", or "not explicit", the score should normally be reduced by at least 15-25% of that criterion's max.

        ---

        **8-Dimension Rubric (Total 100 points)**:

        {rubric_text}

        **DIMENSION-SPECIFIC SCORING GUIDANCE**:

        **Completeness (max 15)**:
        - 15/15 only if all key sections exist and each has concrete, topic-specific content.
        - 12-14 if mostly complete but one or two modules are shallow or underspecified.
        - 8-11 if several modules are missing, too short, or generic.
        - 0-7 if the prompt is structurally incomplete.
        - If title is missing or incomplete, max 9/15.

        **Logical Correctness (max 20)**:
        - 18-20 only if question, answer, and reasoning are fully consistent and mathematically sound.
        - 14-17 if generally correct but one reasoning step is vague or underexplained.
        - 9-13 if reasoning is incomplete or the answer is insufficiently justified.
        - 0-8 if answer is missing, wrong, contradictory, or unsupported.
        - If correct answer is missing, max 10/20.

        **NotebookLM Usability (max 15)**:
        - 14-15 only if the prompt can be pasted directly into NotebookLM without cleanup.
        - 11-13 if usable but contains minor ambiguity or weak content.
        - 7-10 if it needs manual refinement.
        - 0-6 if it contains placeholders, incomplete sections, metadata, or broken structure.

        **Visual Directability (max 10)**:
        - 9-10 only if there is concrete scene-by-scene visual guidance.
        - 7-8 if visual style is clear but scene progression is generic.
        - 4-6 if visuals are vague.
        - 0-3 if there is no usable visual direction.

        **Short-video Suitability (max 10)**:
        - 9-10 only if the hook, pacing, conflict, reveal, and ending are explicitly short-video-friendly.
        - 7-8 if generally short-video compatible but pacing is generic.
        - 4-6 if too slow, too lecture-like, or lacks hook.
        - 0-3 if not suitable for short-form video.

        **Single-narrator Compliance (max 10)**:
        - 9-10 only if single narrator / monologue is explicitly required and dialogue/podcast/two-host formats are explicitly forbidden.
        - 6-8 if only one side is stated.
        - 0-5 if missing or ambiguous.

        **Educational Clarity (max 10)**:
        - 9-10 only if a general viewer can understand the core idea within 60 seconds.
        - 7-8 if mostly clear but somewhat dense.
        - 4-6 if explanation is vague or too abstract.
        - 0-3 if hard to follow.

        **Risk & Error Control (max 10)**:
        - 9-10 only if the prompt actively prevents wrong answers, inconsistent visuals, altered conditions, and misleading explanations.
        - 7-8 if some safeguards exist.
        - 4-6 if safeguards are weak.
        - 0-3 if there is no clear error-control logic.

        ---

        **Prompt to evaluate**:
        ```
        {raw_prompt}
        ```

        ---

        **COMMENT FORMAT REQUIREMENTS**:
        Each comment MUST include:
        1. **Evidence**: Cite or summarize specific content from the prompt.
        2. **Weakness**: Identify at least one concrete weakness (if score < max).
        3. **Improvement**: Suggest one specific improvement action.

        Format: "Evidence: [what exists]. Weakness: [specific problem]. Improvement: [concrete suggestion]."

        Do NOT use generic statements like "The prompt is clear", "It is well-structured", "Minor improvements could be made" without specific evidence and specific suggestions.

        ---

        **Output Format**:
        Return ONLY a JSON object with this structure:

        {{
          "scores": [
            {{
              "key": "completeness",
              "score": <integer 0-15>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "logical_correctness",
              "score": <integer 0-20>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "notebooklm_usability",
              "score": <integer 0-15>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "visual_directability",
              "score": <integer 0-10>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "short_video_suitability",
              "score": <integer 0-10>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "single_narrator_compliance",
              "score": <integer 0-10>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "educational_clarity",
              "score": <integer 0-10>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }},
            {{
              "key": "risk_error_control",
              "score": <integer 0-10>,
              "comment": "Evidence: ... Weakness: ... Improvement: ..."
            }}
          ],
          "overall_review": "<2-3 sentence overall evaluation summarizing key strengths and 1-2 most critical improvement areas>"
        }}

        **CRITICAL REMINDERS**:
        - Each score must be an integer, not exceeding max_score
        - Comments must be SPECIFIC with concrete evidence, weakness, and improvement
        - Do NOT give full score unless no meaningful weakness exists
        - If you identify a weakness in the comment, the score MUST reflect that (reduce by 15-25%)
        - Return ONLY the JSON object, no markdown, no extra text
        - Begin with {{ and end with }}
        """).strip()


def main():
    """CLI entry point for testing"""
    if len(sys.argv) < 2:
        print("Usage: python llm_topic_enhancer.py <title> [--dry-run]")
        print("Example: python llm_topic_enhancer.py '为什么数字9总感觉最特别' --dry-run")
        sys.exit(1)

    title = sys.argv[1]
    dry_run = '--dry-run' in sys.argv

    enhancer = LLMTopicEnhancer()

    try:
        topic_json = enhancer.enhance_topic(
            title=title,
            output_folder=Path("outputs") / "test_llm",
            dry_run=dry_run
        )

        if topic_json:
            print("\n✅ Topic enhanced successfully!")
            print(f"   Title (CN): {topic_json.get('title_cn', 'N/A')}")
            print(f"   Title (EN): {topic_json.get('title_en', 'N/A')}")
            print(f"   Word count: {len(topic_json.get('narration_script', '').split())}")
            print(f"   Scenes: {len(topic_json.get('storyboard_scenes', []))}")
            print(f"   Subtitles: {len(topic_json.get('subtitle_segments', []))}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
