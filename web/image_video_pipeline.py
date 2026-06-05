#!/usr/bin/env python3
"""
Image Video pipeline (v0.6.3) — Static Image Video MVP.

Renders a small set of educational slide PNGs locally with Pillow, then
concatenates them into ``final_video.mp4`` using a system FFmpeg.

This module never calls Seedance, APX, Image2, or TTS. It DOES use the
configured ``AI_VIDEO_LLM_*`` OpenAI-compatible client (typically
gpt-5-chat) to write per-slide English content and a Chinese paragraph
overview tailored to the user's topic. The LLM call is optional — if the
API key is missing, the call fails, or the response is malformed, the
pipeline falls back to a deterministic static template so the video
always renders.

Public API:
    resolve_slide_count(duration_seconds, title=None) -> int
    generate_image_video_package(title, duration_seconds, output_dir,
                                 slug=None) -> dict

The pipeline output layout (relative to ``output_dir``):
    image_video/
        slide_plan.json
        overlay_plan.json
        slides/
            slide_01.png
            slide_02.png
            ...
        concat.txt
        ffmpeg_command.txt
        final_video.mp4
        llm_debug.json          # AI_VIDEO_LLM_* call metadata + raw text
        llm_slide_content.json  # parsed per-slide content from the LLM
        overview_cn.txt         # Chinese paragraph describing the video
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:  # pragma: no cover — Pillow is in requirements.txt
    raise RuntimeError(
        "Pillow is required for the Image Video MVP. "
        "Install it via `pip install Pillow>=10.0.0`."
    ) from exc


IMAGE_VIDEO_PIPELINE_VERSION = "image_video_pipeline_v0.6.3"

ALLOWED_DURATIONS = (5, 15, 30, 60, 90)

# Per-duration slide count ranges. resolve_slide_count() picks a value
# inside the range based on title complexity (length + complex keywords).
DURATION_SLIDE_RANGES: Dict[int, Tuple[int, int]] = {
    5:  (3, 3),
    15: (4, 6),
    30: (6, 8),
    60: (10, 15),
    90: (20, 25),
}

COMPLEX_KEYWORDS = (
    "why", "how", "paradox", "probability", "geometry", "compare",
    "proof", "average", "expected", "ratio", "illusion", "logic",
    "group", "overall", "result", "trick", "puzzle", "fallacy",
    "simpson", "monty", "bayes", "median", "mean",
)

RESOLUTION_W = 1920
RESOLUTION_H = 1080
FPS = 24

# Curated palette for the clean whiteboard look. Hex tuples avoided so the
# Pillow draw calls read clearly.
COLOR_BG = (250, 250, 250)
COLOR_INK = (32, 36, 44)
COLOR_MUTED = (110, 118, 130)
COLOR_ACCENT = (124, 109, 240)
COLOR_ACCENT_SOFT = (235, 232, 254)
COLOR_OK = (61, 159, 102)
COLOR_OK_SOFT = (224, 244, 232)
COLOR_WARN = (212, 109, 76)
COLOR_WARN_SOFT = (252, 232, 224)
COLOR_NEUTRAL_SOFT = (240, 242, 246)


def _slugify(value: str) -> str:
    if not value:
        return "topic"
    out = re.sub(r"[^A-Za-z0-9_\-]+", "_", value).strip("_") or "topic"
    return out[:64]


def _is_chinese(text: str) -> bool:
    if not text:
        return False
    for ch in text:
        if "一" <= ch <= "鿿":
            return True
    return False


def _title_complexity_score(title: Optional[str]) -> float:
    """Return a 0..1 complexity score from the title.

    Used inside duration ranges to nudge slide counts up or down. We never
    return 0 for titles that contain at least one complex keyword, and we
    cap at 1.0 so the lerp into the range stays bounded.
    """
    if not title:
        return 0.5
    text = title.lower()
    chinese = _is_chinese(title)

    if chinese:
        char_len = len(title.strip())
        punct = sum(1 for c in title if c in "?？!！，,。.;；:：、")
        length_score = min(1.0, char_len / 28.0)
        punct_score = min(0.4, punct * 0.1)
        return min(1.0, 0.05 + length_score * 0.7 + punct_score)

    word_count = len([w for w in re.split(r"\s+", text) if w])
    length_score = min(1.0, word_count / 14.0)
    keyword_hits = sum(1 for kw in COMPLEX_KEYWORDS if kw in text)
    keyword_score = min(0.5, keyword_hits * 0.18)
    punct = sum(1 for c in text if c in "?!,.;:")
    punct_score = min(0.2, punct * 0.05)
    return min(1.0, 0.05 + length_score * 0.55 + keyword_score + punct_score)


def resolve_slide_count(
    duration_seconds: int,
    title: Optional[str] = None,
    topic_complexity: Optional[float] = None,
) -> int:
    """Pick a slide count for the given duration based on title complexity.

    Slide-count rules per duration (v0.6.3):
        5s  -> exactly 3
        15s -> 4..6
        30s -> 6..8
        60s -> 10..15
        90s -> 20..25
    """
    if duration_seconds not in DURATION_SLIDE_RANGES:
        raise ValueError(
            f"Unsupported duration_seconds={duration_seconds}. "
            f"Allowed: {ALLOWED_DURATIONS}"
        )
    lo, hi = DURATION_SLIDE_RANGES[duration_seconds]
    if lo == hi:
        return lo
    score = (
        float(topic_complexity)
        if topic_complexity is not None
        else _title_complexity_score(title)
    )
    score = max(0.0, min(1.0, score))
    span = hi - lo
    pick = lo + int(round(score * span))
    return max(lo, min(hi, pick))


def _english_subject(title: str) -> str:
    """Best-effort English subject label for slide overlays.

    For Chinese-only titles we fall back to a neutral "This Topic" label —
    the slide template focuses on structural visuals (cards, arrows, badges)
    rather than dense translation.
    """
    if not title:
        return "This Topic"
    if _is_chinese(title):
        latin = re.sub(r"[^A-Za-z0-9 ?!.,:'\-]+", " ", title).strip()
        if len(latin) >= 4:
            return latin[:60]
        return "This Topic"
    cleaned = re.sub(r"\s+", " ", title).strip()
    return cleaned[:80] if cleaned else "This Topic"


_ROLE_SEQUENCE_SHORT = ("hook", "explanation", "answer")
_ROLE_SEQUENCE_MEDIUM = ("hook", "setup", "explanation", "key_insight", "answer", "takeaway")
_ROLE_SEQUENCE_LONG = (
    "hook", "setup", "misconception", "explanation", "comparison",
    "key_insight", "example", "answer", "recap", "takeaway",
)


def _assign_roles(slide_count: int) -> List[str]:
    if slide_count <= 3:
        return list(_ROLE_SEQUENCE_SHORT[:slide_count]) or ["hook"]
    if slide_count <= 6:
        return list(_ROLE_SEQUENCE_MEDIUM[:slide_count])
    # For long sequences, use the long pattern then pad with explanation/comparison.
    base = list(_ROLE_SEQUENCE_LONG)
    out: List[str] = []
    out.append("hook")
    out.append("setup")
    middle_target = slide_count - 3  # leave room for answer + takeaway at end
    middle_pool = [
        "misconception", "explanation", "comparison", "example",
        "key_insight", "explanation", "comparison", "recap",
    ]
    i = 0
    while len(out) < 2 + middle_target:
        out.append(middle_pool[i % len(middle_pool)])
        i += 1
    out.append("answer")
    out.append("takeaway")
    # Trim if we overshoot; pad if we undershoot.
    if len(out) > slide_count:
        out = out[:slide_count]
    while len(out) < slide_count:
        out.append("explanation")
    # Sanity: keep the curated long template as a guide for short long-runs.
    if slide_count <= len(base):
        out = base[:slide_count]
    return out


# -------------------- LLM-driven slide content --------------------
#
# v0.6.3 update — image_video pipeline calls the configured AI_VIDEO_LLM_*
# OpenAI-compatible model (gpt-5-chat by default) to write per-slide content
# tailored to the user's topic, plus a Chinese paragraph overview. The
# Image Video route never calls Seedance / APX / Image2 / TTS — the LLM
# used here is the same one that already powers the Prompt Mode and
# Seedance Video content asset pipeline, configured via:
#
#   AI_VIDEO_LLM_API_KEY   (primary)
#   AI_VIDEO_LLM_BASE_URL  (default https://api.openai.com/v1)
#   AI_VIDEO_LLM_MODEL     (default gpt-5-chat)
#   AI_VIDEO_LLM_TIMEOUT   (default 60s)
#   AI_VIDEO_LLM_MAX_TOKENS (default 4096)
#   AI_VIDEO_LLM_TEMPERATURE (default 0.6)
#
# The API key is never logged, never written to disk, never returned to
# the frontend. Only ``api_key_configured: bool`` is surfaced in the
# llm_debug.json file.


def _resolve_llm_api_key() -> Tuple[Optional[str], str]:
    primary = os.getenv("AI_VIDEO_LLM_API_KEY")
    if primary and primary.strip() and primary != "put_your_api_key_here":
        return primary, "AI_VIDEO_LLM_API_KEY"
    legacy = os.getenv("OPENAI_API_KEY")
    if legacy and legacy.strip() and legacy != "put_your_api_key_here":
        return legacy, "OPENAI_API_KEY"
    return None, ""


def _build_llm_user_prompt(
    title: str,
    duration_seconds: int,
    slide_count: int,
    roles: List[str],
) -> str:
    """Build the single user message we send to the LLM.

    Asks for one JSON object containing a per-slide list and a Chinese
    paragraph overview. We give the model the role sequence so it knows
    the narrative arc and can write content matching each beat.
    """
    role_lines = "\n".join(
        f"  - slide {i+1} ({role})" for i, role in enumerate(roles)
    )
    return (
        "You are designing a short-form educational explainer video for an\n"
        "audience on TikTok / YouTube Shorts. Visuals are generated locally\n"
        "by a Pillow renderer (no AI image generation). You write the words.\n"
        "\n"
        "Topic (verbatim, may be Chinese):\n"
        f"  {title}\n"
        "\n"
        f"Target duration: {duration_seconds} seconds, {slide_count} slides.\n"
        "Slide narrative arc (in order):\n"
        f"{role_lines}\n"
        "\n"
        "Hard requirements:\n"
        "  1. ALL slide text fields must be written in ENGLISH, even if the\n"
        "     topic is Chinese. The Pillow renderer ships English fonts.\n"
        "  2. The content MUST directly address the user's topic. Do NOT\n"
        "     fall back to generic 'Simpson paradox' filler. If the topic is\n"
        "     about prime numbers, the slides talk about prime numbers.\n"
        "  3. Each slide title <= 7 words. Each caption <= 16 words.\n"
        "     Each highlight <= 8 words. Each visual_focus <= 14 words.\n"
        "  4. The visual_focus describes ONE concrete diagram or symbol the\n"
        "     Pillow renderer should emphasize — e.g. 'two coins side by\n"
        "     side', 'a bar of height 7', 'three dice with faces 1, 2, 3'.\n"
        "     Keep it concrete, no abstract metaphors.\n"
        "  5. image_prompt is a DETAILED English image-generation prompt\n"
        "     (40-90 words) that describes exactly the scene the slide\n"
        "     should show as if you were briefing a designer or an image\n"
        "     generation model: subject, composition, color palette,\n"
        "     background, lighting, perspective, on-screen text layout,\n"
        "     style cues. It MUST stay topic-specific: no generic\n"
        "     'whiteboard' or 'classroom' filler. Style anchor for every\n"
        "     slide: 'clean modern educational explainer, minimal flat\n"
        "     vector illustration, soft pastel palette with one accent\n"
        "     color, generous negative space, 16:9 landscape composition.'\n"
        "     This text will be saved verbatim and later sent to an\n"
        "     image-generation model.\n"
        "  6. The narrative should genuinely teach: hook a question, set up\n"
        "     the problem, walk through real reasoning, deliver an answer\n"
        "     that actually answers the topic, and end with a takeaway the\n"
        "     viewer can repeat in one sentence.\n"
        "  7. Also produce a Chinese paragraph (`overview_cn`) of 4–7\n"
        "     sentences. Write it as flowing prose (no bullet list, no\n"
        "     numbered headings). It should describe what this short video\n"
        "     teaches, the puzzle / question, the key insight, the answer,\n"
        "     and what each part of the video shows. Use the user's original\n"
        "     Chinese phrasing where possible. Do NOT mention TTS, Pillow,\n"
        "     FFmpeg, slides, providers, or any technical implementation.\n"
        "  8. Output a SINGLE JSON object, no markdown fence, no commentary.\n"
        "\n"
        "Schema:\n"
        "{\n"
        "  \"video_title_en\": string (<= 9 words, English),\n"
        "  \"hook_question_en\": string (<= 18 words, English),\n"
        "  \"answer_en\": string (<= 22 words, the actual answer),\n"
        "  \"overview_cn\": string (Chinese paragraph, 4-7 sentences),\n"
        "  \"slides\": [\n"
        "    { \"index\": 1,\n"
        "      \"role\": \"hook\",\n"
        "      \"title\": string,\n"
        "      \"caption\": string,\n"
        "      \"highlight\": string,\n"
        "      \"visual_focus\": string,\n"
        "      \"badge\": string (<= 2 words, English),\n"
        "      \"image_prompt\": string (40-90 words, detailed) },\n"
        "    ... one entry per slide, in order ...\n"
        "  ]\n"
        "}\n"
    )


def _call_llm_for_slide_content(
    title: str,
    duration_seconds: int,
    slide_count: int,
    roles: List[str],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Call the AI_VIDEO_LLM_* model and parse the structured response.

    Returns ``(parsed_dict_or_None, debug)``. ``parsed_dict_or_None`` is
    None when anything goes wrong (no key, network failure, bad JSON,
    schema mismatch). The caller is expected to fall back to the static
    template in that case.

    The debug dict contains config + a few non-sensitive flags but never
    the API key or the system prompt.
    """
    api_key, api_key_source = _resolve_llm_api_key()
    base_url = os.getenv("AI_VIDEO_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("AI_VIDEO_LLM_MODEL", "gpt-5-chat")
    try:
        timeout = int(os.getenv("AI_VIDEO_LLM_TIMEOUT", "60"))
    except Exception:
        timeout = 60
    try:
        max_tokens = int(os.getenv("AI_VIDEO_LLM_MAX_TOKENS", "4096"))
    except Exception:
        max_tokens = 4096
    try:
        temperature = float(os.getenv("AI_VIDEO_LLM_TEMPERATURE", "0.6"))
    except Exception:
        temperature = 0.6

    debug: Dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "timeout_seconds": timeout,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "api_key_configured": bool(api_key),
        "api_key_source": api_key_source or None,
        "config_namespace": "AI_VIDEO_LLM_*",
        "called": False,
        "fallback_used": True,
        "fallback_reason": None,
        "raw_text_chars": 0,
        "disabled_by_env": False,
    }

    # v0.6.3 stabilization — explicit offline mode for smoke tests and
    # offline reproduction. When IMAGE_VIDEO_DISABLE_LLM is truthy, we skip
    # the network call entirely so smoke tests stay 100% local.
    disable_flag = (os.getenv("IMAGE_VIDEO_DISABLE_LLM") or "").strip().lower()
    if disable_flag in ("1", "true", "yes", "on"):
        debug["disabled_by_env"] = True
        debug["fallback_reason"] = "IMAGE_VIDEO_DISABLE_LLM enabled"
        return None, debug

    if not api_key:
        debug["fallback_reason"] = (
            "AI_VIDEO_LLM_API_KEY not configured; using static slide template."
        )
        return None, debug

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        debug["fallback_reason"] = f"openai package unavailable: {exc}"
        return None, debug

    user_prompt = _build_llm_user_prompt(title, duration_seconds, slide_count, roles)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    except Exception as exc:
        debug["fallback_reason"] = f"OpenAI client init failed: {exc}"
        return None, debug

    messages = [
        {
            "role": "system",
            "content": (
                "You write content for short-form educational explainer videos. "
                "Output strict JSON only — no markdown fence, no prose, no "
                "commentary outside the JSON object."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]

    base_payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    raw_text: Optional[str] = None
    debug["called"] = True
    try:
        try:
            resp = client.chat.completions.create(
                **base_payload,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Some OpenAI-compatible gateways don't support response_format.
            resp = client.chat.completions.create(**base_payload)
        raw_text = resp.choices[0].message.content if resp and resp.choices else None
    except Exception as exc:
        debug["fallback_reason"] = f"LLM call failed: {exc}"
        return None, debug

    if not raw_text:
        debug["fallback_reason"] = "LLM returned empty content."
        return None, debug
    debug["raw_text_chars"] = len(raw_text)
    debug["raw_text_preview"] = raw_text[:600]

    parsed = _parse_llm_slide_response(raw_text, slide_count, roles)
    if parsed is None:
        debug["fallback_reason"] = "LLM response did not match expected schema."
        return None, debug

    debug["fallback_used"] = False
    return parsed, debug


def _parse_llm_slide_response(
    raw_text: str, slide_count: int, roles: List[str],
) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction + schema validation."""
    text = raw_text.strip()
    # Strip ```json fences just in case the model adds them.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        data = json.loads(text)
    except Exception:
        # Try to find the outermost {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    slides = data.get("slides")
    if not isinstance(slides, list) or len(slides) != slide_count:
        return None
    cleaned_slides: List[Dict[str, Any]] = []
    for i, item in enumerate(slides):
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        caption = str(item.get("caption") or "").strip()
        highlight = str(item.get("highlight") or "").strip()
        visual_focus = str(item.get("visual_focus") or "").strip()
        badge = str(item.get("badge") or "").strip()
        image_prompt = str(item.get("image_prompt") or "").strip()
        if not title or not caption:
            return None
        cleaned_slides.append({
            "index": i + 1,
            "role": roles[i] if i < len(roles) else "explanation",
            "title": title[:80],
            "caption": caption[:160],
            "highlight": (highlight or title)[:60],
            "visual_focus": visual_focus[:140],
            "badge": (badge or roles[i].title())[:24],
            "image_prompt": image_prompt[:1200],
        })
    overview_cn = str(data.get("overview_cn") or "").strip()
    return {
        "video_title_en": str(data.get("video_title_en") or "").strip()[:80],
        "hook_question_en": str(data.get("hook_question_en") or "").strip()[:160],
        "answer_en": str(data.get("answer_en") or "").strip()[:200],
        "overview_cn": overview_cn,
        "slides": cleaned_slides,
    }


def _build_slide_text(
    role: str,
    index: int,
    total: int,
    subject: str,
) -> Dict[str, str]:
    """Choose title / caption / badge / highlight strings for a slide role.

    Strings are intentionally short and English-only.
    """
    role_text = {
        "hook": {
            "badge": "Question",
            "title": "A Surprising Result",
            "caption": f"What's really going on with {subject}?",
            "highlight": "Look closer.",
        },
        "setup": {
            "badge": "Setup",
            "title": "The Setup",
            "caption": "Two parts to compare. Watch the totals.",
            "highlight": "Compare carefully.",
        },
        "misconception": {
            "badge": "Common Mistake",
            "title": "What People Assume",
            "caption": "The intuitive answer often misses one detail.",
            "highlight": "Don't trust intuition yet.",
        },
        "explanation": {
            "badge": "Step",
            "title": "Walk Through It",
            "caption": "Follow the chain of reasoning, one step at a time.",
            "highlight": "Each step matters.",
        },
        "comparison": {
            "badge": "Compare",
            "title": "Side by Side",
            "caption": "Each side wins on its own. The combined view differs.",
            "highlight": "Watch the totals.",
        },
        "example": {
            "badge": "Example",
            "title": "A Concrete Case",
            "caption": "Plug in numbers to see what happens.",
            "highlight": "Numbers don't lie.",
        },
        "key_insight": {
            "badge": "Key Insight",
            "title": "The Real Reason",
            "caption": "Hidden weights flip the overall direction.",
            "highlight": "This is why.",
        },
        "answer": {
            "badge": "Answer",
            "title": "The Answer",
            "caption": "Both groups can win and the total can lose. It is consistent.",
            "highlight": "Counterintuitive but true.",
        },
        "recap": {
            "badge": "Recap",
            "title": "What We Saw",
            "caption": "Quick recap of the steps before the takeaway.",
            "highlight": "Pieces fit together.",
        },
        "takeaway": {
            "badge": "Takeaway",
            "title": "Final Takeaway",
            "caption": "Aggregates can disagree with parts. Always check the weights.",
            "highlight": "Check the weights.",
        },
    }
    text = role_text.get(role, role_text["explanation"])
    return {
        "title": text["title"],
        "caption": text["caption"],
        "badge": text["badge"],
        "highlight": text["highlight"],
    }


def _build_slide_plan(
    title: str,
    duration_seconds: int,
    slide_count: int,
    llm_content: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (slide_plan, overlay_plan) dicts.

    When ``llm_content`` is provided (validated payload from
    ``_call_llm_for_slide_content``), every slide pulls its title /
    caption / highlight / visual_focus / badge from the model. Roles are
    pulled from the LLM response when valid; otherwise from the static
    role assignment so the renderer always gets a known layout.
    """
    subject = _english_subject(title)
    roles = _assign_roles(slide_count)
    duration_per_slide = duration_seconds / slide_count
    slides: List[Dict[str, Any]] = []
    overlays: List[Dict[str, Any]] = []
    diagram_map = {
        "hook": "large question mark over a topic card",
        "setup": "two side-by-side cards labelled A and B",
        "misconception": "a crossed-out shortcut icon",
        "explanation": "three connected step boxes with arrows",
        "comparison": "two grouped bar shapes side by side",
        "example": "a worked-numbers card",
        "key_insight": "central highlighted insight badge",
        "answer": "answer card with a check badge",
        "recap": "compact 3-step recap row",
        "takeaway": "summary card with a final badge",
    }
    llm_slides = (llm_content or {}).get("slides") if llm_content else None
    for i, role in enumerate(roles, start=1):
        start = round((i - 1) * duration_per_slide, 4)
        end = round(i * duration_per_slide, 4)
        if llm_slides and i - 1 < len(llm_slides):
            entry = llm_slides[i - 1]
            text = {
                "title": entry.get("title") or "",
                "caption": entry.get("caption") or "",
                "highlight": entry.get("highlight") or entry.get("title") or "",
                "badge": entry.get("badge") or role.replace("_", " ").title(),
            }
            visual_focus = entry.get("visual_focus") or ""
            image_prompt = entry.get("image_prompt") or ""
            content_source = "llm"
        else:
            text = _build_slide_text(role, i, slide_count, subject)
            visual_focus = ""
            image_prompt = ""
            content_source = "static_template"
        slides.append({
            "index": i,
            "start": start,
            "end": end,
            "role": role,
            "visual_type": f"{role}_card",
            "title": text["title"],
            "caption": text["caption"],
            "diagram": diagram_map.get(role, "clean whiteboard educational layout"),
            "visual_focus": visual_focus,
            "image_prompt": image_prompt,
            "content_source": content_source,
            "narration_hint": f"Narrator beat for the {role} slide.",
        })
        overlays.append({
            "index": i,
            "title": text["title"],
            "caption": text["caption"],
            "badge": text["badge"],
            "highlight_text": text["highlight"],
            "visual_focus": visual_focus,
            "image_prompt": image_prompt,
            "layout": role,
            "safe_text_source": "local_overlay",
            "content_source": content_source,
        })

    slide_plan = {
        "generation_method": "image_video",
        "version": IMAGE_VIDEO_PIPELINE_VERSION,
        "duration_seconds": duration_seconds,
        "slide_count": slide_count,
        "aspect_ratio": "16:9",
        "resolution": f"{RESOLUTION_W}x{RESOLUTION_H}",
        "fps": FPS,
        "style": "clean whiteboard educational slide",
        "subject": subject,
        "title": title,
        "video_title_en": (llm_content or {}).get("video_title_en") or subject,
        "hook_question_en": (llm_content or {}).get("hook_question_en") or "",
        "answer_en": (llm_content or {}).get("answer_en") or "",
        "content_source": "llm" if llm_slides else "static_template",
        "slides": slides,
    }
    overlay_plan = {
        "generation_method": "image_video",
        "version": IMAGE_VIDEO_PIPELINE_VERSION,
        "duration_seconds": duration_seconds,
        "slide_count": slide_count,
        "subject": subject,
        "slides": overlays,
        "text_rendering": "local_pillow",
        "image_model_text": "disabled",
        "content_source": "llm" if llm_slides else "static_template",
    }
    return slide_plan, overlay_plan


# -------------------- Pillow rendering --------------------

_FONT_CACHE: Dict[Tuple[str, int], Any] = {}


def _load_font(size: int, bold: bool = False) -> Any:
    cache_key = (("bold" if bold else "regular"), size)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]
    candidates = []
    if bold:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    candidates.extend([
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ])
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _FONT_CACHE[cache_key] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


def _measure(draw: "ImageDraw.ImageDraw", text: str, font: Any) -> Tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return draw.textlength(text, font=font), font.size


def _wrap_text(draw: "ImageDraw.ImageDraw", text: str, font: Any, max_width: int) -> List[str]:
    if not text:
        return [""]
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        w, _ = _measure(draw, candidate, font)
        if w <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _draw_pill(draw: "ImageDraw.ImageDraw", xy: Tuple[int, int, int, int],
               fill: Tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = xy
    radius = (y1 - y0) // 2
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    except AttributeError:
        draw.rectangle(xy, fill=fill)


def _draw_card(draw: "ImageDraw.ImageDraw", xy: Tuple[int, int, int, int],
               fill: Tuple[int, int, int], radius: int = 24,
               border: Optional[Tuple[int, int, int]] = None) -> None:
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill,
                               outline=border, width=2 if border else 0)
    except AttributeError:
        draw.rectangle(xy, fill=fill, outline=border, width=2 if border else 0)


def _draw_arrow(draw: "ImageDraw.ImageDraw", x0: int, y0: int, x1: int, y1: int,
                color: Tuple[int, int, int], width: int = 6) -> None:
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    head = 18
    draw.polygon([(x1, y1), (x1 - head, y1 - head // 2), (x1 - head, y1 + head // 2)],
                 fill=color)


def _draw_common_chrome(
    image: "Image.Image",
    badge_text: str,
    progress: Tuple[int, int],
    subject_label: str,
) -> None:
    draw = ImageDraw.Draw(image)
    badge_font = _load_font(36, bold=True)
    foot_font = _load_font(28)

    pad = 60
    badge_w_text, badge_h_text = _measure(draw, badge_text, badge_font)
    badge_w = badge_w_text + 60
    badge_h = badge_h_text + 30
    _draw_pill(draw, (pad, pad, pad + badge_w, pad + badge_h), COLOR_ACCENT)
    draw.text(
        (pad + 30, pad + 15),
        badge_text,
        fill=(255, 255, 255),
        font=badge_font,
    )

    foot_y = RESOLUTION_H - pad - 30
    if _is_chinese(subject_label):
        cjk_foot = _load_unicode_font(28)
        draw.text((pad, foot_y), subject_label, fill=COLOR_MUTED, font=cjk_foot)
    else:
        draw.text((pad, foot_y), subject_label, fill=COLOR_MUTED, font=foot_font)

    progress_str = f"{progress[0]} / {progress[1]}"
    pw, _ph = _measure(draw, progress_str, foot_font)
    draw.text(
        (RESOLUTION_W - pad - pw, foot_y),
        progress_str,
        fill=COLOR_MUTED,
        font=foot_font,
    )


def _fit_title_font(
    draw: "ImageDraw.ImageDraw",
    title: str,
    max_width: int,
    max_lines: int,
    start_size: int = 104,
    min_size: int = 56,
) -> Tuple[Any, List[str]]:
    """Pick a title font size that keeps the wrapped text within max_lines."""
    size = start_size
    while size >= min_size:
        font = _load_font(size, bold=True)
        lines = _wrap_text(draw, title, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 8
    font = _load_font(min_size, bold=True)
    return font, _wrap_text(draw, title, font, max_width)


def _fit_caption_font(
    draw: "ImageDraw.ImageDraw",
    caption: str,
    max_width: int,
    max_lines: int,
    start_size: int = 50,
    min_size: int = 30,
) -> Tuple[Any, List[str]]:
    size = start_size
    while size >= min_size:
        font = _load_font(size)
        lines = _wrap_text(draw, caption, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = _load_font(min_size)
    return font, _wrap_text(draw, caption, font, max_width)


def _draw_centered_title_block(
    draw: "ImageDraw.ImageDraw",
    title: str,
    caption: str,
    title_y: int = 320,
    title_color: Tuple[int, int, int] = COLOR_INK,
    caption_color: Tuple[int, int, int] = COLOR_MUTED,
    max_title_lines: int = 2,
    max_caption_lines: int = 2,
) -> int:
    """Draw a title + caption block that auto-shrinks to fit. Returns the y
    coordinate of the line just below the block so callers can stack
    additional content underneath."""
    title_font, title_lines = _fit_title_font(
        draw, title, RESOLUTION_W - 280, max_title_lines,
    )
    line_h = title_font.size + 20
    for i, line in enumerate(title_lines):
        w, _ = _measure(draw, line, title_font)
        draw.text(((RESOLUTION_W - w) // 2, title_y + i * line_h),
                  line, fill=title_color, font=title_font)

    caption_y = title_y + len(title_lines) * line_h + 26
    if not caption:
        return caption_y
    caption_font, caption_lines = _fit_caption_font(
        draw, caption, RESOLUTION_W - 360, max_caption_lines,
    )
    cap_line_h = caption_font.size + 14
    for i, line in enumerate(caption_lines):
        w, _ = _measure(draw, line, caption_font)
        draw.text(((RESOLUTION_W - w) // 2, caption_y + i * cap_line_h),
                  line, fill=caption_color, font=caption_font)
    return caption_y + len(caption_lines) * cap_line_h


def _draw_visual_focus_strip(
    image: "Image.Image", visual_focus: str, y_top: int,
) -> None:
    """Draw a thin pill near the bottom of the slide with the LLM-supplied
    visual_focus hint, so each slide visibly references the topic-specific
    detail the renderer is trying to show."""
    if not visual_focus or not visual_focus.strip():
        return
    draw = ImageDraw.Draw(image)
    font = _load_font(32)
    text = visual_focus.strip()
    if len(text) > 90:
        text = text[:87] + "..."
    tw, th = _measure(draw, text, font)
    pad_x, pad_y = 28, 14
    box_w = tw + 2 * pad_x
    box_h = th + 2 * pad_y
    x = (RESOLUTION_W - box_w) // 2
    y = max(y_top, RESOLUTION_H - 220)
    if y + box_h > RESOLUTION_H - 110:
        y = RESOLUTION_H - 110 - box_h
    _draw_pill(draw, (x, y, x + box_w, y + box_h), COLOR_NEUTRAL_SOFT)
    draw.text((x + pad_x, y + pad_y), text, fill=COLOR_MUTED, font=font)


def _render_hook(image, slide):
    draw = ImageDraw.Draw(image)
    # Big question mark glyph centered above the title.
    qmark_font = _load_font(260, bold=True)
    qmark = "?"
    w, h = _measure(draw, qmark, qmark_font)
    draw.text(((RESOLUTION_W - w) // 2, 140), qmark,
              fill=COLOR_ACCENT, font=qmark_font)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=420)


def _render_setup(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=200)
    card_y = 540
    card_h = 320
    gap = 80
    card_w = (RESOLUTION_W - 240 - gap) // 2
    left = (240 // 2)
    right = left + card_w + gap
    _draw_card(draw, (left, card_y, left + card_w, card_y + card_h),
               COLOR_ACCENT_SOFT, border=COLOR_ACCENT)
    _draw_card(draw, (right, card_y, right + card_w, card_y + card_h),
               COLOR_NEUTRAL_SOFT, border=COLOR_MUTED)
    label_font = _load_font(110, bold=True)
    for letter, x_anchor in (("A", left + card_w // 2), ("B", right + card_w // 2)):
        w, _ = _measure(draw, letter, label_font)
        draw.text((x_anchor - w // 2, card_y + (card_h - label_font.size) // 2),
                  letter, fill=COLOR_INK, font=label_font)


def _render_misconception(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=240)
    cx, cy = RESOLUTION_W // 2, 760
    box_w, box_h = 680, 200
    _draw_card(draw, (cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2),
               COLOR_WARN_SOFT, border=COLOR_WARN)
    cross = 70
    draw.line([(cx - cross, cy - cross), (cx + cross, cy + cross)],
              fill=COLOR_WARN, width=10)
    draw.line([(cx - cross, cy + cross), (cx + cross, cy - cross)],
              fill=COLOR_WARN, width=10)


def _render_explanation(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=200)
    box_w, box_h, gap = 360, 260, 80
    total = 3 * box_w + 2 * gap
    start = (RESOLUTION_W - total) // 2
    y = 620
    step_font = _load_font(72, bold=True)
    for i in range(3):
        x0 = start + i * (box_w + gap)
        _draw_card(draw, (x0, y, x0 + box_w, y + box_h),
                   COLOR_ACCENT_SOFT, border=COLOR_ACCENT)
        label = str(i + 1)
        w, _ = _measure(draw, label, step_font)
        draw.text((x0 + box_w // 2 - w // 2, y + (box_h - step_font.size) // 2),
                  label, fill=COLOR_ACCENT, font=step_font)
        if i < 2:
            ax0 = x0 + box_w + 12
            ax1 = ax0 + gap - 24
            ay = y + box_h // 2
            _draw_arrow(draw, ax0, ay, ax1, ay, COLOR_ACCENT, width=8)


def _render_comparison(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=200)
    base_y = 880
    bar_w = 100
    gap = 30
    group_gap = 200
    heights_a = [200, 320, 260]
    heights_b = [240, 180, 300]
    group_w = len(heights_a) * bar_w + (len(heights_a) - 1) * gap
    total = group_w * 2 + group_gap
    start_x = (RESOLUTION_W - total) // 2
    for i, h in enumerate(heights_a):
        x = start_x + i * (bar_w + gap)
        draw.rectangle((x, base_y - h, x + bar_w, base_y), fill=COLOR_ACCENT)
    bx_start = start_x + group_w + group_gap
    for i, h in enumerate(heights_b):
        x = bx_start + i * (bar_w + gap)
        draw.rectangle((x, base_y - h, x + bar_w, base_y), fill=COLOR_OK)
    label_font = _load_font(48, bold=True)
    draw.text((start_x + group_w // 2 - 18, base_y + 24), "A",
              fill=COLOR_ACCENT, font=label_font)
    draw.text((bx_start + group_w // 2 - 18, base_y + 24), "B",
              fill=COLOR_OK, font=label_font)


def _render_example(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=200)
    cx = RESOLUTION_W // 2
    card_w, card_h = 1100, 320
    _draw_card(draw, (cx - card_w // 2, 620, cx + card_w // 2, 620 + card_h),
               COLOR_NEUTRAL_SOFT, border=COLOR_MUTED)
    num_font = _load_font(96, bold=True)
    nums = "20  30  50"
    w, _ = _measure(draw, nums, num_font)
    draw.text((cx - w // 2, 740), nums, fill=COLOR_INK, font=num_font)


def _render_key_insight(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=220)
    cx, cy = RESOLUTION_W // 2, 780
    box_w, box_h = 1100, 240
    _draw_card(draw, (cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2),
               COLOR_ACCENT_SOFT, border=COLOR_ACCENT)
    hl_font = _load_font(56, bold=True)
    hl = slide.get("highlight_text") or "Hidden weights flip the result."
    w, _ = _measure(draw, hl, hl_font)
    draw.text((cx - w // 2, cy - hl_font.size // 2), hl,
              fill=COLOR_ACCENT, font=hl_font)


def _render_answer(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=220)
    cx, cy = RESOLUTION_W // 2, 780
    box_w, box_h = 1100, 240
    _draw_card(draw, (cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2),
               COLOR_OK_SOFT, border=COLOR_OK)
    check_font = _load_font(140, bold=True)
    check = "✓"
    w, _ = _measure(draw, check, check_font)
    draw.text((cx - w // 2, cy - check_font.size // 2), check,
              fill=COLOR_OK, font=check_font)


def _render_recap(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=220)
    base_y = 720
    box_w, box_h, gap = 320, 200, 40
    total = 3 * box_w + 2 * gap
    start = (RESOLUTION_W - total) // 2
    label_font = _load_font(60, bold=True)
    for i in range(3):
        x0 = start + i * (box_w + gap)
        _draw_card(draw, (x0, base_y, x0 + box_w, base_y + box_h),
                   COLOR_NEUTRAL_SOFT, border=COLOR_MUTED)
        label = str(i + 1)
        w, _ = _measure(draw, label, label_font)
        draw.text((x0 + box_w // 2 - w // 2, base_y + (box_h - label_font.size) // 2),
                  label, fill=COLOR_MUTED, font=label_font)


def _render_takeaway(image, slide):
    draw = ImageDraw.Draw(image)
    _draw_centered_title_block(draw, slide["title"], slide["caption"], title_y=240)
    cx, cy = RESOLUTION_W // 2, 800
    box_w, box_h = 1200, 200
    _draw_card(draw, (cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2),
               COLOR_OK_SOFT, border=COLOR_OK)
    final_font = _load_font(56, bold=True)
    final = "Final Takeaway"
    w, _ = _measure(draw, final, final_font)
    draw.text((cx - w // 2, cy - final_font.size // 2), final,
              fill=COLOR_OK, font=final_font)


_RENDERERS = {
    "hook": _render_hook,
    "setup": _render_setup,
    "misconception": _render_misconception,
    "explanation": _render_explanation,
    "comparison": _render_comparison,
    "example": _render_example,
    "key_insight": _render_key_insight,
    "answer": _render_answer,
    "recap": _render_recap,
    "takeaway": _render_takeaway,
}


def _load_unicode_font(size: int, bold: bool = False) -> Any:
    """Return a font that can render CJK glyphs (used only in chrome footer
    for Chinese topics). Falls back to the default body font if no CJK
    font is found on the system."""
    cache_key = (("unicode_bold" if bold else "unicode"), size)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _FONT_CACHE[cache_key] = font
                return font
            except Exception:
                continue
    return _load_font(size, bold=bold)


def _render_slide(slide: Dict[str, Any], overlay: Dict[str, Any],
                  subject: str, total: int, output_path: Path) -> None:
    image = Image.new("RGB", (RESOLUTION_W, RESOLUTION_H), COLOR_BG)
    renderer = _RENDERERS.get(slide["role"], _render_explanation)
    enriched = dict(slide)
    enriched["highlight_text"] = overlay.get("highlight_text")
    enriched["visual_focus"] = overlay.get("visual_focus") or slide.get("visual_focus")
    renderer(image, enriched)
    visual_focus = enriched.get("visual_focus") or ""
    if visual_focus:
        _draw_visual_focus_strip(image, visual_focus, y_top=RESOLUTION_H - 220)
    _draw_common_chrome(
        image,
        badge_text=overlay.get("badge", slide["role"].title()),
        progress=(slide["index"], total),
        subject_label=subject,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output_path), format="PNG", optimize=True)


# -------------------- FFmpeg discovery + composition --------------------


_FFMPEG_PROBE_PATHS = (
    "/opt/homebrew/bin/ffmpeg",   # macOS Apple Silicon Homebrew
    "/usr/local/bin/ffmpeg",       # macOS Intel Homebrew / common manual install
    "/usr/bin/ffmpeg",             # Linux package managers
    "/bin/ffmpeg",                 # last-resort Linux fallback
)


def resolve_ffmpeg_binary() -> Tuple[Optional[str], Dict[str, Any]]:
    """Locate an ffmpeg executable, returning ``(path, diagnostics)``.

    Lookup order:
        1. ``$FFMPEG_BIN`` (explicit user override)
        2. ``shutil.which("ffmpeg")`` (current PATH)
        3. ``/opt/homebrew/bin/ffmpeg`` (Apple Silicon Homebrew)
        4. ``/usr/local/bin/ffmpeg`` (Intel Homebrew / manual install)
        5. ``/usr/bin/ffmpeg``, ``/bin/ffmpeg`` (Linux fallbacks)

    Diagnostics include every path that was probed and the value of the
    server's ``PATH`` environment variable so the operator can see what
    Python was actually looking at. The API key namespace is irrelevant
    here — no secret is read or returned.
    """
    checked: List[Dict[str, Any]] = []

    def _probe(label: str, candidate: Optional[str]) -> Optional[str]:
        entry: Dict[str, Any] = {"source": label, "path": candidate, "exists": False}
        if candidate:
            try:
                exists = os.path.isfile(candidate) and os.access(candidate, os.X_OK)
            except Exception:
                exists = False
            entry["exists"] = bool(exists)
        checked.append(entry)
        return candidate if entry["exists"] else None

    found: Optional[str] = None
    env_override = os.getenv("FFMPEG_BIN")
    found = _probe("FFMPEG_BIN", env_override) or found
    if not found:
        which_hit = shutil.which("ffmpeg")
        found = _probe("shutil.which", which_hit) or found
    for hard_path in _FFMPEG_PROBE_PATHS:
        if found:
            # Still record subsequent probes so the diagnostics show the
            # full search list — but we don't actually call them.
            checked.append({"source": "fixed-path", "path": hard_path, "exists": False, "skipped": True})
            continue
        found = _probe("fixed-path", hard_path) or found

    diagnostics: Dict[str, Any] = {
        "found": bool(found),
        "path": found,
        "checked_paths": checked,
        "server_path_env": os.getenv("PATH"),
        "install_hint": "macOS: brew install ffmpeg",
        "error": None if found
                 else "FFmpeg is required for Image Video composition. "
                      "Please install ffmpeg (macOS: brew install ffmpeg) "
                      "and restart the backend server.",
    }
    return found, diagnostics


def _format_ffmpeg_missing_message(diagnostics: Dict[str, Any]) -> str:
    """Compose the multi-line error string written to ``ffmpeg_command.txt``
    and bubbled up through pipeline_result.error when ffmpeg is missing.
    """
    lines = [
        "FFmpeg is required for Image Video composition.",
        "",
        "macOS:",
        "    brew install ffmpeg",
        "",
        "Then restart the backend server:",
        "    python3 -m uvicorn web.app:app --reload --port 8000",
        "",
        "Diagnostics:",
        "    GET /api/video/diagnostics/ffmpeg",
        "",
        "Probed locations:",
    ]
    for entry in diagnostics.get("checked_paths") or []:
        path = entry.get("path") or "(unset)"
        src = entry.get("source") or "?"
        skip = " (skipped — earlier match)" if entry.get("skipped") else ""
        lines.append(f"    [{src}] {path}{skip}")
    return "\n".join(lines) + "\n"


def _compose_with_ffmpeg(
    ffmpeg_bin: str,
    slide_paths: List[Path],
    duration_per_slide: float,
    output_path: Path,
    work_dir: Path,
) -> Tuple[bool, str, List[str], Path]:
    """Concat slide PNGs into an mp4 using the ffmpeg concat demuxer.

    Returns (ok, message, ffmpeg_args, concat_txt_path).
    """
    concat_txt = work_dir / "concat.txt"
    lines: List[str] = []
    for p in slide_paths:
        lines.append(f"file '{p.resolve().as_posix()}'")
        lines.append(f"duration {duration_per_slide:.4f}")
    # FFmpeg concat demuxer requires the last file to be repeated without a
    # duration line so the final frame holds for the right amount of time.
    if slide_paths:
        lines.append(f"file '{slide_paths[-1].resolve().as_posix()}'")
    concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    args = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_txt.resolve()),
        "-vf", f"fps={FPS},format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path.resolve()),
    ]
    try:
        proc = subprocess.run(
            args,
            cwd=str(work_dir.resolve()),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return (False, "FFmpeg binary disappeared during invocation.", args, concat_txt)
    except subprocess.TimeoutExpired:
        return (False, "FFmpeg composition timed out (>600s).", args, concat_txt)

    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        return (False, f"FFmpeg exited with code {proc.returncode}: {tail}",
                args, concat_txt)
    if not output_path.exists() or output_path.stat().st_size == 0:
        return (False, "FFmpeg reported success but output file is missing or empty.",
                args, concat_txt)
    return (True, "ok", args, concat_txt)


# -------------------- Public entrypoint --------------------


def generate_image_video_package(
    title: str,
    duration_seconds: int,
    output_dir: str | Path,
    slug: Optional[str] = None,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate the v0.6.3 Image Video bundle for a given title/duration.

    No remote calls to media providers. The pipeline may call
    ``AI_VIDEO_LLM_*`` for slide content (unless ``IMAGE_VIDEO_DISABLE_LLM``
    is set). Returns a dict regardless of FFmpeg availability — the caller
    can inspect ``route_status`` and ``error`` to decide what to show.

    v0.6.3.2 — ``progress_cb`` is an optional ``(stage_key, status, message)``
    callable used by the run worker to report real per-stage timing into
    the run store. Stage keys this pipeline emits:

        plan_slides            (slide_plan + overlay_plan generated)
        write_slide_content    (LLM call or static fallback)
        render_slide_images    (Pillow render loop)
        compose_final_video    (FFmpeg concat → final_video.mp4)

    The callback is fully optional; passing None preserves the v0.6.3
    behaviour (no progress reporting).
    """
    def _emit(stage_key: str, status: str, message: str = "") -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(stage_key, status, message)
        except Exception:
            # Progress reporting must never break the pipeline.
            pass
    title_clean = (title or "").strip()
    if not title_clean:
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": 0,
            "error": "Title cannot be empty",
            "external_api_called": False,
            "seedance_called": False,
            "apx_called": False,
            "image2_called": False,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_implemented_v0.6.3",
            "voiceover_source": "none",
        }
    if duration_seconds not in DURATION_SLIDE_RANGES:
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": 0,
            "error": f"Unsupported duration_seconds={duration_seconds}; "
                     f"allowed: {ALLOWED_DURATIONS}",
            "external_api_called": False,
            "seedance_called": False,
            "apx_called": False,
            "image2_called": False,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_implemented_v0.6.3",
            "voiceover_source": "none",
        }

    output_root = Path(output_dir)
    image_video_dir = output_root / "image_video"
    slides_dir = image_video_dir / "slides"
    image_video_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)

    _emit("plan_slides", "running", "Resolving slide count and roles...")
    slide_count = resolve_slide_count(duration_seconds, title=title_clean)
    duration_per_slide = duration_seconds / slide_count
    roles = _assign_roles(slide_count)
    _emit("plan_slides", "done",
          f"Planned {slide_count} slides ({duration_per_slide:.2f}s each).")

    # v0.6.3 — call the configured AI_VIDEO_LLM_* model (gpt-5-chat by default)
    # to write per-slide content tailored to the user's topic and a Chinese
    # paragraph overview. Fall back to the static template on any failure so
    # the video always renders. This LLM is NOT a forbidden API — APX,
    # Seedance, Image2, and TTS remain off.
    _emit("write_slide_content", "running",
          "Calling AI_VIDEO_LLM_* for slide titles, captions, and image prompts...")
    llm_content, llm_debug = _call_llm_for_slide_content(
        title=title_clean,
        duration_seconds=duration_seconds,
        slide_count=slide_count,
        roles=roles,
    )
    if llm_content:
        _emit("write_slide_content", "done",
              f"AI wrote {len(llm_content.get('slides', []))} slide blocks "
              f"+ Chinese overview.")
    else:
        _emit("write_slide_content", "done",
              f"Static template used ({llm_debug.get('fallback_reason') or 'fallback'}).")

    slide_plan, overlay_plan = _build_slide_plan(
        title_clean, duration_seconds, slide_count, llm_content=llm_content,
    )

    # Persist plans + LLM artifacts so they're available even if FFmpeg
    # fails later. The API key is never written.
    slide_plan_path = image_video_dir / "slide_plan.json"
    overlay_plan_path = image_video_dir / "overlay_plan.json"
    llm_debug_path = image_video_dir / "llm_debug.json"
    llm_slide_content_path = image_video_dir / "llm_slide_content.json"
    overview_cn_path = image_video_dir / "overview_cn.txt"
    slide_plan_path.write_text(
        json.dumps(slide_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    overlay_plan_path.write_text(
        json.dumps(overlay_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    llm_debug_path.write_text(
        json.dumps(llm_debug, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if llm_content:
        llm_slide_content_path.write_text(
            json.dumps(llm_content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        overview_cn_text = (llm_content.get("overview_cn") or "").strip()
        if overview_cn_text:
            overview_cn_path.write_text(overview_cn_text, encoding="utf-8")

    subject = slide_plan["subject"]
    chrome_label = title_clean if _is_chinese(title_clean) else subject
    slide_paths: List[Path] = []
    _emit("render_slide_images", "running",
          f"Rendering {slide_count} slide PNGs with Pillow...")
    try:
        for slide, overlay in zip(slide_plan["slides"], overlay_plan["slides"]):
            slide_path = slides_dir / f"slide_{slide['index']:02d}.png"
            _render_slide(slide, overlay, chrome_label, slide_count, slide_path)
            slide_paths.append(slide_path)
        _emit("render_slide_images", "done",
              f"{slide_count} slide PNGs ready.")
    except Exception as exc:
        _emit("render_slide_images", "failed", f"Pillow render failed: {exc}")
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": slide_count,
            "slide_plan_path": str(slide_plan_path),
            "overlay_plan_path": str(overlay_plan_path),
            "slides_dir": str(slides_dir),
            "final_video_path": None,
            "error": f"Failed to render slides with Pillow: {exc}",
            "content_llm_called": bool(llm_debug.get("called")),
            "media_api_called": False,
            "external_api_called": bool(llm_debug.get("called")),
            "seedance_called": False,
            "apx_called": False,
            "image2_called": False,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_implemented_v0.6.3",
            "voiceover_source": "none",
            "image_source": "local_static_renderer",
            "video_composer": "ffmpeg",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

    final_video_path = image_video_dir / "final_video.mp4"
    ffmpeg_command_path = image_video_dir / "ffmpeg_command.txt"

    _emit("compose_final_video", "running", "Locating ffmpeg binary...")
    ffmpeg_bin, ffmpeg_diagnostics = resolve_ffmpeg_binary()
    if not ffmpeg_bin:
        # Persist a placeholder so operators can see what would have run.
        ffmpeg_command_path.write_text(
            _format_ffmpeg_missing_message(ffmpeg_diagnostics),
            encoding="utf-8",
        )
        _emit("compose_final_video", "failed",
              "FFmpeg not found — see diagnostics.")
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": slide_count,
            "slide_plan_path": str(slide_plan_path),
            "overlay_plan_path": str(overlay_plan_path),
            "slides_dir": str(slides_dir),
            "final_video_path": None,
            "ffmpeg_command_path": str(ffmpeg_command_path),
            "error": ffmpeg_diagnostics.get("error")
                     or "FFmpeg is required for Image Video composition. "
                        "Please install ffmpeg (macOS: brew install ffmpeg).",
            "ffmpeg_found": False,
            "ffmpeg_path": None,
            "ffmpeg_diagnostics": ffmpeg_diagnostics,
            "external_api_called": bool(llm_debug.get("called")),
            "content_llm_called": bool(llm_debug.get("called")),
            "media_api_called": False,
            "seedance_called": False,
            "apx_called": False,
            "image2_called": False,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_implemented_v0.6.3",
            "voiceover_source": "none",
            "image_source": "local_static_renderer",
            "video_composer": "ffmpeg_missing",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

    _emit("compose_final_video", "running",
          f"Composing final mp4 with FFmpeg ({slide_count} slides)...")
    ok, msg, ffmpeg_args, concat_path = _compose_with_ffmpeg(
        ffmpeg_bin, slide_paths, duration_per_slide, final_video_path, image_video_dir
    )
    # Always persist the command we ran (for debugging / transparency).
    ffmpeg_command_path.write_text(
        " ".join(ffmpeg_args) + "\n", encoding="utf-8"
    )

    if not ok:
        _emit("compose_final_video", "failed", msg)
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": slide_count,
            "slide_plan_path": str(slide_plan_path),
            "overlay_plan_path": str(overlay_plan_path),
            "slides_dir": str(slides_dir),
            "concat_path": str(concat_path),
            "ffmpeg_command_path": str(ffmpeg_command_path),
            "final_video_path": None,
            "error": msg,
            "content_llm_called": bool(llm_debug.get("called")),
            "media_api_called": False,
            "external_api_called": bool(llm_debug.get("called")),
            "seedance_called": False,
            "apx_called": False,
            "image2_called": False,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_implemented_v0.6.3",
            "voiceover_source": "none",
            "image_source": "local_static_renderer",
            "video_composer": "ffmpeg",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

    _emit("compose_final_video", "done",
          f"final_video.mp4 ready ({final_video_path.name}).")
    return {
        "generation_method": "image_video",
        "version": IMAGE_VIDEO_PIPELINE_VERSION,
        "route_status": "succeeded",
        "duration_seconds": duration_seconds,
        "slide_count": slide_count,
        "duration_per_slide": duration_per_slide,
        "subject": subject,
        "slide_plan_path": str(slide_plan_path),
        "overlay_plan_path": str(overlay_plan_path),
        "llm_debug_path": str(llm_debug_path),
        "llm_slide_content_path": str(llm_slide_content_path) if llm_content else None,
        "overview_cn_path": str(overview_cn_path) if (
            llm_content and (llm_content.get("overview_cn") or "").strip()
        ) else None,
        "slides_dir": str(slides_dir),
        "concat_path": str(concat_path),
        "ffmpeg_command_path": str(ffmpeg_command_path),
        "final_video_path": str(final_video_path),
        "ffmpeg_found": True,
        "ffmpeg_path": ffmpeg_bin,
        "ffmpeg_diagnostics": ffmpeg_diagnostics,
        # v0.6.3 stabilization: distinguish content LLM (text) from media
        # API calls (Image2 / Seedance / TTS / APX). Image Video v0.6.3 may
        # call AI_VIDEO_LLM_* for slide text, but never any media provider.
        "content_llm_called": bool(llm_debug.get("called")),
        "media_api_called": False,
        # `external_api_called` is preserved for backwards compatibility but
        # now means "any external network call was made" (LLM included).
        "external_api_called": bool(llm_debug.get("called")),
        "seedance_called": False,
        "apx_called": False,
        "image2_called": False,
        "tts_called": False,
        "has_audio": False,
        "tts_status": "not_implemented_v0.6.3",
        "voiceover_source": "none",
        "image_source": "local_static_renderer",
        "video_composer": "ffmpeg",
        "content_source": "llm" if llm_content else "static_template",
        "llm_used": bool(llm_content),
        "llm_fallback_used": bool(llm_debug.get("fallback_used")),
        "llm_fallback_reason": llm_debug.get("fallback_reason"),
        "llm_model": llm_debug.get("model"),
        "video_title_en": (llm_content or {}).get("video_title_en"),
        "hook_question_en": (llm_content or {}).get("hook_question_en"),
        "answer_en": (llm_content or {}).get("answer_en"),
        "overview_cn": (llm_content or {}).get("overview_cn"),
        "error": None,
    }
