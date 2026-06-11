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


def _format_bgm_catalog_for_prompt(bgm_options: Optional[List[Dict[str, Any]]]) -> str:
    """Render the BGM manifest as a compact catalog the LLM can read.

    Returns an empty string when the catalog is empty so the prompt can
    skip the whole BGM section.
    """
    if not bgm_options:
        return ""
    lines: List[str] = []
    for entry in bgm_options:
        moods = ", ".join(entry.get("mood_keywords") or []) or "—"
        lines.append(
            f"  - filename: {entry['filename']}\n"
            f"      display_name: {entry.get('display_name') or entry['filename']}\n"
            f"      mood_keywords: {moods}\n"
            f"      tempo: {entry.get('tempo') or '—'}; energy: {entry.get('energy') or '—'}\n"
            f"      instruments: {entry.get('instruments') or '—'}\n"
            f"      fits: {entry.get('fits') or '—'}"
        )
    return "\n".join(lines)


def _build_llm_user_prompt(
    title: str,
    duration_seconds: int,
    slide_count: int,
    roles: List[str],
    bgm_options: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build the single user message we send to the LLM.

    Asks for one JSON object containing a per-slide list and a Chinese
    paragraph overview. We give the model the role sequence so it knows
    the narrative arc and can write content matching each beat.
    """
    bgm_catalog = _format_bgm_catalog_for_prompt(bgm_options)
    role_lines = "\n".join(
        f"  - slide {i+1} ({role})" for i, role in enumerate(roles)
    )
    return (
        "You are designing a short-form educational explainer video.\n"
        "The visual aesthetic is 'clean, bold, editorial' — simple, generous\n"
        "with negative space, designed to read on a phone in 1-2 seconds.\n"
        "\n"
        "UNIVERSAL CONSTRAINTS (apply to every video, every style):\n"
        "  - One single large subject sits in the center, occupying ~50–65%%\n"
        "    of the frame. The rest is generous negative space.\n"
        "  - English on-screen text is rendered AS PART OF the artwork in\n"
        "    the chosen medium (cut-paper letters / chalk-drawn letters /\n"
        "    flat type / collaged letters / risograph type — never a HTML\n"
        "    caption bar, never a watermark, never a translucent overlay).\n"
        "  - 16:9 landscape. No badges, no progress counters, no Chinese\n"
        "    characters anywhere on the canvas.\n"
        "  - All N slides for a single video share the SAME chosen art_style\n"
        "    + palette + background texture + mood. The video reads as one\n"
        "    visual world.\n"
        "\n"
        "ART STYLE — PICK ONE per video to match the topic's tone.\n"
        "Set art_style to exactly one of these IDs:\n"
        "\n"
        "  paper_craft\n"
        "    Layered cut-paper / torn-paper illustrations with soft drop\n"
        "    shadows, hand-cut edges, tactile material feel. Letters are\n"
        "    cut from coloured paper. The default Google-NotebookLM look.\n"
        "    Best for: stories, daily life, soft / human topics, kid-\n"
        "    friendly explainers, anything with emotional warmth.\n"
        "\n"
        "  flat_minimal\n"
        "    Clean minimal flat-vector illustration. Solid colour blocks,\n"
        "    1–2 px stroke outlines, simple geometric shapes, no texture,\n"
        "    no shadows, no gradients. Letters are bold sans-serif type.\n"
        "    Best for: math, logic, pure abstract concepts, programming,\n"
        "    statistics — anything where the idea is structural rather\n"
        "    than emotional.\n"
        "\n"
        "  editorial_collage\n"
        "    Magazine / newspaper editorial collage. Cut-out photo-style\n"
        "    fragments arranged with bold geometric shapes, mixed serif\n"
        "    + sans-serif type, hand-torn paper edges, halftone accents,\n"
        "    visible underlying grid. Letters are big editorial headline\n"
        "    type, sometimes overlapping the imagery.\n"
        "    Best for: business, economics, finance, marketing, social /\n"
        "    cultural topics, behavioural psychology.\n"
        "\n"
        "  risograph_print\n"
        "    Risograph / screen-print look: 2–3 limited inks (e.g. red +\n"
        "    blue, or fluorescent orange + black) with visible mis-register\n"
        "    offset, halftone dot texture, slightly grainy off-white paper,\n"
        "    chunky retro display type.\n"
        "    Best for: philosophy, history, literature, vintage / retro\n"
        "    topics, indie / cultural / counter-intuitive ideas.\n"
        "\n"
        "  chalkboard_sketch\n"
        "    Hand-drawn chalkboard or warm-cream notebook page. Loose\n"
        "    chalk / pen lines, hand-drawn arrows, simple cartoon icons,\n"
        "    handwritten labels. Subtle paper or slate texture. The\n"
        "    teacher-at-the-blackboard feel.\n"
        "    Best for: math derivations, physics, classic 'first-\n"
        "    principles' explainers, anything that wants to feel like\n"
        "    a great teacher walking you through a problem.\n"
        "\n"
        "Pick the style honestly — vary across videos. Don't default to\n"
        "paper_craft every time. A finance topic looks better in\n"
        "editorial_collage; a probability topic looks better in\n"
        "flat_minimal; a Greek philosophy topic looks better in\n"
        "risograph_print or chalkboard_sketch.\n"
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
        "       a) The chosen art_style ID (paper_craft / flat_minimal /\n"
        "          editorial_collage / risograph_print / chalkboard_sketch)\n"
        "          and the medium reminder appropriate for that style\n"
        "          (e.g. for paper_craft: 'cut-paper, soft drop shadows';\n"
        "          for chalkboard_sketch: 'chalk lines on slate, slight\n"
        "          dust';  for risograph_print: 'visible mis-register, halftone\n"
        "          dots, slightly grainy paper').\n"
        "       b) Background texture and color you have CHOSEN for this\n"
        "          topic — be specific. Pick ONE, not 'either A or B'.\n"
        "       c) Palette of 3–5 specific colors with hex codes you've\n"
        "          chosen for THIS topic.\n"
        "       d) Mood / lighting (e.g. 'cautionary, low-key' /\n"
        "          'cheerful, bright' / 'mysterious, low-contrast').\n"
        "       e) The composition rules that apply to every slide:\n"
        "          single centered subject ≈60%% of frame, generous\n"
        "          negative space, no text bands, no badges, no progress\n"
        "          counters, no Chinese characters, English text only,\n"
        "          rendered AS PART of the chosen medium (e.g. cut-paper\n"
        "          letters / chalk-drawn letters / flat type / collaged\n"
        "          letters / risograph type), 16:9 landscape.\n"
        "  6. image_prompt for each slide MUST start with the literal\n"
        "     string '<USE ART_DIRECTION>' (5 words including angle\n"
        "     brackets) — the pipeline will replace that token with the\n"
        "     shared art_direction text before sending to gpt-image-2.\n"
        "     After that token, describe in 50–90 words THIS slide's\n"
        "     specific subject: what object/scene appears (in the chosen\n"
        "     medium — cut-paper / flat-vector / collage / riso / chalk),\n"
        "     how it's positioned, and the exact English on-screen text\n"
        "     the image must render as part of the composition (e.g.\n"
        "     'Bold chalk-drawn English title \\\"WHY DOES IT REPEAT?\\\"\n"
        "     sits across the upper third'). Do NOT repeat the palette /\n"
        "     background / mood here — those live in art_direction. Just\n"
        "     the slide-specific scene + text.\n"
        "  6b. SUBTITLE SAFE-AREA — burned-in narration subtitles will\n"
        "      be overlaid on the BOTTOM 22% of the frame at runtime. To\n"
        "      avoid covering the slide's on-screen text or focal point,\n"
        "      EVERY image_prompt MUST keep all rendered text and the\n"
        "      central subject in the upper 70% of the frame. Allowed\n"
        "      text positions: 'across the upper third', 'top-left\n"
        "      banner', 'top-right banner', 'mid-left third', 'mid-right\n"
        "      third', 'centered just above the middle'. Never write\n"
        "      'bottom', 'lower third', 'across the bottom band', or any\n"
        "      similar bottom-area phrasing — that area is reserved for\n"
        "      subtitles.\n"
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
        "  9. bgm_choice — pick one BGM track from the catalog below by\n"
        "     filename (the post-processing pipeline will mux it under the\n"
        "     finished video). Pick whichever track best matches the\n"
        "     emotional tone you wrote in art_direction. Mood and topic\n"
        "     should agree: cautionary topic → reflective / lounge track,\n"
        "     cheerful topic → uplifting / kid-friendly track, awe-leaning\n"
        "     topic → harp / new-age / cinematic track. Always include a\n"
        "     short why (≤ 18 words) explaining the match.\n"
        f"  9b. narration_line — for EACH slide, write exactly ONE\n"
        "      English sentence (8 to 22 words) that the narrator will\n"
        "      speak WHILE THIS SLIDE'S IMAGE IS ON SCREEN. The line MUST\n"
        "      be about the same idea as the slide's title / caption /\n"
        "      visual_focus — viewers will SEE the image and HEAR this\n"
        "      sentence at the same time, so they MUST match. End with a\n"
        "      period, question mark, or exclamation point. No stage\n"
        "      directions, no '[pause]' tags, no slide numbers, no SSML.\n"
        "      Use everyday words a curious learner would understand.\n"
        "      The full narration is automatically built by joining all\n"
        f"      narration_line values in slide order; aim for {max(8, int(duration_seconds * 2.6 / max(slide_count, 1)))}-{max(12, int(duration_seconds * 3.0 / max(slide_count, 1)))}\n"
        f"      words per slide so the total fills the {duration_seconds}-\n"
        "      second video at ~150 wpm without leaving dead air.\n"
        "      WRITING A SHORT narration_line LEAVES SILENCE WHILE THE\n"
        "      SLIDE IS ON SCREEN AND IS A FAILURE.\n"
        "  10. IMAGE MODERATION SAFETY — every image_prompt is sent to a\n"
        "      hosted image generator that runs an Azure-style content\n"
        "      filter. Phrases that look harmless to a human can trip the\n"
        "      'self-harm', 'violence', or 'sexual' filters and get the\n"
        "      whole request rejected. To stay safe, you MUST avoid all of\n"
        "      these words and concepts in image_prompt fields:\n"
        "        - rope / noose / hanging / dangling rope / rope around\n"
        "        - blood / wound / bleeding / cut / knife / blade / sword\n"
        "        - gun / pistol / rifle / weapon / shooting / shot\n"
        "        - die / death / dead / kill / killed / corpse / grave\n"
        "        - jumping off / falling from a height / cliff edge\n"
        "        - pills / overdose / drugs / syringe / needle\n"
        "        - fire consuming a person / burning person\n"
        "        - any depiction of bodily harm to a person\n"
        "      Even when the topic is metaphorically about giving up,\n"
        "      letting go, sacrifice, loss, or risk, you MUST illustrate\n"
        "      these ideas with NEUTRAL paper-craft objects: open hands,\n"
        "      doors, paths, scales, jars, calendars, chess pieces, coins,\n"
        "      bridges, keys, gates, balloons, leaves, flags, signposts,\n"
        "      empty/full vessels. Concept of 'release' = an open hand or\n"
        "      paper balloon drifting up. Concept of 'sacrifice' = a chess\n"
        "      knight tipping over, or a single coin set aside. Concept of\n"
        "      'failure' = a paper graph dipping. NEVER use rope, noose,\n"
        "      blood, weapons, or harm imagery — even tastefully — because\n"
        "      the filter does not understand metaphor.\n"
        "      No human figures in distress. No dark dripping liquids.\n"
        "      No bandages. No hospital beds. No tombstones. No skulls.\n"
        "  11. Output a SINGLE JSON object — no markdown fence, no prose\n"
        "      outside the JSON.\n"
        "\n"
        + (
            "BGM catalog (pick one filename for bgm_choice.filename):\n"
            f"{bgm_catalog}\n\n"
            if bgm_catalog else
            "BGM catalog: none provided — set bgm_choice to null.\n\n"
        )
        + "Schema:\n"
        "{\n"
        "  \"video_title_en\": string (<= 9 words, English),\n"
        "  \"hook_question_en\": string (<= 18 words, English),\n"
        "  \"answer_en\": string (<= 22 words, the actual answer),\n"
        "  \"overview_cn\": string (Chinese paragraph, 4-7 sentences),\n"
        "  \"art_style\": one of \"paper_craft\" | \"flat_minimal\" | "
        "\"editorial_collage\" | \"risograph_print\" | \"chalkboard_sketch\",\n"
        "  \"art_direction\": string (60-100 words, shared by all slides),\n"
        "  \"bgm_choice\": { \"filename\": string-from-catalog,"
        " \"why\": string (<= 18 words) } | null,\n"
        "  \"slides\": [\n"
        "    { \"index\": 1,\n"
        "      \"role\": \"hook\",\n"
        "      \"title\": string,\n"
        "      \"caption\": string,\n"
        "      \"highlight\": string,\n"
        "      \"visual_focus\": string,\n"
        "      \"badge\": string (<= 2 words, English),\n"
        "      \"narration_line\": string (8-22 words, one English sentence the narrator speaks WHILE this slide is on screen — MUST match this slide's idea),\n"
        "      \"image_prompt\": string (40-90 words, detailed) },\n"
        "    ... one entry per slide, in order ...\n"
        "  ]\n"
        "}\n"
    )


def _safe_rewrite_image_prompt(
    failing_prompt: str,
    moderation_error: str,
    slide_title: str,
    slide_caption: str,
    slide_role: str,
    art_direction: str,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """v0.6.5.2 — when the image2 gateway rejects a prompt for moderation
    reasons, ask the LLM to rewrite ONLY that prompt with safer wording.
    Returns ``(rewritten_prompt_or_None, debug)``. Never raises.

    The new prompt is constrained to keep the same paper-craft art
    direction, the same on-screen English text, and the same role/scene
    intent — but with all moderation triggers (rope, blood, weapons,
    death, harm) swapped for neutral metaphors (open hand, scale, gate,
    chess piece, balloon, etc.).
    """
    debug: Dict[str, Any] = {
        "called": False,
        "fallback_reason": None,
        "rewrite_chars": 0,
    }
    api_key, _ = _resolve_llm_api_key()
    base_url = os.getenv("AI_VIDEO_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("AI_VIDEO_LLM_MODEL", "gpt-5-chat")
    try:
        timeout = int(os.getenv("AI_VIDEO_LLM_TIMEOUT", "60"))
    except Exception:
        timeout = 60
    if not api_key:
        debug["fallback_reason"] = "AI_VIDEO_LLM_API_KEY not configured"
        return None, debug
    if (os.getenv("IMAGE_VIDEO_DISABLE_LLM") or "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        debug["fallback_reason"] = "IMAGE_VIDEO_DISABLE_LLM enabled"
        return None, debug

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        debug["fallback_reason"] = f"openai package unavailable: {exc}"
        return None, debug

    user_prompt = (
        "An image generation request was REJECTED by the content moderation\n"
        "filter. Rewrite the image_prompt below so it conveys the same\n"
        "educational meaning but with NEUTRAL paper-craft imagery only.\n"
        "\n"
        "Banned (must NOT appear, even metaphorically):\n"
        "  rope, noose, hanging, blood, wound, cut, knife, blade, sword,\n"
        "  gun, pistol, weapon, die, death, dead, kill, killed, corpse,\n"
        "  grave, tombstone, skull, syringe, pills, drug, overdose,\n"
        "  jumping off, cliff edge, falling from, burning person, bandage,\n"
        "  hospital bed, body in distress.\n"
        "\n"
        "Safe replacements you SHOULD use:\n"
        "  open hand letting a paper balloon drift up = release / letting go\n"
        "  a single coin set aside, scales tipping = sacrifice / trade-off\n"
        "  chess piece tipped over = giving up / surrender\n"
        "  a paper door opening, a paper key turning = opportunity\n"
        "  a paper graph line dipping then rising = setback / recovery\n"
        "  empty paper jar, full paper jar = scarcity vs abundance\n"
        "  paper signpost, paper crossroads = decision\n"
        "  paper bridge, paper path = transition\n"
        "\n"
        f"Slide role: {slide_role}\n"
        f"On-screen title (must still appear in the artwork verbatim): {slide_title}\n"
        f"On-screen caption (informs the visual but is NOT drawn into the image): {slide_caption}\n"
        f"Shared art direction (preserve palette + paper-craft medium):\n"
        f"  {art_direction}\n"
        "\n"
        f"Original (rejected) image_prompt:\n"
        f"  {failing_prompt}\n"
        "\n"
        f"Moderation error from the gateway:\n"
        f"  {moderation_error[:400]}\n"
        "\n"
        "Output ONE JSON object with a single field: "
        "{\"image_prompt\": \"<the rewritten prompt, 60-110 words, "
        "preserves art direction + on-screen title>\"}. No markdown, no prose."
    )

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    except Exception as exc:
        debug["fallback_reason"] = f"OpenAI client init failed: {exc}"
        return None, debug

    debug["called"] = True
    try:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content":
                        "You rewrite image-generation prompts to bypass content "
                        "moderation while preserving educational intent. Output "
                        "strict JSON only."},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=1024,
                temperature=0.4,
            )
        except Exception:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content":
                        "You rewrite image-generation prompts to bypass content "
                        "moderation while preserving educational intent. Output "
                        "strict JSON only."},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.4,
            )
    except Exception as exc:
        debug["fallback_reason"] = f"safe-rewrite LLM call failed: {exc}"
        return None, debug

    raw_text = resp.choices[0].message.content if resp and resp.choices else None
    if not raw_text:
        debug["fallback_reason"] = "safe-rewrite returned empty content"
        return None, debug
    debug["rewrite_chars"] = len(raw_text)

    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            debug["fallback_reason"] = "safe-rewrite response was not JSON"
            return None, debug
        try:
            data = json.loads(match.group(0))
        except Exception as exc:
            debug["fallback_reason"] = f"safe-rewrite JSON parse failed: {exc}"
            return None, debug
    new_prompt = str(data.get("image_prompt") or "").strip()
    if not new_prompt:
        debug["fallback_reason"] = "safe-rewrite missing image_prompt field"
        return None, debug
    return new_prompt[:2400], debug


def _call_llm_for_slide_content(
    title: str,
    duration_seconds: int,
    slide_count: int,
    roles: List[str],
    bgm_options: Optional[List[Dict[str, Any]]] = None,
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

    user_prompt = _build_llm_user_prompt(
        title, duration_seconds, slide_count, roles,
        bgm_options=bgm_options,
    )

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
    # v0.6.6 — LLM picks one of 5 art styles per video. Validate the
    # value; anything off-list defaults to paper_craft for backward
    # compatibility with v0.6.4-era videos.
    _ALLOWED_ART_STYLES = {
        "paper_craft", "flat_minimal", "editorial_collage",
        "risograph_print", "chalkboard_sketch",
    }
    art_style_raw = str(data.get("art_style") or "").strip().lower().replace("-", "_")
    art_style = art_style_raw if art_style_raw in _ALLOWED_ART_STYLES else "paper_craft"

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
        narration_line = str(item.get("narration_line") or "").strip()
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

        # v0.6.7.2 — fall back to caption when narration_line is missing,
        # so older LLM outputs still produce some audio. Strip trailing
        # punctuation that's missing and add one sentence-end mark.
        if not narration_line:
            narration_line = caption
        narration_line = narration_line[:240].strip()
        if narration_line and narration_line[-1] not in ".!?":
            narration_line += "."

        cleaned_slides.append({
            "index": i + 1,
            "role": roles[i] if i < len(roles) else "explanation",
            "title": title[:80],
            "caption": caption[:160],
            "highlight": (highlight or title)[:60],
            "visual_focus": visual_focus[:140],
            "badge": (badge or roles[i].title())[:24],
            "narration_line": narration_line,
            "image_prompt_template": image_prompt_raw[:1500],
            "image_prompt": image_prompt_resolved[:2400],
        })
    overview_cn = str(data.get("overview_cn") or "").strip()

    # v0.6.5 — pull the LLM's bgm_choice. The pipeline post-validates the
    # filename against the manifest in audio_providers.bgm_selector, so we
    # only sanity-clean the field shape here.
    bgm_choice_raw = data.get("bgm_choice")
    bgm_choice: Optional[Dict[str, str]] = None
    if isinstance(bgm_choice_raw, dict):
        chosen_filename = str(bgm_choice_raw.get("filename") or "").strip()
        chosen_why = str(bgm_choice_raw.get("why") or "").strip()
        if chosen_filename:
            bgm_choice = {
                "filename": chosen_filename[:200],
                "why": chosen_why[:160],
            }

    # v0.6.7.2 — narration_script_en is now BUILT from per-slide
    # narration_line values, so the audio is guaranteed to be in the
    # same order as the images, and TTS sentence boundaries map 1:1 to
    # slides. We still accept top-level narration_script_en (legacy /
    # fallback) but the per-slide path takes precedence.
    per_slide_lines = [s.get("narration_line", "").strip() for s in cleaned_slides]
    per_slide_lines = [ln for ln in per_slide_lines if ln]
    if per_slide_lines:
        narration_script_en = " ".join(per_slide_lines)
    else:
        narration_script_en = str(data.get("narration_script_en") or "").strip()

    return {
        "video_title_en": str(data.get("video_title_en") or "").strip()[:80],
        "hook_question_en": str(data.get("hook_question_en") or "").strip()[:160],
        "answer_en": str(data.get("answer_en") or "").strip()[:200],
        "overview_cn": overview_cn,
        "art_direction": art_direction,
        "art_style": art_style,
        "bgm_choice": bgm_choice,
        "narration_script_en": narration_script_en,
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

    _emit("generate_slide_images", "running", "0% In progress...")

    backgrounds_dir = image_video_dir / "image2_backgrounds"
    backgrounds_dir.mkdir(parents=True, exist_ok=True)

    import time as _time_mod
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .image_providers.base import ImageProviderError, TransientImageProviderError

    # v0.6.5.1 — retry config. Tail latency on the gateway makes single-shot
    # failures common (10-30% on 60-90s videos), and the v0.6.4 "fall back
    # to Pillow geometric template" policy was unacceptable visually. Now
    # every transient failure gets retried up to RETRY_MAX_ATTEMPTS times
    # with exponential backoff. The last attempt downgrades quality
    # (high → medium) so the gateway has a higher chance of returning in
    # time.
    try:
        retry_max_attempts = int(os.getenv("APX_IMAGE2_RETRY_ATTEMPTS", "3"))
    except Exception:
        retry_max_attempts = 3
    retry_max_attempts = max(1, min(retry_max_attempts, 5))
    retry_backoff_base = 2.0  # 2s, 4s, 8s

    def _one(slide: Dict[str, Any]) -> Tuple[int, Optional[bytes], Dict[str, Any]]:
        idx = int(slide.get("index") or 0)
        prompt = (slide.get("image_prompt") or "").strip()
        if not prompt:
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
                "attempts": 0, "transient_failures": 0,
            }

        attempts = 0
        transient_failures = 0
        last_error_str: str = ""
        while attempts < retry_max_attempts:
            attempts += 1
            # Final attempt downgrades quality so the gateway returns
            # faster — better a slightly-less-detailed paper-craft image
            # than a Pillow placeholder.
            if attempts == retry_max_attempts and attempts > 1:
                quality_for_attempt: Optional[str] = "medium"
            else:
                quality_for_attempt = None  # = use provider default

            # Retry attempts are silent in the UI — they don't bump the
            # aggregate progress (the slide hasn't completed yet) and
            # they don't print over the "N% In progress..." line. The
            # retry counter shows up in image2_debug.json after the run
            # for monitoring.
            try:
                rendered = provider.generate(prompt, quality=quality_for_attempt)
                return idx, rendered.png_bytes, {
                    "index": idx, "ok": True,
                    "width": rendered.width, "height": rendered.height,
                    "bytes": len(rendered.png_bytes),
                    "attempts": attempts,
                    "transient_failures": transient_failures,
                    "quality_used": quality_for_attempt or provider.default_quality,
                }
            except TransientImageProviderError as exc:
                transient_failures += 1
                last_error_str = str(exc)
                if attempts >= retry_max_attempts:
                    break
                # Exponential backoff before next attempt: 2s, 4s, 8s, ...
                sleep_for = retry_backoff_base * (2 ** (attempts - 1))
                try:
                    _time_mod.sleep(sleep_for)
                except Exception:
                    pass
                continue
            except ImageProviderError as exc:
                # Permanent (4xx, malformed response, etc.) — no retry.
                return idx, None, {
                    "index": idx, "ok": False,
                    "error": str(exc),
                    "attempts": attempts,
                    "transient_failures": transient_failures,
                    "permanent": True,
                }
            except Exception as exc:
                last_error_str = f"{type(exc).__name__}: {exc}"
                if attempts >= retry_max_attempts:
                    break
                sleep_for = retry_backoff_base * (2 ** (attempts - 1))
                try:
                    _time_mod.sleep(sleep_for)
                except Exception:
                    pass
                continue

        return idx, None, {
            "index": idx, "ok": False,
            "error": (
                f"image2 failed after {attempts} attempts "
                f"({transient_failures} transient): {last_error_str}"
            ),
            "attempts": attempts,
            "transient_failures": transient_failures,
            "permanent": False,
        }

    images: Dict[int, "Image.Image"] = {}
    per_slide_debug: List[Dict[str, Any]] = []
    total = len(slides)
    completed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_one, s) for s in slides]
        for fut in as_completed(futures):
            idx, png_bytes, info = fut.result()
            per_slide_debug.append(info)
            if not png_bytes:
                debug["failed"] += 1
            else:
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
            # Live progress beat: emit a "running" message every time a
            # slide finishes so the frontend can show "N / total slides"
            # and a derived percentage. The stage is kept in `running`
            # state until the loop ends; the final `done` emit overwrites
            # this last message with the real wall-clock duration.
            completed += 1
            try:
                progress_pct = int(round((completed / total) * 100)) if total else 0
                _emit(
                    "generate_slide_images", "running",
                    f"{progress_pct}% In progress...",
                )
            except Exception:
                pass

    # v0.6.5.2 — Layer 3: safe-rewrite-and-retry for slides that still
    # failed after the standard retry loop. We ask the LLM to rewrite the
    # image_prompt with safer wording, then call image2 once more. This
    # is the recovery step for moderation-triggered rejections that the
    # banned-words list (Layer 2 in the LLM system prompt) didn't already
    # prevent.
    failed_indices_before_rewrite = [
        p.get("index") for p in per_slide_debug if not p.get("ok")
    ]
    safe_rewrite_attempts = 0
    safe_rewrite_recovered = 0
    safe_rewrite_failed = 0
    safe_rewrite_log: List[Dict[str, Any]] = []

    if failed_indices_before_rewrite:
        # Build a quick lookup from slide.index → slide dict.
        slides_by_idx: Dict[int, Dict[str, Any]] = {
            int(s.get("index") or 0): s for s in slides
        }
        art_direction_for_rewrite = str(slide_plan.get("art_direction") or "")

        _emit(
            "generate_slide_images", "running",
            f"Recovering {len(failed_indices_before_rewrite)} blocked slide(s) "
            "with safer prompts...",
        )

        for failed_idx in failed_indices_before_rewrite:
            if not failed_idx:
                continue
            slide = slides_by_idx.get(int(failed_idx))
            if slide is None:
                continue
            # Find the existing per-slide debug entry so we can append.
            existing_entry = next(
                (p for p in per_slide_debug if p.get("index") == failed_idx),
                None,
            )
            original_error = (existing_entry or {}).get("error", "") if existing_entry else ""
            failing_prompt = str(slide.get("image_prompt") or "")
            slide_title = str(slide.get("title") or "")
            slide_caption = str(slide.get("caption") or "")
            slide_role = str(slide.get("role") or "")

            safe_rewrite_attempts += 1
            new_prompt, rewrite_debug = _safe_rewrite_image_prompt(
                failing_prompt=failing_prompt,
                moderation_error=original_error,
                slide_title=slide_title,
                slide_caption=slide_caption,
                slide_role=slide_role,
                art_direction=art_direction_for_rewrite,
            )
            entry_log: Dict[str, Any] = {
                "index": failed_idx,
                "rewrite_called": bool(rewrite_debug.get("called")),
                "rewrite_fallback_reason": rewrite_debug.get("fallback_reason"),
            }

            if not new_prompt:
                # LLM rewrite itself failed — bail; this slide stays failed.
                entry_log["recovered"] = False
                entry_log["recovery_failed_reason"] = (
                    rewrite_debug.get("fallback_reason") or "no rewrite produced"
                )
                safe_rewrite_failed += 1
                safe_rewrite_log.append(entry_log)
                continue

            # Update the slide_plan in place so downstream consumers see
            # the safer prompt. The original is preserved in
            # `image_prompt_template` already (untouched by this rewrite).
            slide["image_prompt"] = new_prompt
            entry_log["rewritten_prompt_chars"] = len(new_prompt)

            # Try image2 once more with the rewritten prompt + medium
            # quality (fastest tier — moderation is the bottleneck, not
            # render time).
            try:
                rendered = provider.generate(new_prompt, quality="medium")
                try:
                    from io import BytesIO
                    img = Image.open(BytesIO(rendered.png_bytes))
                    img.load()
                    images[int(failed_idx)] = img
                    debug["succeeded"] += 1
                    debug["failed"] = max(0, debug["failed"] - 1)
                    try:
                        (backgrounds_dir / f"slide_{int(failed_idx):02d}_image2.png").write_bytes(
                            rendered.png_bytes
                        )
                    except Exception:
                        pass
                    if existing_entry is not None:
                        existing_entry["ok"] = True
                        existing_entry["recovered_via_safe_rewrite"] = True
                        existing_entry["error"] = None
                        existing_entry["bytes"] = len(rendered.png_bytes)
                        existing_entry["width"] = rendered.width
                        existing_entry["height"] = rendered.height
                        existing_entry["quality_used"] = "medium"
                    safe_rewrite_recovered += 1
                    entry_log["recovered"] = True
                except Exception as exc:
                    safe_rewrite_failed += 1
                    entry_log["recovered"] = False
                    entry_log["recovery_failed_reason"] = (
                        f"PNG decode after rewrite: {type(exc).__name__}: {exc}"
                    )
            except Exception as exc:
                safe_rewrite_failed += 1
                entry_log["recovered"] = False
                entry_log["recovery_failed_reason"] = (
                    f"image2 still failed after rewrite: {type(exc).__name__}: {exc}"
                )

            safe_rewrite_log.append(entry_log)

        if safe_rewrite_recovered > 0:
            _emit(
                "generate_slide_images", "running",
                f"Recovered {safe_rewrite_recovered}/{safe_rewrite_attempts} "
                "blocked slide(s) via safe-rewrite.",
            )

    debug["safe_rewrite_attempts"] = safe_rewrite_attempts
    debug["safe_rewrite_recovered"] = safe_rewrite_recovered
    debug["safe_rewrite_failed"] = safe_rewrite_failed
    debug["safe_rewrite_log"] = safe_rewrite_log

    per_slide_debug.sort(key=lambda d: d.get("index") or 0)
    debug["per_slide"] = per_slide_debug

    # v0.6.5.1 — surface retry stats so we can monitor gateway tail latency.
    total_attempts = sum(int(p.get("attempts") or 0) for p in per_slide_debug)
    total_transient = sum(int(p.get("transient_failures") or 0) for p in per_slide_debug)
    total_extra_attempts = max(0, total_attempts - len(per_slide_debug))
    debug["retry_total_attempts"] = total_attempts
    debug["retry_extra_attempts"] = total_extra_attempts
    debug["retry_transient_failures"] = total_transient
    debug["retry_max_attempts_per_slide"] = retry_max_attempts

    retry_summary_parts: List[str] = []
    if total_extra_attempts > 0:
        retry_summary_parts.append(
            f"{total_extra_attempts} retry" + ("s" if total_extra_attempts != 1 else "")
        )
    if safe_rewrite_recovered > 0:
        retry_summary_parts.append(
            f"{safe_rewrite_recovered} safe-rewrite recover"
            + ("s" if safe_rewrite_recovered != 1 else "")
        )
    retry_summary = f" ({', '.join(retry_summary_parts)})" if retry_summary_parts else ""

    if debug["failed"] == 0:
        _emit("generate_slide_images", "done",
              f"image2 returned {debug['succeeded']}/{debug['requested']} slides"
              + retry_summary + ".")
    else:
        # Layer 4 — fail loud. Don't pretend the video is OK; the caller
        # turns route_status into 'failed' so the frontend tells the user
        # to regenerate. We do NOT mix Pillow geometric placeholders in
        # with image2 paper-craft.
        _emit("generate_slide_images", "failed",
              f"image2 could not produce {debug['failed']}/{debug['requested']} "
              "slide(s) even after retries and safe-rewrite. The pipeline "
              "will mark this run as failed instead of substituting a "
              "Pillow placeholder.")

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


def _format_ass_time(seconds: float) -> str:
    """ASS timestamps look like H:MM:SS.cc (centiseconds, not ms)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _wrap_sentence_to_lines(text: str, max_chars_per_line: int = 50, max_lines: int = 2) -> str:
    """Wrap a sentence into AT MOST ``max_lines`` lines.

    v0.6.7.2 — hard cap at 2 lines so the subtitle box never grows tall
    enough to push the visible top edge into the picture area. If a
    sentence is too long for 2 lines at ``max_chars_per_line``, we
    progressively widen the line budget (up to 80 chars) instead of
    spilling onto a 3rd line. This guarantees the box height is
    constant regardless of sentence length.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if len(text) <= max_chars_per_line:
        return text

    def _wrap_at(width: int) -> List[str]:
        words = text.split()
        out: List[str] = []
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if len(cand) <= width:
                cur = cand
                continue
            if cur:
                out.append(cur)
            cur = w
        if cur:
            out.append(cur)
        return out

    # Try increasing widths until we fit in max_lines lines.
    for width in (max_chars_per_line, 60, 70, 80):
        lines = _wrap_at(width)
        if len(lines) <= max_lines:
            return r"\N".join(lines)

    # Last resort — even at width 80 we have >max_lines lines. Greedily
    # merge until we hit max_lines (this is rare for ≤22-word sentences).
    lines = _wrap_at(80)
    while len(lines) > max_lines:
        i = min(range(len(lines) - 1), key=lambda j: len(lines[j]) + len(lines[j + 1]))
        lines[i] = (lines[i] + " " + lines[i + 1]).strip()
        del lines[i + 1]
    return r"\N".join(lines)


def _build_ass_subtitles(
    narration: str,
    total_duration_seconds: float,
    output_path: Path,
    font_size: int = 56,
    sentence_timings: Optional[List[Any]] = None,
) -> Tuple[Path, int]:
    """Generate an .ass subtitle file.

    v0.6.7.1 — when ``sentence_timings`` (list of objects with .text,
    .start_s, .end_s) is provided, each subtitle line uses the EXACT
    spoken time of that sentence. This guarantees the on-screen text is
    always synchronized with what the TTS is saying.

    Style: white text on a translucent black box (BorderStyle=3) so the
    subtitle stays readable over any image background. Bottom-center,
    auto-wrapped to ≤3 lines.

    When sentence_timings is missing/empty, we fall back to splitting
    the narration text on punctuation and time-evenly distributing
    across total_duration_seconds (legacy behavior, less synchronized).

    Returns ``(path, line_count)``.
    """
    # v0.6.7.3 — NO background box. The previous BorderStyle=3 (filled
    # box) approach made the subtitle look like a black bar covering the
    # picture, no matter how transparent BackColour was — libass's
    # treatment of BackColour alpha for BorderStyle=3 isn't reliable
    # across renderers, and a 100%-clear box is just text-on-image
    # anyway. Better: use BorderStyle=1 (outline + shadow ONLY, no box)
    # with a thick black outline + soft shadow so white text is readable
    # on ANY background — and the picture is 100% visible underneath.
    #
    # ASS color encoding is &HAABBGGRR (alpha-blue-green-red, hex).
    # AA: 00 = opaque, FF = fully transparent.
    #   PrimaryColour: &H00FFFFFF (opaque white text)
    #   OutlineColour: &H00000000 (opaque black outline)
    #   BackColour:    &H80000000 (drop-shadow color, 50% transparent)
    # BorderStyle=1 = outline + shadow (no fill box).
    # Outline=5 = thick black halo around every glyph (readable on any bg).
    # Shadow=2  = soft drop shadow for extra contrast on busy images.
    #
    # Position: per-Dialogue `\pos(960, 1010)` with Alignment=2
    # (bottom-center anchor) → the BOTTOM-CENTER of the subtitle is
    # locked at (960, 1010). 1-line, 2-line subtitles all share the
    # same bottom edge → the visual "position" no longer jumps.
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,60,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    # Bottom-center anchor for Alignment=2 → \pos(x, y) where (x, y)
    # is the BOTTOM-CENTER of the rendered text. y=1010 keeps the
    # subtitle 70 px clear of the 1080-px frame bottom, regardless of
    # whether it wraps to 1 line or 2.
    SUB_X, SUB_Y = 960, 1010
    pos_tag = f"{{\\pos({SUB_X},{SUB_Y})}}"

    events: List[str] = []

    if sentence_timings:
        # Sync mode: each line has the exact start/end time of its sentence.
        for st in sentence_timings:
            start = max(0.0, float(getattr(st, "start_s", 0.0)))
            end = max(start + 0.05, float(getattr(st, "end_s", start + 0.05)))
            text = (getattr(st, "text", "") or "").strip()
            if not text:
                continue
            wrapped = _wrap_sentence_to_lines(text)
            safe_line = wrapped.replace("{", "(").replace("}", ")")
            events.append(
                f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
                f"Default,,0,0,0,,{pos_tag}{safe_line}"
            )
    else:
        # Fallback (no timings) — split by sentence punctuation and
        # time-evenly distribute. Used only if SentenceBoundary events
        # didn't arrive.
        text = re.sub(r"\s+", " ", narration or "").strip()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences or total_duration_seconds <= 0:
            output_path.write_text(header, encoding="utf-8")
            return output_path, 0
        per_line = total_duration_seconds / len(sentences)
        for i, sent in enumerate(sentences):
            start = i * per_line
            end = (i + 1) * per_line
            wrapped = _wrap_sentence_to_lines(sent)
            safe_line = wrapped.replace("{", "(").replace("}", ")")
            events.append(
                f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
                f"Default,,0,0,0,,{pos_tag}{safe_line}"
            )

    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return output_path, len(events)


def _compose_with_ffmpeg(
    ffmpeg_bin: str,
    slide_paths: List[Path],
    duration_per_slide: float,
    output_path: Path,
    work_dir: Path,
    bgm_path: Optional[Path] = None,
    bgm_volume_db: float = -15.0,
    total_duration_seconds: Optional[float] = None,
    narration_path: Optional[Path] = None,
    narration_duration_seconds: float = 0.0,
    bgm_base_volume_db: float = -15.0,
    subtitles_path: Optional[Path] = None,
    per_slide_durations: Optional[List[float]] = None,
) -> Tuple[bool, str, List[str], Path]:
    """Concat slide PNGs into an mp4 using the ffmpeg concat demuxer.

    v0.6.5 — when ``bgm_path`` is provided, the BGM mp3 is muxed in as a
    second input.
    v0.6.7 — when ``narration_path`` is provided, the narration mp3 is
    muxed at full volume and the BGM (if any) is auto-ducked. When
    ``subtitles_path`` is provided, the .ass file is burned into the
    video via the subtitles filter.

    Audio mix logic:
      - narration only            → narration at 0 dB
      - narration + BGM           → narration at 0 dB, BGM ducked + faded
      - BGM only (legacy v0.6.5)  → BGM at bgm_volume_db, fade-out 1s
      - none                      → silent video (no audio track)

    Returns ``(ok, message, ffmpeg_args, concat_txt_path)``.
    """
    concat_txt = work_dir / "concat.txt"
    lines: List[str] = []
    # v0.6.7.2 — when per_slide_durations is provided (one duration per
    # slide, derived from edge-tts sentence_timings), each slide stays on
    # screen for exactly the time the narrator spends on its sentence.
    # This guarantees image↔narration alignment: when the narrator says
    # sentence N, slide N is on screen.
    if per_slide_durations is not None and len(per_slide_durations) == len(slide_paths):
        for p, d in zip(slide_paths, per_slide_durations):
            lines.append(f"file '{p.resolve().as_posix()}'")
            lines.append(f"duration {max(0.4, float(d)):.4f}")
    else:
        for p in slide_paths:
            lines.append(f"file '{p.resolve().as_posix()}'")
            lines.append(f"duration {duration_per_slide:.4f}")
    # FFmpeg concat demuxer requires the last file to be repeated without a
    # duration line so the final frame holds for the right amount of time.
    if slide_paths:
        lines.append(f"file '{slide_paths[-1].resolve().as_posix()}'")
    concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    args: List[str] = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_txt.resolve()),
    ]

    # Track input indexes as we add them.
    narration_idx: Optional[int] = None
    bgm_idx: Optional[int] = None
    next_idx = 1

    if narration_path is not None:
        narration_idx = next_idx
        next_idx += 1
        args.extend(["-i", str(narration_path.resolve())])

    if bgm_path is not None:
        bgm_idx = next_idx
        next_idx += 1
        args.extend([
            "-stream_loop", "-1",
            "-i", str(bgm_path.resolve()),
        ])

    # Compute fade-out start for BGM tail (so music doesn't hard-cut).
    fade_dur = 1.0
    if total_duration_seconds is not None and total_duration_seconds > fade_dur:
        fade_start = max(0.0, total_duration_seconds - fade_dur)
    else:
        est_dur = max(0.0, len(slide_paths) * duration_per_slide)
        fade_start = max(0.0, est_dur - fade_dur)

    # Subtitle filter is part of the video chain. ffmpeg's filter
    # parser is finicky about paths in two ways:
    #   1. spaces in absolute paths (e.g. "/Users/tal/Desktop/Claude Code/")
    #      are not reliably honored even with single-quotes around the value,
    #   2. `ass=subtitles.ass` (where the value contains a `.ass` extension)
    #      gets parsed weirdly because `subtitles` is also a filter name.
    # The bullet-proof workaround: copy the .ass to /tmp with a simple
    # alphanumeric name, then reference it via the `subtitles` filter
    # using the explicit `filename=` keyword. No spaces, no ambiguity.
    subtitle_filter = ""
    subtitle_tmp_path: Optional[Path] = None
    if subtitles_path is not None and subtitles_path.exists():
        # Use the parent directory's stable name as a unique-ish suffix
        # so concurrent runs don't clobber each other's tmp file.
        unique_id = work_dir.name[:32] if work_dir else "run"
        subtitle_tmp_path = Path("/tmp") / f"aivideo_subs_{unique_id}.ass"
        try:
            shutil.copyfile(str(subtitles_path), str(subtitle_tmp_path))
            subtitle_filter = f",subtitles=filename={subtitle_tmp_path.as_posix()}"
        except Exception:
            # If even the /tmp copy fails, drop subtitles silently rather
            # than blowing up the whole compose.
            subtitle_filter = ""
    video_filter = f"fps={FPS},format=yuv420p{subtitle_filter}"

    if narration_idx is not None and bgm_idx is not None:
        # Narration + BGM. Three-stage BGM volume curve so the music
        # supports the speech and then returns once the narrator stops:
        #   [0, narration_end]  → ducked (bgm_volume_db, e.g. -22 dB)
        #   ramp 0.6 s          → base BGM volume
        #   [narration_end+ramp, fade_start] → base volume
        #   [fade_start, end]   → linear fade-out 1 s
        narr_end = max(0.0, float(narration_duration_seconds or 0.0))
        ramp = 0.6
        ramp_end = narr_end + ramp
        base_db = float(bgm_base_volume_db)
        duck_db = float(bgm_volume_db)
        if narr_end > 0.0 and ramp_end < fade_start:
            # volume expression on the BGM stream (in dB):
            #   t < narr_end                → duck
            #   narr_end <= t < ramp_end    → linear interp duck → base
            #   t >= ramp_end               → base
            # ffmpeg's volume filter accepts an expression with `t`.
            vol_expr = (
                f"if(lt(t,{narr_end:.3f}),{duck_db:.2f},"
                f"if(lt(t,{ramp_end:.3f}),"
                f"{duck_db:.2f}+({base_db:.2f}-({duck_db:.2f}))*(t-{narr_end:.3f})/{ramp:.3f},"
                f"{base_db:.2f}))"
            )
            bgm_chain = (
                f"[{bgm_idx}:a]volume='{vol_expr}':eval=frame,"
                f"afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f}[bgm]"
            )
        else:
            # Narration covers the whole clip (or no narration timing) →
            # legacy single-volume duck.
            bgm_chain = (
                f"[{bgm_idx}:a]volume={duck_db:.1f}dB,"
                f"afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f}[bgm]"
            )
        narr_chain = f"[{narration_idx}:a]volume=0dB[narr]"
        mix_chain = "[narr][bgm]amix=inputs=2:duration=longest:dropout_transition=0[a]"
        filter_complex = ";".join([narr_chain, bgm_chain, mix_chain])
        args.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[a]",
            "-vf", video_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path.resolve()),
        ])
    elif narration_idx is not None:
        # Narration only.
        narr_chain = f"[{narration_idx}:a]volume=0dB[a]"
        args.extend([
            "-filter_complex", narr_chain,
            "-map", "0:v",
            "-map", "[a]",
            "-vf", video_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path.resolve()),
        ])
    elif bgm_idx is not None:
        # BGM only — legacy v0.6.5 path.
        bgm_filter = (
            f"[{bgm_idx}:a]volume={bgm_volume_db:.1f}dB,"
            f"afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f}[a]"
        )
        args.extend([
            "-filter_complex", bgm_filter,
            "-map", "0:v",
            "-map", "[a]",
            "-vf", video_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path.resolve()),
        ])
    else:
        # Silent video.
        args.extend([
            "-vf", video_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path.resolve()),
        ])

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
            "tts_status": "not_started",
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
            "tts_status": "not_started",
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

    # v0.6.5 — load the local BGM manifest so we can hand the LLM a
    # short catalog of available tracks and let it pick one as part of
    # the same JSON response. The LLM never listens to the mp3 itself.
    # When BGM is disabled by env, we still call the LLM but pass an
    # empty catalog so the model knows to set bgm_choice to null.
    from web.audio_providers import bgm_disabled_by_env, load_bgm_manifest
    bgm_options_for_llm: List[Dict[str, Any]] = []
    bgm_manifest_debug: Dict[str, Any] = {
        "loaded": False,
        "disabled_by_env": False,
        "track_count": 0,
    }
    if bgm_disabled_by_env():
        bgm_manifest_debug["disabled_by_env"] = True
    else:
        bgm_tracks_for_llm, _bgm_default, bgm_manifest_inner = load_bgm_manifest()
        bgm_manifest_debug["loaded"] = bool(bgm_manifest_inner.get("manifest_exists"))
        bgm_manifest_debug["track_count"] = len(bgm_tracks_for_llm)
        bgm_options_for_llm = [
            {
                "filename": t.filename,
                "display_name": t.display_name,
                "mood_keywords": list(t.mood_keywords or []),
                "fits": t.fits,
                "tempo": t.tempo,
                "energy": t.energy,
                "instruments": t.instruments,
            }
            for t in bgm_tracks_for_llm
        ]

    # v0.6.3 — call the configured AI_VIDEO_LLM_* model (gpt-5-chat by default)
    # to write per-slide content tailored to the user's topic and a Chinese
    # paragraph overview. Fall back to the static template on any failure so
    # the video always renders. This LLM is NOT a forbidden API — APX,
    # Seedance, Image2, and TTS remain off.
    _emit("write_slide_content", "running",
          "Calling AI_VIDEO_LLM_* for slide titles, captions, image prompts, and BGM choice...")
    llm_content, llm_debug = _call_llm_for_slide_content(
        title=title_clean,
        duration_seconds=duration_seconds,
        slide_count=slide_count,
        roles=roles,
        bgm_options=bgm_options_for_llm,
    )
    if llm_content:
        _emit("write_slide_content", "done",
              f"AI wrote {len(llm_content.get('slides', []))} slide blocks "
              f"+ Chinese overview + BGM choice.")
    else:
        _emit("write_slide_content", "done",
              f"Static template used ({llm_debug.get('fallback_reason') or 'fallback'}).")

    # v0.6.5 — resolve the BGM choice into a real on-disk path. This stage
    # is fast (file existence check + manifest lookup) but we still emit a
    # progress beat so the user sees it as a distinct step. When BGM is
    # disabled, we still mark the stage done so the UI is honest.
    from web.audio_providers import resolve_bgm_track
    _emit("select_bgm", "running", "Picking BGM from local library...")
    llm_bgm_choice = (llm_content or {}).get("bgm_choice") or {}
    chosen_filename_for_bgm = (
        str(llm_bgm_choice.get("filename") or "").strip() if isinstance(llm_bgm_choice, dict) else ""
    )
    bgm_track, bgm_debug = resolve_bgm_track(chosen_filename_for_bgm or None)
    bgm_debug["manifest_loaded"] = bgm_manifest_debug
    if bgm_track is not None:
        _emit("select_bgm", "done",
              f"Selected BGM: {bgm_track.display_name} ({bgm_track.filename}).")
    else:
        if bgm_debug.get("disabled_by_env"):
            _emit("select_bgm", "done",
                  "Skipped — IMAGE_VIDEO_DISABLE_BGM set; final video will be silent.")
        else:
            _emit("select_bgm", "done",
                  f"No BGM resolved ({bgm_debug.get('fallback_reason') or 'unknown'}); "
                  "final video will be silent.")

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

    # v0.6.5.2 — Layer 4: fail-loud. If image2 was actually configured
    # and tried (i.e. the user expects real images), and any slide is
    # still missing after the retry + safe-rewrite layers, abort the
    # whole run. We do NOT silently substitute a Pillow geometric
    # placeholder for the failed slide — that produced visually
    # inconsistent videos that the user (correctly) called unacceptable.
    image2_attempted_real = (
        bool(image2_debug.get("called"))
        and not image2_debug.get("disabled_by_env")
    )
    image2_unrecovered = int(image2_debug.get("failed") or 0)
    if image2_attempted_real and image2_unrecovered > 0:
        failed_indices = [
            p.get("index") for p in (image2_debug.get("per_slide") or [])
            if not p.get("ok")
        ]
        moderation_blocked = any(
            "moderation" in str(p.get("error") or "").lower()
            or "safety" in str(p.get("error") or "").lower()
            or "content_policy" in str(p.get("error") or "").lower()
            for p in (image2_debug.get("per_slide") or [])
            if not p.get("ok")
        )
        error_msg = (
            f"image2 could not produce {image2_unrecovered} of "
            f"{image2_debug.get('requested')} slide image(s) "
            f"({failed_indices}) even after retries and safe-rewrite. "
            "The pipeline refuses to substitute a Pillow placeholder. "
            "Click Generate to try again — this often succeeds because "
            "the gateway's content moderation is non-deterministic."
        )
        if moderation_blocked:
            error_msg += (
                " Tip: rephrase the topic to avoid any words the image "
                "moderation filter could associate with self-harm, "
                "violence, or other restricted categories."
            )
        return {
            "generation_method": "image_video",
            "route_status": "failed",
            "duration_seconds": duration_seconds,
            "slide_count": slide_count,
            "slide_plan_path": str(slide_plan_path),
            "overlay_plan_path": str(overlay_plan_path),
            "slides_dir": str(slides_dir),
            "final_video_path": None,
            "error": error_msg,
            "ffmpeg_found": None,
            "ffmpeg_path": None,
            "ffmpeg_diagnostics": None,
            "content_llm_called": bool(llm_debug.get("called")),
            "media_api_called": True,
            "external_api_called": True,
            "seedance_called": False,
            "apx_called": False,
            "image2_called": True,
            "image2_succeeded": int(image2_debug.get("succeeded") or 0),
            "image2_failed": image2_unrecovered,
            "image2_requested": int(image2_debug.get("requested") or 0),
            "image2_disabled_by_env": False,
            "image2_skipped_reason": None,
            "image2_debug_path": str(image2_debug_path),
            "image2_failed_indices": failed_indices,
            "image2_moderation_blocked": moderation_blocked,
            "tts_called": False,
            "has_audio": False,
            "tts_status": "not_started",
            "voiceover_source": "none",
            "image_source": "image2_partial_failure",
            "image_sources": [],
            "video_composer": "skipped",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

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
            "tts_status": "not_started",
            "voiceover_source": "none",
            "image_source": "local_static_renderer",
            "video_composer": "ffmpeg",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

    # ----------------------------------------------------------------
    # v0.6.7 — synthesize_narration: feed LLM's narration_script_en into
    # ElevenLabs, save narration.mp3 + subtitles.ass next to the slides.
    # When IMAGE_VIDEO_NARRATION_ENABLED=false (or the LLM didn't return
    # a script), we skip and fall back to the BGM-only path.
    # ----------------------------------------------------------------
    narration_audio_path: Optional[Path] = None
    narration_duration: float = 0.0
    subtitles_ass_path: Optional[Path] = None
    narration_status = "skipped"
    narration_error: Optional[str] = None
    narration_voice_id: Optional[str] = None
    narration_model_id: Optional[str] = None
    narration_char_count = 0
    narration_subtitle_lines = 0
    # v0.6.7.2 — per-slide on-screen duration. When narration succeeds we
    # set each slide's duration to match the time edge-tts spends speaking
    # that slide's narration_line (so image N is on screen exactly while
    # sentence N is being said). Falls back to the even split otherwise.
    per_slide_durations: Optional[List[float]] = None

    narration_enabled_env = (os.getenv("IMAGE_VIDEO_NARRATION_ENABLED", "true") or "").strip().lower()
    narration_enabled = narration_enabled_env in ("1", "true", "yes", "on", "")
    narration_script = (llm_content or {}).get("narration_script_en") if llm_content else None
    narration_script = (narration_script or "").strip()

    if narration_enabled and narration_script:
        _emit("synthesize_narration", "running",
              f"0% In progress — calling Edge TTS ({len(narration_script)} chars)...")
        try:
            from web.audio_providers.edge_tts_provider import (
                synthesize_narration as _edge_synth,
                EdgeTtsError,
            )
        except Exception as exc:
            _emit("synthesize_narration", "failed",
                  f"Failed to import edge-tts provider: {exc}")
            narration_status = "import_failed"
            narration_error = f"import: {exc}"
        else:
            narration_audio_path_candidate = image_video_dir / "narration.mp3"
            try:
                tts_result = _edge_synth(
                    text=narration_script,
                    output_path=narration_audio_path_candidate,
                )
                narration_audio_path = tts_result.audio_path
                narration_duration = tts_result.duration_seconds
                narration_voice_id = tts_result.voice_id
                narration_model_id = tts_result.model_id
                narration_char_count = tts_result.char_count
                narration_status = "succeeded"
                _emit("synthesize_narration", "running",
                      f"60% In progress — narration mp3 saved ({narration_duration:.1f}s).")
            except EdgeTtsError as exc:
                _emit("synthesize_narration", "failed", f"Edge TTS failed: {exc}")
                narration_status = "tts_failed"
                narration_error = str(exc)
            except Exception as exc:
                _emit("synthesize_narration", "failed", f"Unexpected TTS error: {exc}")
                narration_status = "tts_failed"
                narration_error = f"unexpected: {exc}"

        # Build subtitles AFTER narration succeeds — duration is the
        # measured mp3 length so subtitle line timing matches the audio.
        # v0.6.7.1: pass through sentence_timings from edge-tts so each
        # subtitle line is shown for the EXACT span of audio that speaks
        # it (no more time-even drift).
        if narration_status == "succeeded" and narration_duration > 0.0:
            subtitles_ass_path_candidate = image_video_dir / "subtitles.ass"
            try:
                subtitles_ass_path, narration_subtitle_lines = _build_ass_subtitles(
                    narration_script,
                    total_duration_seconds=narration_duration,
                    output_path=subtitles_ass_path_candidate,
                    sentence_timings=getattr(tts_result, "sentence_timings", None),
                )
                _emit("synthesize_narration", "done",
                      f"100% Done — narration {narration_duration:.1f}s, "
                      f"{narration_subtitle_lines} subtitle lines.")
            except Exception as exc:
                _emit("synthesize_narration", "done",
                      f"Narration ready but subtitle build failed (continuing without subs): {exc}")
                subtitles_ass_path = None
                narration_error = f"subtitles: {exc}"

            # v0.6.7.2 — derive per-slide on-screen durations from the
            # SentenceBoundary timings. We assume one sentence ↔ one
            # slide (which is what the narration_line schema enforces).
            # If the counts don't match (model wrote multi-sentence
            # narration_lines, or merged some), fall back to the even
            # split for safety.
            sts = getattr(tts_result, "sentence_timings", None) or []
            if sts and len(sts) == slide_count:
                durs: List[float] = []
                for i, st in enumerate(sts):
                    s = max(0.0, float(getattr(st, "start_s", 0.0)))
                    if i + 1 < len(sts):
                        next_s = float(getattr(sts[i + 1], "start_s", s))
                        durs.append(max(0.4, next_s - s))
                    else:
                        # Last slide holds until the end of the audio.
                        durs.append(max(0.4, narration_duration - s))
                per_slide_durations = durs
            else:
                # Sentence count ≠ slide count → safest is the even split
                # so we don't desync the whole video.
                per_slide_durations = None
    else:
        # Skip narration entirely — emit a 'done' so the UI advances and
        # downstream compose still runs (BGM-only legacy path).
        skip_reason = (
            "IMAGE_VIDEO_NARRATION_ENABLED=false" if not narration_enabled
            else "no narration_script_en in LLM output"
        )
        _emit("synthesize_narration", "done",
              f"Skipped narration ({skip_reason}).")
        narration_status = "skipped"
        narration_error = skip_reason

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
            "tts_status": "not_started",
            "voiceover_source": "none",
            "image_source": "local_static_renderer",
            "video_composer": "ffmpeg_missing",
            "content_source": "llm" if llm_content else "static_template",
            "llm_used": bool(llm_content),
            "llm_fallback_used": bool(llm_debug.get("fallback_used")),
            "llm_fallback_reason": llm_debug.get("fallback_reason"),
            "overview_cn": (llm_content or {}).get("overview_cn"),
        }

    bgm_compose_path = bgm_track.absolute_path if bgm_track is not None else None
    # v0.6.5 — operator-tunable BGM volume. Default -15 dB sits well below
    # any future TTS narration. Set IMAGE_VIDEO_BGM_VOLUME_DB in .env to
    # override; clamped to a sane range so a typo can't blow speakers.
    try:
        bgm_volume_db_default = float(
            os.getenv("IMAGE_VIDEO_BGM_VOLUME_DB", "-15.0")
        )
    except Exception:
        bgm_volume_db_default = -15.0
    if bgm_volume_db_default > 0.0:
        bgm_volume_db_default = 0.0
    if bgm_volume_db_default < -40.0:
        bgm_volume_db_default = -40.0

    # v0.6.7 — when narration is on, BGM ducks further so speech stays
    # intelligible. Default -22 dB; clamped to the same sane range.
    bgm_volume_db_effective = bgm_volume_db_default
    if narration_audio_path is not None:
        try:
            duck_db = float(os.getenv("IMAGE_VIDEO_NARRATION_BGM_DUCK_DB", "-22.0"))
        except Exception:
            duck_db = -22.0
        if duck_db > 0.0:
            duck_db = 0.0
        if duck_db < -40.0:
            duck_db = -40.0
        bgm_volume_db_effective = duck_db

    _emit("compose_final_video", "running",
          (f"Composing final mp4 with FFmpeg ({slide_count} slides"
           + (f" + narration ({narration_duration:.1f}s)" if narration_audio_path is not None else "")
           + (f" + BGM '{bgm_track.display_name}'" if bgm_track is not None else " + no BGM")
           + (" + subtitles" if subtitles_ass_path is not None else "")
           + ")..."))
    # When per-slide durations are set, the on-screen total = sum of them
    # (≈ narration_duration). When they are not, fall back to the
    # original duration_seconds (legacy even split).
    effective_total_duration = (
        sum(per_slide_durations) if per_slide_durations else float(duration_seconds)
    )
    ok, msg, ffmpeg_args, concat_path = _compose_with_ffmpeg(
        ffmpeg_bin, slide_paths, duration_per_slide, final_video_path, image_video_dir,
        bgm_path=bgm_compose_path,
        bgm_volume_db=bgm_volume_db_effective,
        total_duration_seconds=float(effective_total_duration),
        narration_path=narration_audio_path,
        narration_duration_seconds=float(narration_duration or 0.0),
        bgm_base_volume_db=float(bgm_volume_db_default),
        subtitles_path=subtitles_ass_path,
        per_slide_durations=per_slide_durations,
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
            "tts_status": "not_started",
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
        "tts_called": narration_status in ("succeeded", "tts_failed", "import_failed"),
        "has_audio": bool(bgm_track is not None) or narration_status == "succeeded",
        "tts_status": narration_status,
        "tts_error": narration_error,
        "voiceover_source": "edge_tts" if narration_status == "succeeded" else "none",
        "narration_audio_path": str(narration_audio_path) if narration_audio_path else None,
        "narration_duration_seconds": float(narration_duration),
        "narration_voice_id": narration_voice_id,
        "narration_model_id": narration_model_id,
        "narration_char_count": narration_char_count,
        "subtitles_path": str(subtitles_ass_path) if subtitles_ass_path else None,
        "subtitle_lines": narration_subtitle_lines,
        "narration_script_en": (llm_content or {}).get("narration_script_en"),
        "bgm_used": bool(bgm_track is not None),
        "bgm_filename": (bgm_track.filename if bgm_track is not None else None),
        "bgm_display_name": (bgm_track.display_name if bgm_track is not None else None),
        "bgm_mood_keywords": (
            list(bgm_track.mood_keywords) if bgm_track is not None else []
        ),
        "bgm_volume_db": float(bgm_volume_db_default),
        "bgm_chosen_by_llm": bool(
            llm_bgm_choice and isinstance(llm_bgm_choice, dict) and llm_bgm_choice.get("filename")
        ),
        "bgm_llm_why": (
            (llm_bgm_choice or {}).get("why")
            if isinstance(llm_bgm_choice, dict) else None
        ),
        "bgm_disabled_by_env": bool(bgm_debug.get("disabled_by_env")),
        "bgm_fallback_used": bool(bgm_debug.get("fallback_used")),
        "bgm_fallback_reason": bgm_debug.get("fallback_reason"),
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
        "art_style": (llm_content or {}).get("art_style") or "paper_craft",
        "error": None,
    }
