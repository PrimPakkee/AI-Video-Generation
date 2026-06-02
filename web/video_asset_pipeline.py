#!/usr/bin/env python3
"""
Video Content Asset Pipeline - v0.5.6 (compatible with the v0.5.5 surface).

Generates the structured content assets that the v0.6.0 Seedance integration
will eventually consume, plus the v0.5.5 dry-run Seedance contract bundle
and the v0.5.6 Seedance prompt compiler bundle. This module **does NOT
call any real video API, does NOT call Seedance, does NOT generate real
mp4, and does NOT download any real video file**. It only:

1. Renders the Video Asset Prompt template with the user topic.
2. Calls an OpenAI-compatible LLM (config from ``AI_VIDEO_LLM_*`` env vars).
3. Parses the strict-JSON response (with markdown-fence + extract fallbacks).
4. Writes 13 deterministic asset files to ``output_dir/video_assets/``:
   ``topic_analysis.json``, ``reasoning.md``, ``video_script.md``,
   ``storyboard.json``, ``provider_prompt.txt``,
   ``provider_request_preview.json``, ``seedance_payload_preview.json``,
   ``provider_contract_validation.json``, ``provider_lifecycle_preview.json``,
   ``seedance_prompt.txt``, ``seedance_negative_prompt.txt``,
   ``seedance_prompt_debug.json``, and the self-registering
   ``generation_manifest.json``.
5. Returns a dict the FastAPI layer can splice into the response.

Any failure (missing API key, network error, JSON parse failure, validation
failure) falls back to a deterministic synthetic asset bundle so the
``/api/video/generate`` endpoint never returns 500 because of asset
generation.

The module never logs the API key, never writes the API key to disk, and
never imports anything from Prompt Mode's NotebookLM template.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VIDEO_ASSETS_SCHEMA_VERSION = "video_assets_v0.5.6"
VIDEO_ASSETS_LEGACY_SCHEMA_VERSION = "video_assets_v0.5.5"
DEFAULT_DURATION_SECONDS = 60
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_STYLE = "clean whiteboard line-art educational short video"
DEFAULT_FPS = 24
DEFAULT_RESOLUTION = "1080x1920"
PROVIDER_NAME = "mock"
PROVIDER_STATUS = "provider_not_configured"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "video_asset_prompt_template.md"

ASSET_FILES = [
    "topic_analysis.json",
    "reasoning.md",
    "video_script.md",
    "storyboard.json",
    "provider_prompt.txt",
    "provider_request_preview.json",
    "generation_manifest.json",
    "seedance_payload_preview.json",
    "provider_contract_validation.json",
    "provider_lifecycle_preview.json",
    "seedance_prompt.txt",
    "seedance_negative_prompt.txt",
    "seedance_prompt_debug.json",
]

REQUIRED_TOP_KEYS = (
    "topic_analysis",
    "reasoning",
    "script",
    "storyboard",
    "provider_prompt",
    "web_copy_placeholder",
)

NEGATIVE_CONSTRAINTS = [
    "no dialogue",
    "no interview",
    "no podcast",
    "no two-host conversation",
    "no multiple speakers",
    "no irrelevant decorative visuals",
    "no wrong answer",
    "no unsupported visual claims",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _detect_language(topic: str) -> str:
    """Return ``zh-CN`` if the topic contains CJK characters, else ``en``."""
    if not topic:
        return "en"
    for ch in topic:
        if "一" <= ch <= "鿿":
            return "zh-CN"
    return "en"


def _read_template() -> str:
    try:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _render_template(topic: str, language: str) -> str:
    template = _read_template()
    if not template:
        return (
            "Generate a strict JSON content asset for an educational short "
            "video on the topic below. Output JSON only, no commentary.\n\n"
            f"Topic: {topic}\n"
            f"Language: {language}\n"
            f"Duration: {DEFAULT_DURATION_SECONDS}s\n"
            f"Aspect Ratio: {DEFAULT_ASPECT_RATIO}\n"
            f"Style: {DEFAULT_STYLE}\n"
        )
    return (
        template
        .replace("{{TOPIC}}", topic)
        .replace("{{LANGUAGE}}", language)
        .replace("{{DURATION_SECONDS}}", str(DEFAULT_DURATION_SECONDS))
        .replace("{{ASPECT_RATIO}}", DEFAULT_ASPECT_RATIO)
        .replace("{{STYLE}}", DEFAULT_STYLE)
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of a JSON object from LLM output."""
    if not text:
        return None
    candidate = text.strip()
    # Direct parse.
    try:
        return json.loads(candidate)
    except Exception:
        pass
    # Strip ```json ... ``` fences.
    fence = candidate
    if fence.startswith("```json"):
        fence = fence[7:]
    elif fence.startswith("```"):
        fence = fence[3:]
    if fence.endswith("```"):
        fence = fence[:-3]
    fence = fence.strip()
    try:
        return json.loads(fence)
    except Exception:
        pass
    # Extract the outermost { ... } block.
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(candidate[first:last + 1])
        except Exception:
            return None
    return None


def _resolve_api_key() -> Tuple[Optional[str], str]:
    """Return ``(key, source)`` using ``AI_VIDEO_LLM_API_KEY`` as the primary
    source. ``OPENAI_API_KEY`` is only checked as a low-priority fallback so
    legacy environments still work; the primary v0.5.4 config is the
    ``AI_VIDEO_LLM_*`` set. The key value itself is never logged or written
    anywhere — only the fact that it was configured (a bool) is surfaced.
    """
    primary = os.getenv("AI_VIDEO_LLM_API_KEY")
    if primary and primary.strip() and primary != "put_your_api_key_here":
        return primary, "AI_VIDEO_LLM_API_KEY"
    legacy = os.getenv("OPENAI_API_KEY")
    if legacy and legacy.strip() and legacy != "put_your_api_key_here":
        return legacy, "OPENAI_API_KEY"
    return None, ""


def _call_llm(prompt_text: str, warnings: List[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Call the configured OpenAI-compatible LLM.

    Returns ``(raw_text, debug)``. ``raw_text`` is None if the call could not
    be made or failed; the failure reason is appended to ``warnings``. The
    debug dict carries non-secret config metadata (model, base_url,
    temperature, etc.) and never contains the API key.
    """
    api_key, api_key_source = _resolve_api_key()
    base_url = os.getenv("AI_VIDEO_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("AI_VIDEO_LLM_MODEL", "gpt-5-chat")
    timeout = int(os.getenv("AI_VIDEO_LLM_TIMEOUT", "60"))
    max_tokens = int(os.getenv("AI_VIDEO_LLM_MAX_TOKENS", "4096"))
    try:
        temperature: Optional[float] = float(os.getenv("AI_VIDEO_LLM_TEMPERATURE", "0.7"))
    except Exception:
        temperature = 0.7
    response_format = os.getenv("AI_VIDEO_LLM_RESPONSE_FORMAT", "json_object").lower()

    debug: Dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "base_url_configured": bool(base_url),
        "timeout_seconds": timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": response_format,
        "api_key_configured": bool(api_key),
        "api_key_source": api_key_source or None,
        "config_namespace": "AI_VIDEO_LLM_*",
    }

    if not debug["api_key_configured"]:
        warnings.append("AI_VIDEO_LLM_API_KEY not configured; using fallback assets.")
        return None, debug

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        warnings.append(f"openai package unavailable: {exc}")
        return None, debug

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    except Exception as exc:
        warnings.append(f"OpenAI client init failed: {exc}")
        return None, debug

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert educational short-video content designer. "
                "Output strict JSON only, no markdown fence, no commentary."
            ),
        },
        {"role": "user", "content": prompt_text},
    ]

    base_payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        base_payload["temperature"] = temperature

    use_json_mode = response_format == "json_object"

    def _do_call(payload: Dict[str, Any], with_json_mode: bool):
        if with_json_mode:
            return client.chat.completions.create(
                **payload,
                response_format={"type": "json_object"},
            )
        return client.chat.completions.create(**payload)

    try:
        try:
            response = _do_call(base_payload, with_json_mode=use_json_mode)
        except Exception as e1:
            err = str(e1).lower()
            if "unsupported parameter" in err and "temperature" in err:
                payload = {k: v for k, v in base_payload.items() if k != "temperature"}
                try:
                    response = _do_call(payload, with_json_mode=use_json_mode)
                    warnings.append("LLM dropped temperature parameter (unsupported).")
                except Exception as e2:
                    err2 = str(e2).lower()
                    if "response_format" in err2 or "json_object" in err2 or "not supported" in err2:
                        response = _do_call(payload, with_json_mode=False)
                        warnings.append("LLM dropped temperature + json_mode (unsupported).")
                    else:
                        warnings.append(f"LLM retry failed: {e2}")
                        return None, debug
            elif "response_format" in err or "json_object" in err or "not supported" in err:
                response = _do_call(base_payload, with_json_mode=False)
                warnings.append("LLM dropped json_mode (unsupported).")
            else:
                warnings.append(f"LLM call failed: {e1}")
                return None, debug

        if not hasattr(response, "choices") or not response.choices:
            warnings.append("LLM returned empty choices array.")
            return None, debug
        text = response.choices[0].message.content
        if not text:
            warnings.append("LLM returned empty content.")
            return None, debug
        return text, debug
    except Exception as exc:
        warnings.append(f"LLM unexpected error: {exc}")
        return None, debug


def _validate_and_normalize(
    parsed: Dict[str, Any],
    topic: str,
    language: str,
    warnings: List[str],
) -> Dict[str, Any]:
    """Coerce LLM output into the canonical v0.5.4 shape.

    Missing keys are filled with deterministic placeholders; type errors are
    rewritten to safe defaults. The result is always a complete object the
    asset writers can consume.
    """
    if not isinstance(parsed, dict):
        warnings.append("LLM JSON was not an object; using fallback structure.")
        parsed = {}

    # topic_analysis
    ta = parsed.get("topic_analysis")
    if not isinstance(ta, dict):
        ta = {}
        warnings.append("topic_analysis missing/invalid; coerced to default.")
    ta.setdefault("topic", topic)
    ta.setdefault("normalized_topic", topic)
    ta.setdefault("content_type", "general_explanation")
    ta.setdefault("difficulty", "medium")
    ta.setdefault("core_concept", topic)
    ta.setdefault("target_audience", "students, parents, short-video viewers")
    ta.setdefault("video_goal", "Explain the topic clearly in 50-60 seconds.")
    if not isinstance(ta.get("risk_points"), list):
        ta["risk_points"] = ["Avoid wrong answer", "Avoid mismatched visuals"]
    if not isinstance(ta.get("visual_requirements"), list):
        ta["visual_requirements"] = [
            "white background",
            "clean line-art educational visuals",
            "large readable on-screen text",
        ]
    ta.setdefault("language", language)

    # reasoning
    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {}
        warnings.append("reasoning missing/invalid; coerced to default.")
    is_zh = str(language).lower().startswith("zh")
    if is_zh:
        reasoning.setdefault("correct_answer", "需要人工核对。")
        if not isinstance(reasoning.get("step_by_step_reasoning"), list):
            reasoning["step_by_step_reasoning"] = [
                "第 1 步:明确问题的精确含义。",
                "第 2 步:找出关键的约束条件。",
                "第 3 步:套用相关原理推导。",
                "第 4 步:得出答案并复核。",
            ]
        reasoning.setdefault(
            "common_wrong_intuition",
            "很多人会凭直觉给出表面答案,而忽略关键约束。",
        )
        reasoning.setdefault(
            "key_teaching_point",
            "回答前先确认约束条件,慢一点再下结论。",
        )
        reasoning.setdefault(
            "accuracy_notes",
            "需要人工复核:本资产包未经过任何视频 provider 端的内容校验。",
        )
    else:
        reasoning.setdefault("correct_answer", "Human review required.")
        if not isinstance(reasoning.get("step_by_step_reasoning"), list):
            reasoning["step_by_step_reasoning"] = [
                "Step 1: Define the question precisely.",
                "Step 2: Identify the key constraint.",
                "Step 3: Apply the relevant principle.",
                "Step 4: Derive the answer and double-check.",
            ]
        reasoning.setdefault(
            "common_wrong_intuition",
            "Many viewers will jump to a surface-level guess without checking the constraint.",
        )
        reasoning.setdefault(
            "key_teaching_point",
            "Slow down and verify the constraint before answering.",
        )
        reasoning.setdefault(
            "accuracy_notes",
            "Human review required: this asset bundle was produced without provider-side verification.",
        )

    # script
    script = parsed.get("script")
    if not isinstance(script, dict):
        script = {}
        warnings.append("script missing/invalid; coerced to default.")
    if is_zh:
        script.setdefault("hook", f"关于「{topic}」,有一个出乎意料的点。")
        script.setdefault(
            "narration",
            f"单一旁白讲解「{topic}」:先抛出问题,逐步推理,最后揭示答案并配合清晰的视觉演示。",
        )
        if not isinstance(script.get("on_screen_text"), list):
            script["on_screen_text"] = [topic, "问题", "答案", "为什么?"]
        if not isinstance(script.get("timing_plan"), list):
            script["timing_plan"] = [
                "0-5 秒 钩子",
                "5-15 秒 铺垫",
                "15-30 秒 推理",
                "30-45 秒 揭示答案",
                "45-60 秒 收尾",
            ]
        script.setdefault("ending", "如果觉得有用,关注一下,后续还有类似题目。")
    else:
        script.setdefault("hook", f"Here's something surprising about {topic}.")
        script.setdefault(
            "narration",
            f"Single narrator monologue introducing {topic}, walking through the reasoning, "
            "and revealing the answer with a clean visual proof.",
        )
        if not isinstance(script.get("on_screen_text"), list):
            script["on_screen_text"] = [
                topic,
                "Question",
                "Answer",
                "Why?",
            ]
        if not isinstance(script.get("timing_plan"), list):
            script["timing_plan"] = [
                "0-5s hook",
                "5-15s setup",
                "15-30s reasoning",
                "30-45s reveal",
                "45-60s takeaway",
            ]
        script.setdefault("ending", "Follow for more puzzles like this.")

    # storyboard
    storyboard = parsed.get("storyboard")
    if not isinstance(storyboard, dict):
        storyboard = {}
        warnings.append("storyboard missing/invalid; coerced to default.")
    storyboard.setdefault("duration_seconds", DEFAULT_DURATION_SECONDS)
    storyboard.setdefault("aspect_ratio", DEFAULT_ASPECT_RATIO)
    storyboard.setdefault("style", DEFAULT_STYLE)
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 5:
        warnings.append("storyboard.scenes missing or fewer than 5 entries; using fallback scene list.")
        scenes = _fallback_scenes(topic)
    else:
        cleaned: List[Dict[str, Any]] = []
        for idx, sc in enumerate(scenes, start=1):
            if not isinstance(sc, dict):
                continue
            sc.setdefault("scene_id", idx)
            sc.setdefault("time_range", f"{(idx - 1) * 12}-{idx * 12}s")
            sc.setdefault("visual", "Whiteboard line-art illustration matching the narration.")
            sc.setdefault("narration", "Single narrator explains the next reasoning step.")
            sc.setdefault("on_screen_text", topic if idx == 1 else "")
            cleaned.append(sc)
        scenes = cleaned if cleaned else _fallback_scenes(topic)
    storyboard["scenes"] = scenes
    storyboard["negative_constraints"] = list(NEGATIVE_CONSTRAINTS)

    # provider_prompt
    provider_prompt = parsed.get("provider_prompt")
    if not isinstance(provider_prompt, str) or len(provider_prompt.strip()) < 80:
        warnings.append("provider_prompt missing or too short; using fallback prompt.")
        provider_prompt = _build_fallback_provider_prompt(topic, ta, reasoning, script, scenes)

    # web_copy_placeholder
    web_copy = parsed.get("web_copy_placeholder")
    if not isinstance(web_copy, dict):
        web_copy = {}
    web_copy.setdefault("title", "")
    web_copy.setdefault("description", "")
    if not isinstance(web_copy.get("hashtags"), list):
        web_copy["hashtags"] = []

    return {
        "topic_analysis": ta,
        "reasoning": reasoning,
        "script": script,
        "storyboard": storyboard,
        "provider_prompt": provider_prompt.strip(),
        "web_copy_placeholder": web_copy,
    }


def _fallback_scenes(topic: str) -> List[Dict[str, Any]]:
    return [
        {
            "scene_id": 1,
            "time_range": "0-5s",
            "visual": f"Whiteboard reveals the title '{topic}' with a hand-drawn underline.",
            "narration": f"Here's a quick puzzle about {topic}.",
            "on_screen_text": topic,
            "camera": "static center",
            "notes": "Hook scene; large readable title.",
        },
        {
            "scene_id": 2,
            "time_range": "5-15s",
            "visual": "Hand-drawn diagram introducing the setup of the question.",
            "narration": "Here's the setup, drawn out so you can follow along.",
            "on_screen_text": "Setup",
            "camera": "slow zoom in",
            "notes": "Visual matches the reasoning, no decorative clutter.",
        },
        {
            "scene_id": 3,
            "time_range": "15-30s",
            "visual": "Step-by-step annotations appear next to the diagram, one bullet at a time.",
            "narration": "Single narrator walks through each reasoning step in order.",
            "on_screen_text": "Why?",
            "camera": "static",
            "notes": "Each annotation matches a reasoning step.",
        },
        {
            "scene_id": 4,
            "time_range": "30-45s",
            "visual": "Final answer drawn in a yellow highlight box.",
            "narration": "Here's the answer, and here's why the common intuition misses it.",
            "on_screen_text": "Answer",
            "camera": "static",
            "notes": "Answer must be correct; no unsupported claims.",
        },
        {
            "scene_id": 5,
            "time_range": "45-60s",
            "visual": "Takeaway sentence written large with a hand-drawn underline.",
            "narration": "If this clicked, follow for more puzzles like this.",
            "on_screen_text": "Takeaway",
            "camera": "static",
            "notes": "Ending scene, clear CTA.",
        },
    ]


def _build_fallback_provider_prompt(
    topic: str,
    topic_analysis: Dict[str, Any],
    reasoning: Dict[str, Any],
    script: Dict[str, Any],
    scenes: List[Dict[str, Any]],
) -> str:
    timing = " | ".join(script.get("timing_plan", [])) or "0-5s hook | 5-30s reasoning | 30-60s reveal"
    scene_summary = " | ".join(
        f"{sc.get('time_range', '')}: {sc.get('visual', '')[:80]}"
        for sc in scenes
        if isinstance(sc, dict)
    )
    constraints = ", ".join(NEGATIVE_CONSTRAINTS)
    return (
        f"Generate a 50-60 second 1080p 9:16 24fps educational short video about: {topic}. "
        f"Core concept: {topic_analysis.get('core_concept', topic)}. "
        f"Correct answer: {reasoning.get('correct_answer', 'Human review required.')}. "
        f"Visual style: clean whiteboard line-art educational short video, white background, "
        f"large readable on-screen text, simple hand-drawn diagrams. "
        f"Timing plan: {timing}. "
        f"Storyboard: {scene_summary}. "
        f"Narration constraints: single narrator, monologue narration, "
        f"{constraints}. "
        f"On-screen text must be large, readable, and match the narration. "
        f"Visuals must match the reasoning and contain no irrelevant decoration. "
        f"The final answer shown must be correct."
    )


def _render_reasoning_md(topic: str, reasoning: Dict[str, Any]) -> str:
    steps = reasoning.get("step_by_step_reasoning") or []
    lines = [
        "# Reasoning & Answer Verification",
        "",
        "## Original Topic",
        "",
        str(topic),
        "",
        "## Correct Answer",
        "",
        str(reasoning.get("correct_answer", "")),
        "",
        "## Step-by-step Reasoning",
        "",
    ]
    if steps:
        for idx, step in enumerate(steps, start=1):
            lines.append(f"{idx}. {step}")
    else:
        lines.append("_(no step-by-step reasoning provided)_")
    lines.extend([
        "",
        "## Common Wrong Intuition",
        "",
        str(reasoning.get("common_wrong_intuition", "")),
        "",
        "## Key Teaching Point",
        "",
        str(reasoning.get("key_teaching_point", "")),
        "",
        "## Accuracy Notes",
        "",
        str(reasoning.get("accuracy_notes", "")),
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _render_video_script_md(topic: str, script: Dict[str, Any], storyboard: Dict[str, Any]) -> str:
    lines = [
        f"# Video Script - {topic}",
        "",
        "## Hook",
        "",
        str(script.get("hook", "")),
        "",
        "## Narration",
        "",
        str(script.get("narration", "")),
        "",
        "## On-screen text",
        "",
    ]
    for ost in script.get("on_screen_text", []) or []:
        lines.append(f"- {ost}")
    lines.extend(["", "## Timing plan", ""])
    for t in script.get("timing_plan", []) or []:
        lines.append(f"- {t}")
    lines.extend(["", "## Ending", "", str(script.get("ending", "")), "", "## Storyboard summary", ""])
    for sc in storyboard.get("scenes", []) or []:
        lines.append(
            f"- Scene {sc.get('scene_id', '?')} ({sc.get('time_range', '')}): "
            f"{sc.get('visual', '')} | OST: {sc.get('on_screen_text', '')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_design_summary_cn(topic: str, ta: Dict[str, Any], reasoning: Dict[str, Any]) -> str:
    """Brief Chinese-language design overview shown in the Video Mode Overview tab."""
    audience = ta.get("target_audience", "短视频观众")
    risk = "、".join(ta.get("risk_points") or []) or "无"
    visual_reqs = "、".join(ta.get("visual_requirements") or []) or "白底线稿"
    return (
        f"主题：{topic}\n"
        f"核心概念：{ta.get('core_concept', topic)}\n"
        f"目标受众：{audience}\n"
        f"视频目标：{ta.get('video_goal', '')}\n"
        f"风险点：{risk}\n"
        f"视觉要求：{visual_reqs}\n"
        f"正确答案：{reasoning.get('correct_answer', '')}\n"
        f"教学要点：{reasoning.get('key_teaching_point', '')}\n"
        f"备注：{reasoning.get('accuracy_notes', '')}"
    )


def _build_provider_request_preview(
    topic: str,
    provider_prompt: str,
    storyboard: Dict[str, Any],
    language: str,
) -> Dict[str, Any]:
    """Future-Seedance contract preview. v0.5.4 NEVER sends this payload.

    Top-level fields mirror what a real Seedance call would expect so the
    v0.6.0 wiring can read this file directly. We deliberately do NOT
    include any real endpoint, API key, Authorization header, or anything
    that could be mistaken for a live submission. ``submit_mode`` stays
    ``not_connected`` and ``real_video_generated`` stays ``false`` for the
    entire v0.5.x line.
    """
    duration = storyboard.get("duration_seconds", DEFAULT_DURATION_SECONDS)
    aspect_ratio = storyboard.get("aspect_ratio", DEFAULT_ASPECT_RATIO)
    style = storyboard.get("style", DEFAULT_STYLE)
    negative_prompt = ", ".join(NEGATIVE_CONSTRAINTS)

    return {
        "provider": PROVIDER_NAME,
        "future_provider": "seedance",
        "model": None,
        "topic": topic,
        "prompt": provider_prompt,
        "duration_seconds": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": DEFAULT_RESOLUTION,
        "fps": DEFAULT_FPS,
        "language": language,
        "style": style,
        "negative_prompt": negative_prompt,
        "submit_mode": "not_connected",
        "provider_status": PROVIDER_STATUS,
        "real_video_generated": False,
        "note": (
            "This is a v0.5.x provider request preview. No real video API is called."
        ),
        # Compatibility nested form retained for any caller that read the
        # earlier shape. Same data, no secrets.
        "request": {
            "topic": topic,
            "prompt": provider_prompt,
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "fps": DEFAULT_FPS,
            "resolution": DEFAULT_RESOLUTION,
            "style": style,
            "negative_constraints": list(NEGATIVE_CONSTRAINTS),
        },
    }


def _safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _save_assets(
    assets_dir: Path,
    topic: str,
    history_id: Optional[int],
    normalized: Dict[str, Any],
    provider_request_preview: Dict[str, Any],
    debug: Dict[str, Any],
    warnings: List[str],
    llm_used: bool,
    llm_raw_text: Optional[str],
) -> Tuple[Dict[str, str], Dict[str, Any], Dict[str, Any]]:
    assets_dir.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, str] = {}

    topic_analysis_path = assets_dir / "topic_analysis.json"
    _safe_write(topic_analysis_path, json.dumps(normalized["topic_analysis"], ensure_ascii=False, indent=2))
    paths["topic_analysis"] = str(topic_analysis_path)

    reasoning_md = _render_reasoning_md(topic, normalized["reasoning"])
    reasoning_path = assets_dir / "reasoning.md"
    _safe_write(reasoning_path, reasoning_md)
    paths["reasoning"] = str(reasoning_path)

    script_md = _render_video_script_md(topic, normalized["script"], normalized["storyboard"])
    script_path = assets_dir / "video_script.md"
    _safe_write(script_path, script_md)
    paths["video_script"] = str(script_path)

    storyboard_path = assets_dir / "storyboard.json"
    _safe_write(storyboard_path, json.dumps(normalized["storyboard"], ensure_ascii=False, indent=2))
    paths["storyboard"] = str(storyboard_path)

    provider_prompt_path = assets_dir / "provider_prompt.txt"
    _safe_write(provider_prompt_path, normalized["provider_prompt"])
    paths["provider_prompt"] = str(provider_prompt_path)

    preview_path = assets_dir / "provider_request_preview.json"
    _safe_write(preview_path, json.dumps(provider_request_preview, ensure_ascii=False, indent=2))
    paths["provider_request_preview"] = str(preview_path)

    # v0.5.6: Seedance prompt compiler — convert the structured assets into
    # a Seedance-shaped prompt + negative prompt + debug payload. The
    # compiler is offline only; no network call is made. The compiled
    # prompt is then handed to the v0.5.5 contract adapter so the Seedance
    # payload preview reflects the compiled prompt instead of the generic
    # provider_prompt.
    from .video_providers.seedance_prompt_compiler import (  # local import to avoid cycle
        SeedancePromptCompiler,
        COMPILER_VERSION as SEEDANCE_COMPILER_VERSION,
        PROFILE_SCHEMA_VERSION as SEEDANCE_PROFILE_SCHEMA_VERSION,
    )

    compiler_warnings: List[str] = []
    seedance_prompt_text = ""
    seedance_negative_prompt = ""
    seedance_prompt_debug: Dict[str, Any] = {}
    compiler_ready = False
    compiler_profile_version = SEEDANCE_PROFILE_SCHEMA_VERSION
    try:
        compiler = SeedancePromptCompiler()
        compiled = compiler.compile_from_assets(
            topic_analysis=normalized.get("topic_analysis"),
            reasoning=normalized.get("reasoning"),
            video_script=normalized.get("script"),
            storyboard=normalized.get("storyboard"),
            provider_request_preview=provider_request_preview,
            topic=topic,
            language=normalized.get("topic_analysis", {}).get("language"),
        )
        seedance_prompt_text = compiled.get("seedance_prompt") or ""
        seedance_negative_prompt = compiled.get("negative_prompt") or ""
        seedance_prompt_debug = compiled.get("seedance_prompt_debug") or {}
        compiler_warnings = list(compiled.get("warnings") or [])
        compiler_profile_version = compiled.get("profile_version") or SEEDANCE_PROFILE_SCHEMA_VERSION
        compiler_ready = bool(seedance_prompt_text.strip())
    except Exception as compiler_exc:
        warnings.append(f"Seedance prompt compiler failed: {compiler_exc}")
        compiler_ready = False

    if compiler_warnings:
        warnings.extend(compiler_warnings)

    seedance_prompt_path = assets_dir / "seedance_prompt.txt"
    _safe_write(seedance_prompt_path, seedance_prompt_text or "")
    paths["seedance_prompt"] = str(seedance_prompt_path)

    seedance_negative_prompt_path = assets_dir / "seedance_negative_prompt.txt"
    _safe_write(seedance_negative_prompt_path, seedance_negative_prompt or "")
    paths["seedance_negative_prompt"] = str(seedance_negative_prompt_path)

    seedance_prompt_debug_path = assets_dir / "seedance_prompt_debug.json"
    _safe_write(
        seedance_prompt_debug_path,
        json.dumps(seedance_prompt_debug or {}, ensure_ascii=False, indent=2),
    )
    paths["seedance_prompt_debug"] = str(seedance_prompt_debug_path)

    # v0.5.5: Seedance contract adapter — validate the request preview, build
    # a future-Seedance payload preview, and emit a canonical lifecycle
    # preview. All three are dry-run only; no network call is made. v0.5.6
    # passes the compiled Seedance prompt + negative prompt so the payload
    # preview reflects the compiler output.
    from .video_providers.seedance_contract_adapter import (  # local import to avoid cycle
        SeedanceContractAdapter,
        PROVIDER_CONTRACT_SCHEMA_VERSION,
    )

    adapter = SeedanceContractAdapter()
    contract_validation = adapter.validate_provider_request_preview(provider_request_preview)
    seedance_payload = adapter.build_seedance_payload_preview(
        provider_request_preview,
        compiled_prompt=seedance_prompt_text or None,
        compiled_negative_prompt=seedance_negative_prompt or None,
        prompt_compiler_version=SEEDANCE_COMPILER_VERSION if compiler_ready else None,
        prompt_source=(
            "video_assets/seedance_prompt.txt" if compiler_ready else "video_assets/provider_prompt.txt"
        ),
        negative_prompt_source=(
            "video_assets/seedance_negative_prompt.txt"
            if compiler_ready
            else "video_assets/provider_request_preview.json#negative_prompt"
        ),
        compiler_ready=compiler_ready,
    )
    lifecycle_preview = adapter.build_lifecycle_preview(provider_request_preview, contract_validation)

    seedance_payload_path = assets_dir / "seedance_payload_preview.json"
    _safe_write(seedance_payload_path, json.dumps(seedance_payload, ensure_ascii=False, indent=2))
    paths["seedance_payload_preview"] = str(seedance_payload_path)

    contract_validation_path = assets_dir / "provider_contract_validation.json"
    _safe_write(contract_validation_path, json.dumps(contract_validation, ensure_ascii=False, indent=2))
    paths["provider_contract_validation"] = str(contract_validation_path)

    lifecycle_preview_path = assets_dir / "provider_lifecycle_preview.json"
    _safe_write(lifecycle_preview_path, json.dumps(lifecycle_preview, ensure_ascii=False, indent=2))
    paths["provider_lifecycle_preview"] = str(lifecycle_preview_path)

    # Register generation_manifest.json BEFORE we serialise the manifest so
    # that manifest.files / manifest.assets include the manifest itself
    # (matches what is on disk and what Download All packages).
    manifest_path = assets_dir / "generation_manifest.json"
    paths["generation_manifest"] = str(manifest_path)

    # Same for llm_raw_output.txt: register the path up-front so the
    # manifest reflects it. The file itself is written below.
    raw_path: Optional[Path] = None
    if llm_raw_text is not None:
        raw_path = assets_dir / "llm_raw_output.txt"
        paths["llm_raw_output"] = str(raw_path)

    manifest = {
        "schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
        "legacy_schema_version": VIDEO_ASSETS_LEGACY_SCHEMA_VERSION,
        "provider_contract_schema_version": PROVIDER_CONTRACT_SCHEMA_VERSION,
        "seedance_prompt_compiler_version": SEEDANCE_COMPILER_VERSION,
        "seedance_prompt_profile_version": compiler_profile_version,
        "generated_at": _utc_now_iso(),
        "topic": topic,
        "history_id": history_id,
        "language": normalized["topic_analysis"].get("language"),
        "provider": PROVIDER_NAME,
        "future_provider": "seedance",
        "provider_status": PROVIDER_STATUS,
        "submit_mode": "not_connected",
        "real_video_generated": False,
        "real_video_downloaded": False,
        "network_call_performed": False,
        "seedance_contract_ready": bool(contract_validation.get("valid")),
        "provider_contract_validation_valid": bool(contract_validation.get("valid")),
        "seedance_prompt_ready": bool(compiler_ready),
        "seedance_prompt_path": "video_assets/seedance_prompt.txt",
        "seedance_negative_prompt_path": "video_assets/seedance_negative_prompt.txt",
        "seedance_prompt_debug_path": "video_assets/seedance_prompt_debug.json",
        "prompt_source_for_seedance_payload": (
            "video_assets/seedance_prompt.txt"
            if compiler_ready
            else "video_assets/provider_prompt.txt"
        ),
        "llm_used": bool(llm_used),
        "fallback_used": not bool(llm_used),
        "llm": {
            "model": debug.get("model"),
            "base_url_configured": debug.get("base_url_configured", False),
            "temperature": debug.get("temperature"),
            "max_tokens": debug.get("max_tokens"),
            "response_format": debug.get("response_format"),
            "api_key_configured": debug.get("api_key_configured", False),
            "config_namespace": debug.get("config_namespace", "AI_VIDEO_LLM_*"),
        },
        "warnings": list(warnings),
        "files": {key: os.path.relpath(value, assets_dir.parent) for key, value in paths.items()},
        "assets": [
            {"key": key, "relative_path": os.path.relpath(value, assets_dir.parent)}
            for key, value in paths.items()
        ],
    }
    _safe_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    if raw_path is not None and llm_raw_text is not None:
        try:
            _safe_write(raw_path, llm_raw_text)
        except Exception:
            # If we cannot write the raw output, drop the entry so the
            # manifest's claim about it stays accurate.
            paths.pop("llm_raw_output", None)

    contract_bundle = {
        "seedance_payload_preview": seedance_payload,
        "provider_contract_validation": contract_validation,
        "provider_lifecycle_preview": lifecycle_preview,
        "seedance_prompt": seedance_prompt_text,
        "seedance_negative_prompt": seedance_negative_prompt,
        "seedance_prompt_debug": seedance_prompt_debug,
        "seedance_prompt_compiler_version": SEEDANCE_COMPILER_VERSION,
        "seedance_prompt_profile_version": compiler_profile_version,
        "seedance_prompt_ready": bool(compiler_ready),
    }
    return paths, manifest, contract_bundle


def build_video_content_assets(
    topic: str,
    output_dir: Path | str,
    history_id: Optional[int] = None,
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate the full v0.5.4 video content asset bundle.

    Always returns a dict with at minimum:
    - ``success`` (bool): True if assets were written, False on hard failure.
    - ``warnings`` (list[str])
    - ``video_assets`` (dict): the normalized content payload.
    - ``provider_prompt`` (str)
    - ``provider_request_preview`` (dict)
    - ``asset_manifest`` (dict)
    - ``asset_paths`` (dict[str, str])
    - ``preview_text`` (str): suitable for the Video Mode Preview tab.
    - ``overview_cn`` (str): suitable for the Video Mode Overview tab.
    - ``llm_used`` (bool)

    On any unexpected exception, falls back to the deterministic synthetic
    asset bundle and returns ``success=False`` with ``warnings`` populated.
    Never raises.
    """
    warnings: List[str] = []
    output_path = Path(output_dir)
    assets_dir = output_path / "video_assets"
    language = _detect_language(topic)
    llm_used = False
    llm_raw_text: Optional[str] = None
    debug: Dict[str, Any] = {}

    try:
        prompt_text = _render_template(topic, language)

        # Note: llm_client is a forward-compatibility hook so callers can
        # inject a fake client for tests; v0.5.4 ignores it and goes through
        # the env-driven OpenAI client path.
        _ = llm_client
        raw_text, debug = _call_llm(prompt_text, warnings)
        parsed: Optional[Dict[str, Any]] = None
        if raw_text:
            llm_raw_text = raw_text
            parsed = _extract_json(raw_text)
            if parsed is None:
                warnings.append("LLM JSON parse failed; using fallback structure.")
            else:
                llm_used = True

        normalized = _validate_and_normalize(parsed or {}, topic, language, warnings)
        provider_request_preview = _build_provider_request_preview(
            topic, normalized["provider_prompt"], normalized["storyboard"], language,
        )

        paths, manifest, contract_bundle = _save_assets(
            assets_dir=assets_dir,
            topic=topic,
            history_id=history_id,
            normalized=normalized,
            provider_request_preview=provider_request_preview,
            debug=debug,
            warnings=warnings,
            llm_used=llm_used,
            llm_raw_text=llm_raw_text,
        )

        preview_text = _render_video_script_md(topic, normalized["script"], normalized["storyboard"])
        overview_cn = _build_design_summary_cn(topic, normalized["topic_analysis"], normalized["reasoning"])

        return {
            "success": True,
            "warnings": warnings,
            "video_assets": normalized,
            "provider_prompt": normalized["provider_prompt"],
            "provider_request_preview": provider_request_preview,
            "seedance_payload_preview": contract_bundle["seedance_payload_preview"],
            "provider_contract_validation": contract_bundle["provider_contract_validation"],
            "provider_lifecycle_preview": contract_bundle["provider_lifecycle_preview"],
            "seedance_prompt": contract_bundle.get("seedance_prompt", ""),
            "seedance_negative_prompt": contract_bundle.get("seedance_negative_prompt", ""),
            "seedance_prompt_debug": contract_bundle.get("seedance_prompt_debug", {}),
            "seedance_prompt_compiler_version": contract_bundle.get(
                "seedance_prompt_compiler_version"
            ),
            "seedance_prompt_profile_version": contract_bundle.get(
                "seedance_prompt_profile_version"
            ),
            "seedance_prompt_ready": bool(contract_bundle.get("seedance_prompt_ready")),
            "asset_manifest": manifest,
            "asset_paths": paths,
            "assets_dir": str(assets_dir),
            "preview_text": preview_text,
            "overview_cn": overview_cn,
            "llm_used": llm_used,
            "schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
        }
    except Exception as exc:
        warnings.append(f"Pipeline hard failure: {exc}")
        traceback.print_exc(file=sys.stderr)
        # Last-resort fallback: try to write at least a minimal manifest so
        # the response can still surface what happened.
        try:
            normalized = _validate_and_normalize({}, topic, language, warnings)
            provider_request_preview = _build_provider_request_preview(
                topic, normalized["provider_prompt"], normalized["storyboard"], language,
            )
            paths, manifest, contract_bundle = _save_assets(
                assets_dir=assets_dir,
                topic=topic,
                history_id=history_id,
                normalized=normalized,
                provider_request_preview=provider_request_preview,
                debug=debug,
                warnings=warnings,
                llm_used=False,
                llm_raw_text=llm_raw_text,
            )
            preview_text = _render_video_script_md(topic, normalized["script"], normalized["storyboard"])
            overview_cn = _build_design_summary_cn(topic, normalized["topic_analysis"], normalized["reasoning"])
            return {
                "success": False,
                "warnings": warnings,
                "video_assets": normalized,
                "provider_prompt": normalized["provider_prompt"],
                "provider_request_preview": provider_request_preview,
                "seedance_payload_preview": contract_bundle["seedance_payload_preview"],
                "provider_contract_validation": contract_bundle["provider_contract_validation"],
                "provider_lifecycle_preview": contract_bundle["provider_lifecycle_preview"],
                "seedance_prompt": contract_bundle.get("seedance_prompt", ""),
                "seedance_negative_prompt": contract_bundle.get("seedance_negative_prompt", ""),
                "seedance_prompt_debug": contract_bundle.get("seedance_prompt_debug", {}),
                "seedance_prompt_compiler_version": contract_bundle.get(
                    "seedance_prompt_compiler_version"
                ),
                "seedance_prompt_profile_version": contract_bundle.get(
                    "seedance_prompt_profile_version"
                ),
                "seedance_prompt_ready": bool(contract_bundle.get("seedance_prompt_ready")),
                "asset_manifest": manifest,
                "asset_paths": paths,
                "assets_dir": str(assets_dir),
                "preview_text": preview_text,
                "overview_cn": overview_cn,
                "llm_used": False,
                "schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
            }
        except Exception as final_exc:
            warnings.append(f"Pipeline catastrophic failure: {final_exc}")
            return {
                "success": False,
                "warnings": warnings,
                "video_assets": None,
                "provider_prompt": "",
                "provider_request_preview": None,
                "seedance_payload_preview": None,
                "provider_contract_validation": None,
                "provider_lifecycle_preview": None,
                "seedance_prompt": "",
                "seedance_negative_prompt": "",
                "seedance_prompt_debug": {},
                "seedance_prompt_compiler_version": None,
                "seedance_prompt_profile_version": None,
                "seedance_prompt_ready": False,
                "asset_manifest": None,
                "asset_paths": {},
                "assets_dir": str(assets_dir),
                "preview_text": "",
                "overview_cn": "",
                "llm_used": False,
                "schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
            }


def _load_dotenv_for_cli() -> bool:
    """Best-effort load of project-root .env when running as a CLI script.

    Returns True if a .env file was found and loaded. Never prints the API
    key. Silent if python-dotenv is missing — env vars from the parent
    process still apply.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return False
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path)
        return True
    except Exception:
        return False


def main() -> int:
    """Tiny CLI for local self-testing. Never prints API key contents."""
    if len(sys.argv) < 2:
        print("Usage: python -m web.video_asset_pipeline <topic> [output_dir]")
        return 1
    topic = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else (PROJECT_ROOT / "outputs" / "_pipeline_smoke")
    env_loaded = _load_dotenv_for_cli()
    api_key, source = _resolve_api_key()
    base_url = os.getenv("AI_VIDEO_LLM_BASE_URL", "")
    model = os.getenv("AI_VIDEO_LLM_MODEL", "gpt-5-chat")
    print(f".env exists: {env_loaded}")
    print(f"AI_VIDEO_LLM_API_KEY configured: {bool(api_key)}")
    print(f"AI_VIDEO_LLM_BASE_URL configured: {bool(base_url)}")
    print(f"current model: {model}")
    result = build_video_content_assets(topic=topic, output_dir=out, history_id=None)
    print(f"LLM path used: {'real LLM' if result.get('llm_used') else 'fallback'}")
    print(json.dumps({
        "success": result["success"],
        "llm_used": result["llm_used"],
        "warnings": result["warnings"],
        "assets_dir": result["assets_dir"],
        "files": result.get("asset_paths"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
