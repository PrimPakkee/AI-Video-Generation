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


VIDEO_ASSETS_SCHEMA_VERSION = "video_assets_v0.6.0"
VIDEO_ASSETS_LEGACY_SCHEMA_VERSION = "video_assets_v0.5.6"
# v0.6.0 duration sync: APX_VIDEO_DURATION is the single source of truth for
# Video Mode duration. The legacy 60s default is only a last-resort fallback;
# resolve_target_duration_seconds() should always be used in practice.
DEFAULT_DURATION_SECONDS = 5
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


# v0.6.0 — duration sync helpers ---------------------------------------------

def resolve_target_duration_seconds(raw: Any = None, default: int = 5) -> int:
    """Single source of truth for Video Mode duration.

    Priority: explicit ``raw`` arg → ``APX_VIDEO_DURATION`` env → ``default``.
    Always returns a clean int; illegal values fall back to ``default``.
    Values < 3 are normalised to 5 (APX rejects shorter clips). Values > 120
    are clamped to 60 to avoid prompt bloat.
    """
    candidate: Any = raw
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = os.environ.get("APX_VIDEO_DURATION")
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = default
    try:
        value = int(str(candidate).strip())
    except Exception:
        value = default
    if value < 3:
        return 5
    if value > 120:
        return 60
    return value


def build_duration_profile(duration_seconds: int) -> Dict[str, Any]:
    """Return the recommended scene/word-count strategy for a given duration."""
    d = int(duration_seconds or 5)
    if d <= 10:
        return {
            "profile_name": "smoke_ultra_short",
            "duration_seconds": d,
            "scene_count_min": 2,
            "scene_count_max": 3,
            "word_count_min": 12,
            "word_count_max": 35,
            "instruction": (
                "Ultra-short smoke-test video. Focus on one visual hook and one "
                "answer. Do not write a full 60-second explanation."
            ),
        }
    if d <= 20:
        return {
            "profile_name": "quick_answer",
            "duration_seconds": d,
            "scene_count_min": 3,
            "scene_count_max": 4,
            "word_count_min": 35,
            "word_count_max": 70,
            "instruction": "Quick short video. Hook, one compact reasoning step, answer.",
        }
    if d <= 35:
        return {
            "profile_name": "standard_short",
            "duration_seconds": d,
            "scene_count_min": 5,
            "scene_count_max": 6,
            "word_count_min": 70,
            "word_count_max": 120,
            "instruction": "Standard short video. Full but compressed reasoning.",
        }
    if d <= 60:
        return {
            "profile_name": "full_explanation",
            "duration_seconds": d,
            "scene_count_min": 6,
            "scene_count_max": 9,
            "word_count_min": 120,
            "word_count_max": 190,
            "instruction": (
                "Full educational short. Hook, setup, reasoning, answer reveal, takeaway."
            ),
        }
    return {
        "profile_name": "extended_explanation",
        "duration_seconds": d,
        "scene_count_min": 8,
        "scene_count_max": 12,
        "word_count_min": 180,
        "word_count_max": 280,
        "instruction": (
            "Extended educational video. Keep visual structure clear and avoid "
            "overloading the video model."
        ),
    }


# v0.6.0 — duration hardening helpers ----------------------------------------

_LEGACY_DURATION_PATTERNS = [
    (re.compile(r"50\s*[-–]\s*60\s*seconds", re.IGNORECASE), "{d}-second"),
    (re.compile(r"50\s*[-–]\s*60\s*second", re.IGNORECASE), "{d}-second"),
    (re.compile(r"60\s*[-–]\s*second", re.IGNORECASE), "{d}-second"),
    (re.compile(r"\b60\s*seconds\b", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"\b60\s*sec\b", re.IGNORECASE), "{d} sec"),
    (re.compile(r"\bone\s*minute\b", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"\ba\s*minute\b", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"50\s*[-–]\s*60\s*秒"), "{d} 秒"),
    (re.compile(r"60\s*秒"), "{d} 秒"),
    (re.compile(r"一分钟"), "{d} 秒"),
]


def _sync_duration_text(text: Any, target_duration_seconds: int) -> str:
    """Replace legacy 50–60 / 60-second / one-minute phrasing with the target."""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    d = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    for pattern, replacement in _LEGACY_DURATION_PATTERNS:
        s = pattern.sub(replacement.format(d=d), s)
    return s


_TIME_RANGE_PATTERN = re.compile(
    r"(\d+)\s*[-–]\s*(\d+)\s*(?:s|sec|seconds|秒)", re.IGNORECASE
)


def _timing_plan_exceeds_duration(
    timing_plan: Any, target_duration_seconds: int
) -> bool:
    """True iff timing_plan is missing/invalid or its end times overshoot target."""
    if not isinstance(timing_plan, list):
        return True
    d = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    if d <= 10 and len(timing_plan) > 4:
        return True
    if d <= 20 and len(timing_plan) > 5:
        return True
    parsed_any = False
    for item in timing_plan:
        if not isinstance(item, str):
            continue
        m = _TIME_RANGE_PATTERN.search(item)
        if not m:
            continue
        parsed_any = True
        try:
            end_t = int(m.group(2))
        except Exception:
            continue
        if end_t > d:
            return True
    if not parsed_any:
        return False
    return False


def _assign_scene_time_ranges(
    scenes: List[Dict[str, Any]],
    target_duration_seconds: int,
) -> List[Dict[str, Any]]:
    """Force every scene's time_range onto a contiguous 0..target schedule."""
    d = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    cleaned: List[Dict[str, Any]] = []
    for sc in scenes:
        if isinstance(sc, dict):
            cleaned.append(dict(sc))
    n = len(cleaned)
    if n == 0:
        return cleaned
    per = max(1, d // n)
    for idx, sc in enumerate(cleaned, start=1):
        start_t = (idx - 1) * per
        end_t = idx * per if idx < n else d
        if start_t >= d:
            start_t = max(0, d - 1)
        if end_t > d:
            end_t = d
        sc["scene_id"] = sc.get("scene_id", idx)
        sc["time_range"] = f"{start_t}-{end_t}s"
    return cleaned


def _sync_provider_prompt_duration(
    provider_prompt: Any, target_duration_seconds: int
) -> str:
    """Strip legacy 50–60 wording and append a single Mandatory-duration line."""
    d = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    s = _sync_duration_text(provider_prompt, d).strip()
    if not s:
        return s
    mandatory_re = re.compile(
        r"Mandatory duration:\s*\d+\s*seconds\.\s*Ignore any conflicting duration instruction\.?",
        re.IGNORECASE,
    )
    s = mandatory_re.sub("", s).strip()
    suffix = f"Mandatory duration: {d} seconds. Ignore any conflicting duration instruction."
    if not s.endswith("."):
        s += "."
    return s + " " + suffix


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


def _render_template(
    topic: str,
    language: str,
    target_duration_seconds: int,
    duration_profile: Dict[str, Any],
) -> str:
    duration_str = str(int(target_duration_seconds))
    profile_name = str(duration_profile.get("profile_name", ""))
    scene_min = str(int(duration_profile.get("scene_count_min", 5)))
    scene_max = str(int(duration_profile.get("scene_count_max", 6)))
    word_min = str(int(duration_profile.get("word_count_min", 70)))
    word_max = str(int(duration_profile.get("word_count_max", 120)))
    instruction = str(duration_profile.get("instruction", ""))

    template = _read_template()
    if not template:
        return (
            "Generate a strict JSON content asset for an educational short "
            "video on the topic below. Output JSON only, no commentary.\n\n"
            f"Topic: {topic}\n"
            f"Language: {language}\n"
            f"Target duration: {duration_str} seconds (single source of truth)\n"
            f"Duration profile: {profile_name}\n"
            f"Recommended scene count: {scene_min}-{scene_max}\n"
            f"Recommended narration word count: {word_min}-{word_max}\n"
            f"Duration strategy: {instruction}\n"
            f"Aspect Ratio: {DEFAULT_ASPECT_RATIO}\n"
            f"Style: {DEFAULT_STYLE}\n"
        )
    return (
        template
        .replace("{{TOPIC}}", topic)
        .replace("{{LANGUAGE}}", language)
        .replace("{{DURATION_SECONDS}}", duration_str)
        .replace("{{DURATION_PROFILE_NAME}}", profile_name)
        .replace("{{SCENE_COUNT_MIN}}", scene_min)
        .replace("{{SCENE_COUNT_MAX}}", scene_max)
        .replace("{{WORD_COUNT_MIN}}", word_min)
        .replace("{{WORD_COUNT_MAX}}", word_max)
        .replace("{{DURATION_STRATEGY_INSTRUCTION}}", instruction)
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
    target_duration_seconds: int = DEFAULT_DURATION_SECONDS,
    duration_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Coerce LLM output into the canonical v0.5.4 shape.

    Missing keys are filled with deterministic placeholders; type errors are
    rewritten to safe defaults. The result is always a complete object the
    asset writers can consume.
    """
    if not isinstance(parsed, dict):
        warnings.append("LLM JSON was not an object; using fallback structure.")
        parsed = {}

    target_duration = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    if duration_profile is None:
        duration_profile = build_duration_profile(target_duration)

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
    ta.setdefault(
        "video_goal",
        f"Explain the topic clearly in a {target_duration}-second educational short video.",
    )
    # Strip legacy 50–60s phrasing if the LLM (or a stale fallback) supplied it.
    if isinstance(ta.get("video_goal"), str):
        ta["video_goal"] = _sync_duration_text(ta["video_goal"], target_duration)
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
        if _timing_plan_exceeds_duration(script.get("timing_plan"), target_duration):
            if isinstance(script.get("timing_plan"), list) and script["timing_plan"]:
                warnings.append("script.timing_plan normalized to target duration.")
            script["timing_plan"] = _build_fallback_timing_plan(target_duration, language)
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
        if _timing_plan_exceeds_duration(script.get("timing_plan"), target_duration):
            if isinstance(script.get("timing_plan"), list) and script["timing_plan"]:
                warnings.append("script.timing_plan normalized to target duration.")
            script["timing_plan"] = _build_fallback_timing_plan(target_duration, language)
        script.setdefault("ending", "Follow for more puzzles like this.")

    # Strip legacy 50–60s phrasing from any LLM-supplied narration / ending.
    if isinstance(script.get("narration"), str):
        script["narration"] = _sync_duration_text(script["narration"], target_duration)
    if isinstance(script.get("ending"), str):
        script["ending"] = _sync_duration_text(script["ending"], target_duration)

    # storyboard
    storyboard = parsed.get("storyboard")
    if not isinstance(storyboard, dict):
        storyboard = {}
        warnings.append("storyboard missing/invalid; coerced to default.")
    existing_duration = storyboard.get("duration_seconds")
    if existing_duration is not None:
        try:
            existing_int = int(existing_duration)
        except Exception:
            existing_int = None
        if existing_int is not None and existing_int != target_duration:
            warnings.append(
                "storyboard.duration_seconds normalized to target duration."
            )
    storyboard["duration_seconds"] = target_duration
    storyboard.setdefault("aspect_ratio", DEFAULT_ASPECT_RATIO)
    storyboard.setdefault("style", DEFAULT_STYLE)
    scene_min = int(duration_profile.get("scene_count_min", 5))
    scene_max = int(duration_profile.get("scene_count_max", 6))
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < scene_min:
        warnings.append(
            f"storyboard.scenes missing or fewer than {scene_min} entries; using fallback scene list."
        )
        scenes = _fallback_scenes(topic, target_duration, language)
    else:
        overshoot = False
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            tr = sc.get("time_range")
            if not isinstance(tr, str):
                continue
            m = _TIME_RANGE_PATTERN.search(tr)
            if m:
                try:
                    if int(m.group(2)) > target_duration:
                        overshoot = True
                        break
                except (TypeError, ValueError):
                    continue
        cleaned_input: List[Dict[str, Any]] = [sc for sc in scenes if isinstance(sc, dict)]
        if not cleaned_input:
            scenes = _fallback_scenes(topic, target_duration, language)
        else:
            scenes = _assign_scene_time_ranges(cleaned_input, target_duration)
            for idx, sc in enumerate(scenes, start=1):
                sc.setdefault("scene_id", idx)
                sc.setdefault("visual", "Whiteboard line-art illustration matching the narration.")
                sc.setdefault("narration", "Single narrator explains the next reasoning step.")
                sc.setdefault("on_screen_text", topic if idx == 1 else "")
        if overshoot:
            warnings.append("storyboard.scene time_range normalized to target duration.")
        if len(scenes) > scene_max:
            warnings.append(
                f"storyboard.scenes count {len(scenes)} exceeds profile max {scene_max} "
                f"for duration {target_duration}s."
            )
    storyboard["scenes"] = scenes
    storyboard["negative_constraints"] = list(NEGATIVE_CONSTRAINTS)

    # provider_prompt
    provider_prompt = parsed.get("provider_prompt")
    if not isinstance(provider_prompt, str) or len(provider_prompt.strip()) < 80:
        warnings.append("provider_prompt missing or too short; using fallback prompt.")
        provider_prompt = _build_fallback_provider_prompt(
            topic, ta, reasoning, script, scenes, target_duration
        )
    provider_prompt = _sync_provider_prompt_duration(provider_prompt, target_duration)

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


def _build_fallback_timing_plan(duration_seconds: int, language: str) -> List[str]:
    """Deterministic timing plan that always sums to duration_seconds."""
    d = int(duration_seconds or DEFAULT_DURATION_SECONDS)
    is_zh = str(language).lower().startswith("zh")
    if d <= 10:
        if is_zh:
            return [f"0-{max(1, d // 2)} 秒 钩子+问题", f"{max(1, d // 2)}-{d} 秒 答案+收尾"]
        return [f"0-{max(1, d // 2)}s hook+question", f"{max(1, d // 2)}-{d}s answer+takeaway"]
    if d <= 20:
        a = max(1, d // 4)
        b = max(a + 1, (d * 3) // 4)
        if is_zh:
            return [f"0-{a} 秒 钩子", f"{a}-{b} 秒 推理", f"{b}-{d} 秒 揭示"]
        return [f"0-{a}s hook", f"{a}-{b}s reasoning", f"{b}-{d}s reveal"]
    if d <= 35:
        if is_zh:
            return [
                f"0-{max(2, d // 8)} 秒 钩子",
                f"{max(2, d // 8)}-{d // 3} 秒 铺垫",
                f"{d // 3}-{(2 * d) // 3} 秒 推理",
                f"{(2 * d) // 3}-{(5 * d) // 6} 秒 揭示",
                f"{(5 * d) // 6}-{d} 秒 收尾",
            ]
        return [
            f"0-{max(2, d // 8)}s hook",
            f"{max(2, d // 8)}-{d // 3}s setup",
            f"{d // 3}-{(2 * d) // 3}s reasoning",
            f"{(2 * d) // 3}-{(5 * d) // 6}s reveal",
            f"{(5 * d) // 6}-{d}s takeaway",
        ]
    if d <= 60:
        if is_zh:
            return [
                "0-5 秒 钩子",
                f"5-{d // 4} 秒 铺垫",
                f"{d // 4}-{d // 2} 秒 推理",
                f"{d // 2}-{(3 * d) // 4} 秒 揭示",
                f"{(3 * d) // 4}-{d} 秒 收尾",
            ]
        return [
            "0-5s hook",
            f"5-{d // 4}s setup",
            f"{d // 4}-{d // 2}s reasoning",
            f"{d // 2}-{(3 * d) // 4}s reveal",
            f"{(3 * d) // 4}-{d}s takeaway",
        ]
    if is_zh:
        return [
            "0-5 秒 钩子",
            f"5-{d // 5} 秒 铺垫",
            f"{d // 5}-{(2 * d) // 5} 秒 推理上",
            f"{(2 * d) // 5}-{(3 * d) // 5} 秒 推理下",
            f"{(3 * d) // 5}-{(4 * d) // 5} 秒 揭示",
            f"{(4 * d) // 5}-{d} 秒 收尾",
        ]
    return [
        "0-5s hook",
        f"5-{d // 5}s setup",
        f"{d // 5}-{(2 * d) // 5}s reasoning a",
        f"{(2 * d) // 5}-{(3 * d) // 5}s reasoning b",
        f"{(3 * d) // 5}-{(4 * d) // 5}s reveal",
        f"{(4 * d) // 5}-{d}s takeaway",
    ]


def _fallback_scenes(
    topic: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    language: str = "en",
) -> List[Dict[str, Any]]:
    d = int(duration_seconds or DEFAULT_DURATION_SECONDS)
    profile = build_duration_profile(d)
    scene_count = max(int(profile.get("scene_count_min", 2)), 2)
    is_zh = str(language).lower().startswith("zh")

    if scene_count == 2:
        labels = [
            ("Hook+Question" if not is_zh else "钩子+问题", topic, "Hook scene; large readable title."),
            ("Answer" if not is_zh else "答案", "Answer", "Final answer; correct, no unsupported claims."),
        ]
    elif scene_count == 3:
        labels = [
            ("Hook" if not is_zh else "钩子", topic, "Hook scene."),
            ("Reasoning" if not is_zh else "推理", "Why?", "Single narrator walks through reasoning."),
            ("Answer" if not is_zh else "答案", "Answer", "Answer + takeaway."),
        ]
    else:
        base = [
            ("Hook" if not is_zh else "钩子", topic),
            ("Setup" if not is_zh else "铺垫", "Setup"),
            ("Reasoning" if not is_zh else "推理", "Why?"),
            ("Reveal" if not is_zh else "揭示", "Answer"),
            ("Takeaway" if not is_zh else "收尾", "Takeaway"),
        ]
        if scene_count > 5:
            extra = [(f"Reasoning {i}" if not is_zh else f"推理 {i}", "Why?") for i in range(2, scene_count - 3)]
            base = base[:3] + extra + base[3:]
        base = base[:scene_count]
        labels = [(name, ost, "Scene matches reasoning, no decorative clutter.") for name, ost in base]

    per_scene = max(1, d // scene_count)
    scenes: List[Dict[str, Any]] = []
    for idx, (label, ost, *rest) in enumerate(labels, start=1):
        start_t = (idx - 1) * per_scene
        end_t = idx * per_scene if idx < scene_count else d
        notes = rest[0] if rest else "Scene matches reasoning."
        scenes.append({
            "scene_id": idx,
            "time_range": f"{start_t}-{end_t}s",
            "visual": (
                f"Whiteboard reveals the title '{topic}'." if idx == 1
                else "Whiteboard line-art illustration matching the narration."
            ),
            "narration": (
                f"Here's a quick puzzle about {topic}." if idx == 1
                else "Single narrator explains the next reasoning step."
            ),
            "on_screen_text": ost,
            "camera": "static" if idx != 1 else "static center",
            "notes": notes,
        })
    return scenes


def _build_fallback_provider_prompt(
    topic: str,
    topic_analysis: Dict[str, Any],
    reasoning: Dict[str, Any],
    script: Dict[str, Any],
    scenes: List[Dict[str, Any]],
    target_duration_seconds: int = DEFAULT_DURATION_SECONDS,
) -> str:
    timing = " | ".join(script.get("timing_plan", [])) or "0-5s hook | reasoning | reveal"
    scene_summary = " | ".join(
        f"{sc.get('time_range', '')}: {sc.get('visual', '')[:80]}"
        for sc in scenes
        if isinstance(sc, dict)
    )
    constraints = ", ".join(NEGATIVE_CONSTRAINTS)
    return (
        f"Generate a {int(target_duration_seconds)} second 1080p 9:16 24fps educational short video about: {topic}. "
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
    target_duration_seconds: int = DEFAULT_DURATION_SECONDS,
    duration_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Future-Seedance contract preview. v0.5.4 NEVER sends this payload.

    Top-level fields mirror what a real Seedance call would expect so the
    v0.6.0 wiring can read this file directly. We deliberately do NOT
    include any real endpoint, API key, Authorization header, or anything
    that could be mistaken for a live submission. ``submit_mode`` stays
    ``not_connected`` and ``real_video_generated`` stays ``false`` for the
    entire v0.5.x line.
    """
    duration = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    aspect_ratio = storyboard.get("aspect_ratio", DEFAULT_ASPECT_RATIO)
    style = storyboard.get("style", DEFAULT_STYLE)
    negative_prompt = ", ".join(NEGATIVE_CONSTRAINTS)
    if duration_profile is None:
        duration_profile = build_duration_profile(duration)

    return {
        "provider": PROVIDER_NAME,
        "future_provider": "seedance",
        "model": None,
        "topic": topic,
        "prompt": provider_prompt,
        "duration_seconds": duration,
        "target_duration_seconds": duration,
        "duration_source": "APX_VIDEO_DURATION",
        "duration_profile": duration_profile,
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
            "This is a v0.6.0 provider request preview. No real video API is called."
        ),
        # Compatibility nested form retained for any caller that read the
        # earlier shape. Same data, no secrets.
        "request": {
            "topic": topic,
            "prompt": provider_prompt,
            "duration_seconds": duration,
            "target_duration_seconds": duration,
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
    target_duration_seconds: int = DEFAULT_DURATION_SECONDS,
    duration_profile: Optional[Dict[str, Any]] = None,
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

    if isinstance(seedance_prompt_debug, dict):
        seedance_prompt_debug.setdefault("target_duration_seconds", target_duration_seconds or DEFAULT_DURATION_SECONDS)
        seedance_prompt_debug.setdefault(
            "duration_profile",
            (duration_profile or build_duration_profile(target_duration_seconds or DEFAULT_DURATION_SECONDS)).get("profile_name"),
        )
        pm = seedance_prompt_debug.get("prompt_metrics")
        if isinstance(pm, dict):
            pm["duration_seconds"] = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
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

    target_duration = int(target_duration_seconds or DEFAULT_DURATION_SECONDS)
    if duration_profile is None:
        duration_profile = build_duration_profile(target_duration)

    manifest = {
        "schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
        "legacy_schema_version": VIDEO_ASSETS_LEGACY_SCHEMA_VERSION,
        "target_duration_seconds": target_duration,
        "duration_source": "APX_VIDEO_DURATION",
        "duration_profile": duration_profile.get("profile_name"),
        "duration_synced": True,
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
    target_duration_seconds: Optional[int] = None,
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
    duration_seconds = resolve_target_duration_seconds(target_duration_seconds)
    duration_profile = build_duration_profile(duration_seconds)

    try:
        prompt_text = _render_template(topic, language, duration_seconds, duration_profile)

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

        normalized = _validate_and_normalize(
            parsed or {}, topic, language, warnings,
            target_duration_seconds=duration_seconds,
            duration_profile=duration_profile,
        )
        provider_request_preview = _build_provider_request_preview(
            topic, normalized["provider_prompt"], normalized["storyboard"], language,
            target_duration_seconds=duration_seconds,
            duration_profile=duration_profile,
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
            target_duration_seconds=duration_seconds,
            duration_profile=duration_profile,
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
            normalized = _validate_and_normalize(
                {}, topic, language, warnings,
                target_duration_seconds=duration_seconds,
                duration_profile=duration_profile,
            )
            provider_request_preview = _build_provider_request_preview(
                topic, normalized["provider_prompt"], normalized["storyboard"], language,
                target_duration_seconds=duration_seconds,
                duration_profile=duration_profile,
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
                target_duration_seconds=duration_seconds,
                duration_profile=duration_profile,
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
