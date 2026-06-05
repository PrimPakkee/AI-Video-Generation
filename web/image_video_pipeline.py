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
        "You are designing a short-form educational explainer video in the\n"
        "visual style of Google NotebookLM's video overviews.\n"
        "\n"
        "WHAT IS UNIVERSALLY TRUE OF NOTEBOOKLM-STYLE VIDEOS\n"
        "(applies to every topic, do not change):\n"
        "  - Paper-craft / cut-paper / layered torn-paper illustrations.\n"
        "    Layered shapes with soft drop shadows, hand-cut edges,\n"
        "    tactile material feel. NOT vector flat art, NOT 3D render,\n"
        "    NOT photo, NOT line drawing.\n"
        "  - One single large subject sits in the center of the frame and\n"
        "    occupies roughly 50–65%% of the canvas. The rest of the frame\n"
        "    is generous negative space.\n"
        "  - Any on-screen English text is rendered AS PART OF the paper-\n"
        "    craft artwork itself — bold chunky paper-cut letters integrated\n"
        "    into the composition. NEVER a caption bar, NEVER a watermark,\n"
        "    NEVER a translucent overlay.\n"
        "  - 16:9 landscape composition. No badges, no progress counters,\n"
        "    no Chinese characters anywhere on the canvas.\n"
        "  - All N slides for a single video share the SAME palette,\n"
        "    background texture, and overall mood — the video reads as one\n"
        "    visual world, not N unrelated illustrations.\n"
        "\n"
        "WHAT IS *NOT* UNIVERSAL — YOU PICK PER TOPIC:\n"
        "  - The actual color palette\n"
        "  - The background texture / color\n"
        "  - The overall mood / lighting\n"
        "  - The kind of objects that show up\n"
        "These should match the topic's domain and emotional tone. Examples\n"
        "(do not copy verbatim — use them only as guidance for how varied\n"
        "the choices should be):\n"
        "  - Topic about rainbows  → bright sky-blue background, full\n"
        "    rainbow palette, sunny mood, paper clouds and sun motifs.\n"
        "  - Topic about black holes → deep navy / charcoal background,\n"
        "    with small accents of warm orange or violet, mysterious mood.\n"
        "  - Topic about compounding interest → muted forest green +\n"
        "    aged-parchment cream + brass-gold coin accents, ledger-paper\n"
        "    background, serious-but-warm mood.\n"
        "  - Topic about why free trials are risky → dim blue-grey paper\n"
        "    background with warning-red and credit-card-blue accents,\n"
        "    cautionary mood, small clock and credit-card motifs.\n"
        "  - Topic about DNA replication → soft mint-green and pale-rose\n"
        "    palette, cool clinical mood, lab-paper background.\n"
        "  - Topic about ancient Roman history → terracotta / sandstone /\n"
        "    aged-papyrus palette, faded sepia mood.\n"
        "Do NOT default to sky-blue + cream + rainbow colors unless the\n"
        "topic itself is about something colorful and cheerful. Pick what\n"
        "actually fits.\n"
        "\n"
        "Topic (verbatim, may be Chinese):\n"
        f"  {title}\n"
        "\n"
        f"Target duration: {duration_seconds} seconds, {slide_count} slides.\n"
        "Slide narrative arc (in order):\n"
        f"{role_lines}\n"
        "\n"
        "Hard requirements:\n"
        "  1. ALL English text fields must be in ENGLISH even if the topic\n"
        "     is Chinese. The image generator ships English fonts only.\n"
        "  2. The narrative MUST directly address the user's topic. Never\n"
        "     produce generic 'Simpson paradox' or 'rainbow' filler. If the\n"
        "     topic is about prime numbers, the slides talk about prime\n"
        "     numbers.\n"
        "  3. Each slide title <= 7 words. caption <= 16 words. highlight\n"
        "     <= 8 words. visual_focus <= 14 words.\n"
        "  4. visual_focus describes ONE concrete object the picture should\n"
        "     emphasize — e.g. 'two coins side by side', 'a bar of height 7',\n"
        "     'three dice with faces 1, 2, 3'. Keep it concrete.\n"
        "  5. art_direction is a SHARED 60–100 word description that EVERY\n"
        "     slide will reuse to keep the video visually consistent. It\n"
        "     must specify, for THIS topic:\n"
        "       a) Paper-craft medium reminder (cut-paper / layered torn\n"
        "          paper / soft shadows / hand-cut edges).\n"
        "       b) Background texture and color you have CHOSEN for this\n"
        "          topic — be specific (e.g. 'aged cream parchment paper\n"
        "          with subtle fiber texture' / 'deep navy starfield paper'\n"
        "          / 'pale sky-blue paper with faint grid'). Do NOT say\n"
        "          'either A or B' — pick one.\n"
        "       c) Palette of 3–5 specific colors with hex codes you've\n"
        "          chosen for THIS topic.\n"
        "       d) Mood / lighting (e.g. 'cautionary, low-key' /\n"
        "          'cheerful, bright' / 'mysterious, low-contrast').\n"
        "       e) The composition rules that apply to every slide:\n"
        "          single centered subject ≈60%% of frame, generous\n"
        "          negative space, no text bands, no badges, no progress\n"
        "          counters, no Chinese characters, English text only,\n"
        "          rendered as paper-cut lettering integrated into the\n"
        "          artwork, 16:9 landscape.\n"
        "  6. image_prompt for each slide MUST start with the literal\n"
        "     string '<USE ART_DIRECTION>' (5 words including angle\n"
        "     brackets) — the pipeline will replace that token with the\n"
        "     shared art_direction text before sending to gpt-image-2.\n"
        "     After that token, describe in 50–90 words THIS slide's\n"
        "     specific subject: what paper-cut object/scene appears, how\n"
        "     it's positioned, and the exact English on-screen text the\n"
        "     image must render as part of the paper-cut composition\n"
        "     (e.g. 'Bold chunky paper-cut English title \\\"WHY DOES IT\n"
        "     REPEAT?\\\" sits across the upper third'). Do NOT repeat the\n"
        "     palette / background / mood here — those live in\n"
        "     art_direction. Just the slide-specific scene + text.\n"
        "  7. The narrative should genuinely teach: hook a question, set\n"
        "     up the problem, walk through real reasoning, deliver an\n"
        "     answer, end with a takeaway.\n"
        "  8. Also produce a Chinese paragraph (`overview_cn`) of 4–7\n"
        "     sentences in flowing prose (no bullets, no headings). It\n"
        "     describes what this short video teaches: the puzzle /\n"
        "     question, the key insight, the answer, what each part shows.\n"
        "     Use the user's original Chinese phrasing where possible.\n"
        "     Do NOT mention TTS, Pillow, FFmpeg, slides, providers, or\n"
        "     any technical implementation detail.\n"
        "  9. Output a SINGLE JSON object — no markdown fence, no prose\n"
        "     outside the JSON.\n"
        "\n"
        "Schema:\n"
        "{\n"
        "  \"video_title_en\": string (<= 9 words, English),\n"
        "  \"hook_question_en\": string (<= 18 words, English),\n"
        "  \"answer_en\": string (<= 22 words, the actual answer),\n"
        "  \"overview_cn\": string (Chinese paragraph, 4-7 sentences),\n"
        "  \"art_direction\": string (60-100 words, shared by all slides),\n"
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

    # v0.6.4.1 — pull the LLM-chosen art_direction (palette / background /
    # mood for THIS topic) and splice it into every slide's image_prompt
    # by replacing the literal '<USE ART_DIRECTION>' token. If the token
    # is missing (e.g. the model forgot), prepend the art_direction
    # automatically so we still get a topic-consistent visual world.
    art_direction = str(data.get("art_direction") or "").strip()[:1200]

    cleaned_slides: List[Dict[str, Any]] = []
    for i, item in enumerate(slides):
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        caption = str(item.get("caption") or "").strip()
        highlight = str(item.get("highlight") or "").strip()
        visual_focus = str(item.get("visual_focus") or "").strip()
        badge = str(item.get("badge") or "").strip()
        image_prompt_raw = str(item.get("image_prompt") or "").strip()
        if not title or not caption:
            return None

        # Splice art_direction into image_prompt. The pipeline sends
        # `image_prompt_resolved` (after splicing) to gpt-image-2; we keep
        # both raw + resolved so the Raw Text tab shows the operator
        # exactly what was sent.
        if art_direction:
            if "<USE ART_DIRECTION>" in image_prompt_raw:
                image_prompt_resolved = image_prompt_raw.replace(
                    "<USE ART_DIRECTION>", art_direction, 1,
                )
            else:
                image_prompt_resolved = f"{art_direction}\n\n{image_prompt_raw}"
        else:
            image_prompt_resolved = image_prompt_raw

        cleaned_slides.append({
            "index": i + 1,
            "role": roles[i] if i < len(roles) else "explanation",
            "title": title[:80],
            "caption": caption[:160],
            "highlight": (highlight or title)[:60],
            "visual_focus": visual_focus[:140],
            "badge": (badge or roles[i].title())[:24],
            "image_prompt_template": image_prompt_raw[:1500],
            "image_prompt": image_prompt_resolved[:2400],
        })
    overview_cn = str(data.get("overview_cn") or "").strip()
    return {
        "video_title_en": str(data.get("video_title_en") or "").strip()[:80],
        "hook_question_en": str(data.get("hook_question_en") or "").strip()[:160],
        "answer_en": str(data.get("answer_en") or "").strip()[:200],
        "overview_cn": overview_cn,
        "art_direction": art_direction,
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


def _resize_to_canvas(src_image: "Image.Image") -> "Image.Image":
    """Fit ``src_image`` into a 1920×1080 RGB canvas, preserving aspect ratio.

    The image2 endpoint may return e.g. 1792×1024 (close to 16:9 but not
    exact) or even 1254×1254 (square). We center-crop after a proportional
    resize so the final frame always fills 1920×1080 without letterboxing.
    """
    if src_image.mode != "RGB":
        src_image = src_image.convert("RGB")
    sw, sh = src_image.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", (RESOLUTION_W, RESOLUTION_H), COLOR_BG)
    target_ratio = RESOLUTION_W / RESOLUTION_H
    src_ratio = sw / sh
    if abs(src_ratio - target_ratio) < 0.01:
        return src_image.resize((RESOLUTION_W, RESOLUTION_H), Image.LANCZOS)
    if src_ratio > target_ratio:
        # Source is wider — scale by height, crop width
        new_h = RESOLUTION_H
        new_w = int(round(sw * (RESOLUTION_H / sh)))
        resized = src_image.resize((new_w, new_h), Image.LANCZOS)
        x0 = (new_w - RESOLUTION_W) // 2
        return resized.crop((x0, 0, x0 + RESOLUTION_W, RESOLUTION_H))
    # Source is taller — scale by width, crop height
    new_w = RESOLUTION_W
    new_h = int(round(sh * (RESOLUTION_W / sw)))
    resized = src_image.resize((new_w, new_h), Image.LANCZOS)
    y0 = (new_h - RESOLUTION_H) // 2
    return resized.crop((0, y0, RESOLUTION_W, y0 + RESOLUTION_H))


def _draw_text_band_over_background(
    image: "Image.Image", title: str, caption: str,
    title_y: int = 320, max_title_lines: int = 2, max_caption_lines: int = 2,
) -> int:
    """Draw a translucent band + title/caption on top of an image2 background.

    The band keeps the text legible regardless of what colors the image
    model picked. Returns the y coordinate just below the caption so
    callers can stack additional content underneath if they want.
    """
    draw = ImageDraw.Draw(image, "RGBA")
    title_font, title_lines = _fit_title_font(
        draw, title, RESOLUTION_W - 280, max_title_lines,
    )
    line_h = title_font.size + 20
    title_block_h = len(title_lines) * line_h + 26
    caption_lines: List[str] = []
    caption_font = None
    cap_line_h = 0
    if caption:
        caption_font, caption_lines = _fit_caption_font(
            draw, caption, RESOLUTION_W - 360, max_caption_lines,
        )
        cap_line_h = caption_font.size + 14
    band_h = title_block_h + (len(caption_lines) * cap_line_h) + 40
    band_y0 = max(0, title_y - 40)
    band_y1 = min(RESOLUTION_H, band_y0 + band_h)
    draw.rectangle(
        (0, band_y0, RESOLUTION_W, band_y1),
        fill=(255, 255, 255, 200),
    )
    for i, line in enumerate(title_lines):
        w, _ = _measure(draw, line, title_font)
        draw.text(((RESOLUTION_W - w) // 2, title_y + i * line_h),
                  line, fill=COLOR_INK, font=title_font)
    caption_y = title_y + len(title_lines) * line_h + 26
    if caption_font and caption_lines:
        for i, line in enumerate(caption_lines):
            w, _ = _measure(draw, line, caption_font)
            draw.text(((RESOLUTION_W - w) // 2, caption_y + i * cap_line_h),
                      line, fill=COLOR_MUTED, font=caption_font)
        return caption_y + len(caption_lines) * cap_line_h
    return caption_y


def _render_slide(slide: Dict[str, Any], overlay: Dict[str, Any],
                  subject: str, total: int, output_path: Path,
                  background: Optional["Image.Image"] = None) -> None:
    """Render one slide to a PNG.

    v0.6.4.1 — when ``background`` is provided (image2 succeeded for this
    slide), we use the image **as-is**: resize to 1920×1080 and save. No
    text band, no badge pill, no progress counter, no Chinese subject
    footer. The image2 prompt itself instructs gpt-image-2 to render any
    on-screen English title/caption as part of the paper-cut composition,
    matching the NotebookLM video-overview look.

    When ``background`` is None (image2 disabled / failed for this slide),
    we still fall back to the original Pillow path: blank canvas +
    role-specific diagram + centered title/caption + chrome. The chrome
    is only drawn on the Pillow fallback path so the user can tell which
    slides came from image2 and which were generated locally.
    """
    if background is not None:
        image = _resize_to_canvas(background)
        # No Pillow overlays on image2 output. The image already contains
        # the on-screen text it needs.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(output_path), format="PNG", optimize=True)
        return

    # Pillow fallback path — keeps the v0.6.3 chrome so the operator can
    # see at a glance that this slide was NOT produced by image2.
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


# -------------------- Image2 background generation (v0.6.4) --------------------
#
# When APX_IMAGE2_ENABLED=true, every slide gets a topic-specific real image
# (gpt-image-2) as its background. The LLM-written title/caption are still
# drawn locally with Pillow on top of a translucent band so the on-screen
# text stays correct regardless of how the image model handled type. Each
# slide is generated independently in a thread pool — a single slide
# failing falls back to the v0.6.3 Pillow renderer for that slide only.


def _image2_disabled_by_env() -> bool:
    """Smoke / offline kill switch."""
    flag = (os.getenv("IMAGE_VIDEO_DISABLE_IMAGE2") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _generate_image2_backgrounds(
    slide_plan: Dict[str, Any],
    image_video_dir: Path,
    progress_cb: Optional[Any] = None,
) -> Tuple[Dict[int, "Image.Image"], Dict[str, Any]]:
    """Run gpt-image-2 for every slide concurrently. Returns
    ``(per_slide_image_map, debug)``.

    ``per_slide_image_map`` is keyed by slide index. Slides whose call
    failed are simply absent from the map; the caller falls back to the
    Pillow-only renderer for those.

    The function is allowed to return an empty map (image2 disabled, no
    provider configured, or all calls failed). It NEVER raises.
    """
    debug: Dict[str, Any] = {
        "called": False,
        "disabled_by_env": False,
        "provider_configured": False,
        "skipped_reason": None,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "per_slide": [],
        "concurrency": 1,
    }

    def _emit(stage_key: str, status: str, message: str = "") -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(stage_key, status, message)
        except Exception:
            pass

    if _image2_disabled_by_env():
        debug["disabled_by_env"] = True
        debug["skipped_reason"] = "IMAGE_VIDEO_DISABLE_IMAGE2 enabled"
        _emit("generate_slide_images", "done",
              "Skipped — IMAGE_VIDEO_DISABLE_IMAGE2 set; using local Pillow only.")
        return {}, debug

    try:
        from web.image_providers.apx_image2_provider import ApxImage2Provider
    except Exception as exc:
        debug["skipped_reason"] = f"provider import failed: {exc}"
        _emit("generate_slide_images", "done",
              f"Skipped — provider import failed ({exc}); Pillow only.")
        return {}, debug

    provider = ApxImage2Provider()
    debug["provider_configured"] = provider.is_configured()
    if not provider.is_configured():
        debug["skipped_reason"] = (
            "APX_IMAGE2_ENABLED + APX_IMAGE2_API_KEY not set; using local Pillow only."
        )
        _emit("generate_slide_images", "done",
              "Skipped — APX_IMAGE2_* not configured; Pillow only.")
        return {}, debug

    slides = slide_plan.get("slides") or []
    if not slides:
        debug["skipped_reason"] = "slide_plan empty"
        _emit("generate_slide_images", "done", "No slides to render.")
        return {}, debug

    try:
        concurrency = int(os.getenv("APX_IMAGE2_CONCURRENCY", "4"))
    except Exception:
        concurrency = 4
    concurrency = max(1, min(concurrency, len(slides)))
    debug["concurrency"] = concurrency
    debug["called"] = True
    debug["requested"] = len(slides)

    _emit("generate_slide_images", "running",
          f"Calling gpt-image-2 for {len(slides)} slides "
          f"(concurrency={concurrency}, size={provider.default_size}, "
          f"quality={provider.default_quality})...")

    backgrounds_dir = image_video_dir / "image2_backgrounds"
    backgrounds_dir.mkdir(parents=True, exist_ok=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .image_providers.base import ImageProviderError

    def _one(slide: Dict[str, Any]) -> Tuple[int, Optional[bytes], Dict[str, Any]]:
        idx = int(slide.get("index") or 0)
        prompt = (slide.get("image_prompt") or "").strip()
        if not prompt:
            # Build a fallback image_prompt out of title/caption/visual_focus.
            bits = [
                slide.get("title") or "",
                slide.get("caption") or "",
                slide.get("visual_focus") or "",
            ]
            prompt = ". ".join(b for b in bits if b)
        if not prompt:
            return idx, None, {
                "index": idx, "ok": False,
                "error": "no image_prompt available",
            }
        try:
            rendered = provider.generate(prompt)
            return idx, rendered.png_bytes, {
                "index": idx, "ok": True,
                "width": rendered.width, "height": rendered.height,
                "bytes": len(rendered.png_bytes),
            }
        except ImageProviderError as exc:
            return idx, None, {"index": idx, "ok": False, "error": str(exc)}
        except Exception as exc:
            return idx, None, {
                "index": idx, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    images: Dict[int, "Image.Image"] = {}
    per_slide_debug: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_one, s) for s in slides]
        for fut in as_completed(futures):
            idx, png_bytes, info = fut.result()
            per_slide_debug.append(info)
            if not png_bytes:
                debug["failed"] += 1
                continue
            try:
                from io import BytesIO
                img = Image.open(BytesIO(png_bytes))
                img.load()
                images[idx] = img
                debug["succeeded"] += 1
                # Persist the raw image2 PNG for transparency / debugging.
                try:
                    (backgrounds_dir / f"slide_{idx:02d}_image2.png").write_bytes(png_bytes)
                except Exception:
                    pass
            except Exception as exc:
                debug["failed"] += 1
                info["ok"] = False
                info["error"] = (
                    f"PNG decode failed: {type(exc).__name__}: {exc}"
                )

    per_slide_debug.sort(key=lambda d: d.get("index") or 0)
    debug["per_slide"] = per_slide_debug

    _emit("generate_slide_images", "done",
          f"image2 returned {debug['succeeded']}/{debug['requested']} slides "
          f"(failed={debug['failed']}; failures fall back to Pillow per slide).")

    return images, debug


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

    # v0.6.4 — call gpt-image-2 for every slide concurrently (before the
    # Pillow render loop). Single-slide failures fall back to the Pillow
    # path automatically. Returns an empty dict when image2 is disabled
    # or the provider isn't configured.
    image2_backgrounds, image2_debug = _generate_image2_backgrounds(
        slide_plan=slide_plan,
        image_video_dir=image_video_dir,
        progress_cb=progress_cb,
    )
    image2_debug_path = image_video_dir / "image2_debug.json"
    try:
        image2_debug_path.write_text(
            json.dumps(image2_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    slide_paths: List[Path] = []
    image_sources: List[str] = []
    _emit("render_slide_overlays", "running",
          "Drawing on-screen titles and captions on each slide...")
    try:
        for slide, overlay in zip(slide_plan["slides"], overlay_plan["slides"]):
            slide_path = slides_dir / f"slide_{slide['index']:02d}.png"
            background = image2_backgrounds.get(int(slide.get("index") or 0))
            _render_slide(slide, overlay, chrome_label, slide_count,
                          slide_path, background=background)
            slide_paths.append(slide_path)
            image_sources.append("image2" if background is not None else "pillow_fallback")
        _emit("render_slide_overlays", "done",
              f"{slide_count} slide PNGs ready "
              f"(image2 backgrounds: {sum(1 for s in image_sources if s=='image2')}, "
              f"pillow fallbacks: {sum(1 for s in image_sources if s!='image2')}).")
    except Exception as exc:
        _emit("render_slide_overlays", "failed", f"Pillow overlay failed: {exc}")
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
            "media_api_called": bool(image2_debug.get("called")),
            "external_api_called": bool(
                llm_debug.get("called") or image2_debug.get("called")
            ),
            "seedance_called": False,
            "apx_called": False,
            "image2_called": bool(image2_debug.get("called")),
            "image2_succeeded": int(image2_debug.get("succeeded") or 0),
            "image2_failed": int(image2_debug.get("failed") or 0),
            "image2_requested": int(image2_debug.get("requested") or 0),
            "image2_disabled_by_env": bool(image2_debug.get("disabled_by_env")),
            "image2_skipped_reason": image2_debug.get("skipped_reason"),
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
            "media_api_called": bool(image2_debug.get("called")),
            "external_api_called": bool(
                llm_debug.get("called") or image2_debug.get("called")
            ),
            "seedance_called": False,
            "apx_called": False,
            "image2_called": bool(image2_debug.get("called")),
            "image2_succeeded": int(image2_debug.get("succeeded") or 0),
            "image2_failed": int(image2_debug.get("failed") or 0),
            "image2_requested": int(image2_debug.get("requested") or 0),
            "image2_disabled_by_env": bool(image2_debug.get("disabled_by_env")),
            "image2_skipped_reason": image2_debug.get("skipped_reason"),
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
        # v0.6.3 stabilization + v0.6.4: distinguish content LLM from media
        # generation. media_api_called flips to true ONLY when image2 was
        # actually contacted; per-slide image2 success/failure is in the
        # numeric counters and image2_per_slide debug list.
        "content_llm_called": bool(llm_debug.get("called")),
        "media_api_called": bool(image2_debug.get("called")),
        "external_api_called": bool(
            llm_debug.get("called") or image2_debug.get("called")
        ),
        "seedance_called": False,
        "apx_called": False,
        "image2_called": bool(image2_debug.get("called")),
        "image2_succeeded": int(image2_debug.get("succeeded") or 0),
        "image2_failed": int(image2_debug.get("failed") or 0),
        "image2_requested": int(image2_debug.get("requested") or 0),
        "image2_disabled_by_env": bool(image2_debug.get("disabled_by_env")),
        "image2_skipped_reason": image2_debug.get("skipped_reason"),
        "image2_debug_path": str(image2_debug_path),
        "image_sources": image_sources,
        "tts_called": False,
        "has_audio": False,
        "tts_status": "not_implemented_v0.6.3",
        "voiceover_source": "none",
        "image_source": (
            "image2" if (image2_debug.get("succeeded") or 0) > 0
            else "local_static_renderer"
        ),
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
