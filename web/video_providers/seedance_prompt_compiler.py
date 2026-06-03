"""
SeedancePromptCompiler (v0.6.2).

Compiles structured Video Mode content assets (topic_analysis / reasoning /
video_script / storyboard / provider_request_preview) into a Seedance-shaped
prompt bundle: a compact ``seedance_prompt.txt``, a structured negative
prompt, a normalized input view, a prompt-quality verdict, and a debug
payload that captures the compilation decisions.

v0.6.2 changes
--------------
* New ``normalize_seedance_prompt_input(...)`` step extracts a clean,
  English-only structured view from upstream assets BEFORE building the
  final prompt. Empty / placeholder upstream content (``this topic``, ``A``,
  ``AB``, ``BAB``, ``Question``/``Answer``/``Why?`` as the only fragments,
  ``Human review required``, CJK-only narration / scene text) is detected
  and recorded as ``prompt_quality_failed=true`` instead of being papered
  over with a generic placeholder.
* Final ``seedance_prompt.txt`` is rewritten into a compact, video-model
  friendly English prompt with positive narrator instructions ("Use one
  clear English narrator voiceover.") — the legacy "does not yet generate
  audio" wording is gone.
* New ``validate_seedance_prompt_quality(prompt, compiled_payload,
  duration_seconds)`` — the function the runtime calls right before a real
  APX submit. Default-deny: if any rule fails, real APX submission must be
  blocked.

The compiler is deliberately offline:

* No real Seedance API is called.
* No HTTP request of any kind is performed.
* No real mp4 is generated and no real video URL is produced.
* The NotebookLM Prompt Mode template is **not** imported.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_LEGACY_DURATION_PATTERNS = [
    (re.compile(r"50\s*[-–]\s*60\s*seconds?", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"60\s*[-–]\s*second", re.IGNORECASE), "{d}-second"),
    (re.compile(r"60\s*seconds?", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"\bone\s+minute\b", re.IGNORECASE), "{d} seconds"),
    (re.compile(r"50\s*[-–]\s*60\s*秒"), "{d} 秒"),
    (re.compile(r"60\s*秒"), "{d} 秒"),
    (re.compile(r"一分钟"), "{d} 秒"),
]


def _sync_duration_text(text: Any, target_duration_seconds: int) -> str:
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    try:
        d = int(target_duration_seconds)
    except Exception:
        d = 5
    if d <= 0:
        d = 5
    for pattern, replacement in _LEGACY_DURATION_PATTERNS:
        s = pattern.sub(replacement.format(d=d), s)
    return s


COMPILER_VERSION = "seedance_prompt_compiler_v0.6.2"
PROFILE_SCHEMA_VERSION = "seedance_prompt_profile_v0.6.2"
DEBUG_SCHEMA_VERSION = "seedance_prompt_debug_v0.6.2"

DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "provider_profiles"
    / "seedance.json"
)

DEFAULT_DURATION_SECONDS = 15
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_RESOLUTION = "1920x1080"
DEFAULT_ORIENTATION = "landscape"
DEFAULT_STYLE = (
    "clean whiteboard infographic educational explainer, white background, "
    "simple line art, large readable English text only"
)

_CJK_RE = re.compile(
    "["
    "　-〿"
    "㐀-䶿"
    "一-鿿"
    "豈-﫿"
    "＀-￯"
    "]"
)


# ---------------------------------------------------------------------------
# Quality-gate constants
# ---------------------------------------------------------------------------

# Placeholder strings the v0.6.2 quality gate refuses to ship to APX.
BANNED_PLACEHOLDER_STRINGS = (
    "this topic",
    "human review required",
    "needs human review",
    "tbd",
    "placeholder",
    "does not yet generate audio",
)

# Tokens that, when seen *standalone* (i.e. as the entire field), indicate
# the LLM produced nonsense like "A" / "AB" / "BAB" / "ABA" / "BA".
BANNED_STANDALONE_TOKENS = {
    "a", "b", "c",
    "ab", "ba", "bab", "aba", "abab", "baba",
}

# Generic on-screen-text fragments that may appear among others but must not
# dominate the allowed_on_screen_text list.
GENERIC_OST_FRAGMENTS = {"question", "answer", "why?", "why", "topic"}

# Keywords the final compiled prompt MUST contain.
REQUIRED_PROMPT_KEYWORDS = (
    "16:9",
    "landscape",
    "1920x1080",
    "english narrator",
    "single narrator",
    "monologue",
    "no dialogue",
    "no podcast",
    "no interview",
    "no chinese characters",
)


# ---------------------------------------------------------------------------
# String helpers
# ---------------------------------------------------------------------------

def _strip_cjk(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    cleaned = _CJK_RE.sub("", s)
    return re.sub(r"\s+", " ", cleaned).strip()


def _safe_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return fallback


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _short_english(text: Any, max_words: int = 8, max_chars: int = 80) -> str:
    """Strip CJK, collapse whitespace, cap length. Returns ``""`` if nothing
    meaningful remains — callers MUST treat empty as a quality failure
    rather than fabricating a placeholder."""
    s = _strip_cjk(text) if text is not None else ""
    if not s:
        return ""
    words = s.split()
    if len(words) > max_words:
        s = " ".join(words[:max_words])
    if len(s) > max_chars:
        s = s[:max_chars].rstrip()
    return s.strip()


def _is_banned_standalone(text: str) -> bool:
    if not text:
        return False
    norm = re.sub(r"[^a-zA-Z]", "", text).lower()
    if not norm:
        return False
    return norm in BANNED_STANDALONE_TOKENS


def _contains_banned_placeholder(text: str) -> Optional[str]:
    if not text:
        return None
    low = text.lower()
    for marker in BANNED_PLACEHOLDER_STRINGS:
        if marker in low:
            return marker
    return None


DEFAULT_NEGATIVE_PROMPT_DEFAULTS: List[str] = [
    "no dialogue",
    "no interview",
    "no podcast",
    "no two-host conversation",
    "no multiple speakers",
    "no Chinese characters",
    "no CJK text on screen",
    "no misspelled text",
    "no extra on-screen text beyond the provided list",
    "no off-topic decoration",
    "no wrong answer",
    "no unsupported visual claims",
    "no real human faces",
    "no photorealistic humans",
    "no 3D rendering",
    "no dark cinematic look",
    "no clutter",
    "no copyrighted characters",
    "no logos or watermarks",
    "no text rendering errors",
    "no flicker",
    "no extreme camera movement",
    "no portrait 9:16 framing",
    "no random letters",
    "no placeholder text",
    "no stock footage",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Normalization step (the heart of the v0.6.2 quality fix)
# ---------------------------------------------------------------------------

def normalize_seedance_prompt_input(
    topic_analysis: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
    video_script: Optional[Dict[str, Any]] = None,
    storyboard: Optional[Dict[str, Any]] = None,
    provider_request_preview: Optional[Dict[str, Any]] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull a clean, English-only structured view out of upstream assets.

    Returns a dict with these keys:

    * ``original_topic``           — verbatim user input (may be CJK).
    * ``english_subject``          — short English subject; empty on failure.
    * ``english_title``            — short English title.
    * ``english_question``         — the English question the video answers.
    * ``video_goal``               — one-line English goal sentence.
    * ``core_concept``             — short English core concept.
    * ``correct_answer``           — concise English answer.
    * ``hook_line``                — opening narrator line.
    * ``narration_script``         — full English narration body.
    * ``ending_line``              — closing narrator line.
    * ``scene_plan``               — list of {scene_id, time_range, visual,
                                     narration, on_screen_text}.
    * ``allowed_on_screen_text``   — list of concrete English fragments.
    * ``duration_seconds``         — int.
    * ``aspect_ratio``             — always "16:9".
    * ``resolution``               — always "1920x1080".
    * ``style``                    — short style descriptor.
    * ``prompt_quality_failed``    — bool.
    * ``quality_block_reasons``    — list[str] explaining failures (if any).
    * ``needs_human_review``       — bool (LLM-signalled).

    The function NEVER fabricates ``this topic`` / ``A`` / ``AB`` / ``BAB``
    placeholders. When upstream content is missing, the returned fields are
    empty and the relevant block-reason is appended.
    """
    ta = topic_analysis if isinstance(topic_analysis, dict) else {}
    rs = reasoning if isinstance(reasoning, dict) else {}
    sc = video_script if isinstance(video_script, dict) else {}
    sb = storyboard if isinstance(storyboard, dict) else {}
    pr = provider_request_preview if isinstance(provider_request_preview, dict) else {}

    block_reasons: List[str] = []

    original_topic = topic or ta.get("topic") or pr.get("topic") or ""

    # ------------------------------------------------------------------
    # English subject / title / question
    # ------------------------------------------------------------------
    english_subject = _short_english(
        ta.get("english_subject")
        or ta.get("english_title")
        or ta.get("normalized_topic"),
        max_words=8,
        max_chars=80,
    )
    if not english_subject or _is_banned_standalone(english_subject):
        # Last-ditch attempts using core_concept / video_goal — these are
        # often present in the LLM output even when english_subject is not.
        for candidate_key in ("core_concept", "video_goal", "title"):
            candidate = _short_english(ta.get(candidate_key), max_words=8, max_chars=80)
            if candidate and not _is_banned_standalone(candidate):
                english_subject = candidate
                break
    if not english_subject and original_topic:
        # Try the user's literal input ONLY if it has English content.
        candidate = _short_english(original_topic, max_words=8, max_chars=80)
        if candidate and not _is_banned_standalone(candidate):
            english_subject = candidate
    if not english_subject:
        block_reasons.append("english_subject is empty")
    elif _contains_banned_placeholder(english_subject):
        block_reasons.append(
            f"english_subject contains banned placeholder ({english_subject!r})"
        )

    english_title = _short_english(
        ta.get("english_title") or ta.get("english_subject") or english_subject,
        max_words=10,
        max_chars=100,
    )

    english_question = _short_english(
        ta.get("english_question")
        or pr.get("english_question")
        or sc.get("hook"),
        max_words=20,
        max_chars=180,
    )
    if not english_question and english_subject:
        # Build a plausible question from the subject — avoids "this topic"
        # wording while still flagging the missing field as a soft warning.
        english_question = f"What is {english_subject}?"

    # ------------------------------------------------------------------
    # Goal / concept / answer
    # ------------------------------------------------------------------
    video_goal = _short_english(ta.get("video_goal"), max_words=40, max_chars=300)
    core_concept = _short_english(
        ta.get("core_concept") or english_subject, max_words=20, max_chars=200
    )
    if not core_concept:
        block_reasons.append("core_concept is empty")

    correct_answer_raw = _safe_str(rs.get("correct_answer"))
    correct_answer = _strip_cjk(correct_answer_raw).strip()
    # Cap to keep prompts compact — but preserve sentence boundary.
    if len(correct_answer) > 320:
        correct_answer = correct_answer[:320].rstrip()
    if not correct_answer:
        block_reasons.append("correct_answer is empty")
    elif _is_banned_standalone(correct_answer):
        block_reasons.append(f"correct_answer is a banned token ({correct_answer!r})")
    elif _contains_banned_placeholder(correct_answer):
        block_reasons.append(
            f"correct_answer contains banned placeholder ({correct_answer!r})"
        )

    hook_line = _strip_cjk(_safe_str(sc.get("hook"))).strip()
    if _is_banned_standalone(hook_line):
        hook_line = ""

    narration_script = _strip_cjk(_safe_str(sc.get("narration"))).strip()
    if not narration_script:
        block_reasons.append("narration_script is empty")
    elif _is_banned_standalone(narration_script):
        block_reasons.append(
            f"narration_script is a banned token ({narration_script!r})"
        )
    elif len(narration_script.split()) < 4:
        block_reasons.append(
            f"narration_script too short ({len(narration_script.split())} words)"
        )

    ending_line = _strip_cjk(_safe_str(sc.get("ending"))).strip()
    if _is_banned_standalone(ending_line):
        ending_line = ""

    # ------------------------------------------------------------------
    # Scene plan
    # ------------------------------------------------------------------
    scene_plan: List[Dict[str, Any]] = []
    raw_scenes = _safe_list(sb.get("scenes"))
    for idx, sc_item in enumerate(raw_scenes, start=1):
        if not isinstance(sc_item, dict):
            continue
        # Prefer v0.6.2 *_en keys but keep back-compat with the v0.6.1 names.
        visual = _strip_cjk(
            _safe_str(sc_item.get("visual_en") or sc_item.get("visual"))
        ).strip()
        narration = _strip_cjk(
            _safe_str(sc_item.get("narration_en") or sc_item.get("narration"))
        ).strip()
        ost_raw = sc_item.get("on_screen_text_en")
        if ost_raw is None:
            ost_raw = sc_item.get("on_screen_text")
        ost_list: List[str] = []
        if isinstance(ost_raw, list):
            for item in ost_raw:
                clean = _short_english(item, max_words=8, max_chars=60)
                if clean and not _is_banned_standalone(clean):
                    ost_list.append(clean)
        else:
            clean = _short_english(ost_raw, max_words=8, max_chars=60)
            if clean and not _is_banned_standalone(clean):
                ost_list.append(clean)
        scene_plan.append({
            "scene_id": sc_item.get("scene_id", idx),
            "time_range": _strip_cjk(_safe_str(sc_item.get("time_range"))),
            "visual": visual,
            "narration": narration,
            "on_screen_text": ost_list,
            "camera": _strip_cjk(_safe_str(sc_item.get("camera"))),
            "notes": _strip_cjk(_safe_str(sc_item.get("notes"))),
        })

    if not scene_plan:
        block_reasons.append("scene_plan is empty")
    else:
        bad_scenes = []
        for s in scene_plan:
            if not s.get("visual") or _is_banned_standalone(s["visual"]):
                bad_scenes.append(f"scene {s.get('scene_id')} missing visual")
                continue
            if not s.get("narration") or _is_banned_standalone(s["narration"]):
                bad_scenes.append(f"scene {s.get('scene_id')} missing narration")
        if bad_scenes:
            block_reasons.extend(bad_scenes)

    # ------------------------------------------------------------------
    # Allowed on-screen text
    # ------------------------------------------------------------------
    allowed_ost: List[str] = []
    seen_ost: set = set()
    for raw in _safe_list(sc.get("on_screen_text")):
        if isinstance(raw, list):
            for sub in raw:
                clean = _short_english(sub, max_words=8, max_chars=60)
                if clean and clean.lower() not in seen_ost and not _is_banned_standalone(clean):
                    seen_ost.add(clean.lower())
                    allowed_ost.append(clean)
        else:
            clean = _short_english(raw, max_words=8, max_chars=60)
            if clean and clean.lower() not in seen_ost and not _is_banned_standalone(clean):
                seen_ost.add(clean.lower())
                allowed_ost.append(clean)
    # Pull additional fragments from each scene so we always have ≥2 unless
    # upstream is genuinely empty.
    for s in scene_plan:
        for item in s.get("on_screen_text") or []:
            low = item.lower()
            if low in seen_ost or _is_banned_standalone(item):
                continue
            seen_ost.add(low)
            allowed_ost.append(item)

    if len(allowed_ost) < 2:
        block_reasons.append(
            f"allowed_on_screen_text has {len(allowed_ost)} entries (min 2)"
        )

    # Reject lists that are entirely generic Question/Answer/Why fragments.
    if allowed_ost:
        non_generic = [
            x for x in allowed_ost if x.lower().rstrip("?") not in GENERIC_OST_FRAGMENTS
        ]
        if not non_generic:
            block_reasons.append(
                "allowed_on_screen_text is entirely generic (Question/Answer/Why?)"
            )

    # ------------------------------------------------------------------
    # Duration / format
    # ------------------------------------------------------------------
    duration_candidate = (
        pr.get("target_duration_seconds")
        or pr.get("duration_seconds")
        or sb.get("duration_seconds")
        or DEFAULT_DURATION_SECONDS
    )
    try:
        duration_seconds = int(duration_candidate)
    except Exception:
        duration_seconds = DEFAULT_DURATION_SECONDS
    if duration_seconds <= 0:
        duration_seconds = DEFAULT_DURATION_SECONDS

    needs_human_review = bool(ta.get("needs_human_review")) or bool(
        rs.get("needs_human_review")
    )

    return {
        "original_topic": original_topic,
        "english_subject": english_subject,
        "english_title": english_title,
        "english_question": english_question,
        "video_goal": video_goal,
        "core_concept": core_concept,
        "correct_answer": correct_answer,
        "hook_line": hook_line,
        "narration_script": narration_script,
        "ending_line": ending_line,
        "scene_plan": scene_plan,
        "allowed_on_screen_text": allowed_ost,
        "duration_seconds": duration_seconds,
        "aspect_ratio": DEFAULT_ASPECT_RATIO,
        "resolution": DEFAULT_RESOLUTION,
        "orientation": DEFAULT_ORIENTATION,
        "style": DEFAULT_STYLE,
        "prompt_quality_failed": bool(block_reasons),
        "quality_block_reasons": block_reasons,
        "needs_human_review": needs_human_review,
    }


# ---------------------------------------------------------------------------
# Final-prompt quality gate (called by the runtime right before APX submit)
# ---------------------------------------------------------------------------

def validate_seedance_prompt_quality(
    prompt: str,
    compiled_payload: Optional[Dict[str, Any]] = None,
    duration_seconds: Optional[int] = None,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Default-deny check on the FINAL Seedance prompt.

    Returns ``(passed, reasons, details)``. When ``passed`` is False the
    runtime MUST NOT call APX. The third return value carries machine-
    readable per-rule outcomes useful for the Provider Evidence panel.

    ``compiled_payload`` is the dict returned by
    :func:`SeedancePromptCompiler.compile_from_assets` (or a subset of it).
    The function tolerates ``None`` / partial input but is stricter the more
    structure it has.
    """
    reasons: List[str] = []
    rules: Dict[str, Any] = {}

    payload = compiled_payload or {}
    normalized = (
        payload.get("normalized_input")
        if isinstance(payload, dict)
        else None
    ) or {}

    # 1. Non-empty prompt.
    prompt_str = _safe_str(prompt)
    if not prompt_str.strip():
        reasons.append("prompt is empty")
        rules["prompt_non_empty"] = False
    else:
        rules["prompt_non_empty"] = True

    # 2. Reasonable length.
    char_len = len(prompt_str)
    rules["prompt_chars"] = char_len
    if char_len < 200:
        reasons.append(f"prompt too short ({char_len} chars; min 200)")
    elif char_len > 12000:
        reasons.append(f"prompt too long ({char_len} chars; max 12000)")

    # 3. No CJK.
    if _CJK_RE.search(prompt_str):
        reasons.append("prompt contains Chinese / CJK characters")
        rules["no_cjk"] = False
    else:
        rules["no_cjk"] = True

    # 4. v0.6.2-hotfix — Banned-placeholder / standalone-token checks were
    # previously run against the FULL prompt text, which collided with
    # legitimate Negative-constraint sentences ("No placeholder text.",
    # "Do not use placeholder text.") and caused false-positive blocks.
    # The v0.6.2-hotfix policy: only inspect the structured normalized_input
    # *content* fields. The full-prompt scan keeps just the structural
    # invariants below (length, CJK, required keywords, duration mention) —
    # those cannot collide with negative-constraint phrasing.
    low = prompt_str.lower()
    rules["banned_placeholder_hits"] = []
    rules["banned_standalone_hits"] = []

    # 5. Required keywords on the final prompt — case-insensitive substring
    # match. These are structural and never overlap with banned content.
    missing_keywords: List[str] = []
    for kw in REQUIRED_PROMPT_KEYWORDS:
        if kw.lower() not in low:
            missing_keywords.append(kw)
    if missing_keywords:
        reasons.append(
            "prompt missing required keywords: " + ", ".join(missing_keywords)
        )
    rules["missing_required_keywords"] = missing_keywords

    # 6-12. Inspect the structured normalized_input fields. Banned
    # placeholders / standalone tokens are caught HERE, not on the full
    # prompt. Only fields whose role is to carry user content are scanned —
    # never fields like profile.style or compiler-emitted rule text.
    structured_placeholder_hits: List[str] = []
    structured_standalone_hits: List[str] = []
    standalone_pattern = re.compile(r"^[A-Za-z]{1,5}$")

    def _record_placeholder(field: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        vl = v.lower()
        for marker in BANNED_PLACEHOLDER_STRINGS:
            if marker in vl:
                structured_placeholder_hits.append(f"{field}={v!r} contains '{marker}'")
                return
        # Standalone A / AB / BAB only make sense when the *entire* field
        # value is the bad token, e.g. narration_script == "A". Sentence-
        # level fields legitimately contain "A" as an article.
        if standalone_pattern.match(v) and _is_banned_standalone(v):
            structured_standalone_hits.append(f"{field}={v!r}")

    if normalized:
        # Subject / title / question / goal / concept / answer / hook /
        # narration / ending — single-string content fields.
        for field in (
            "english_subject",
            "english_title",
            "english_question",
            "video_goal",
            "core_concept",
            "correct_answer",
            "hook_line",
            "narration_script",
            "ending_line",
        ):
            _record_placeholder(field, _safe_str(normalized.get(field)))

        # allowed_on_screen_text — list of fragments. Each fragment scanned
        # individually so "Question" in a list with concrete fragments is
        # tolerated by a separate generic-only check below.
        for idx, ost_item in enumerate(_safe_list(normalized.get("allowed_on_screen_text"))):
            _record_placeholder(f"allowed_on_screen_text[{idx}]", _safe_str(ost_item))

        # scene_plan[*].{visual, narration, on_screen_text}
        for idx, scene in enumerate(_safe_list(normalized.get("scene_plan"))):
            if not isinstance(scene, dict):
                continue
            sid = scene.get("scene_id", idx + 1)
            _record_placeholder(f"scene[{sid}].visual", _safe_str(scene.get("visual")))
            _record_placeholder(f"scene[{sid}].narration", _safe_str(scene.get("narration")))
            ost_field = scene.get("on_screen_text")
            if isinstance(ost_field, list):
                for j, ost_item in enumerate(ost_field):
                    _record_placeholder(
                        f"scene[{sid}].on_screen_text[{j}]", _safe_str(ost_item)
                    )
            else:
                _record_placeholder(
                    f"scene[{sid}].on_screen_text", _safe_str(ost_field)
                )

    if structured_placeholder_hits:
        reasons.append(
            "structured field contains banned placeholder: "
            + "; ".join(structured_placeholder_hits)
        )
    rules["banned_placeholder_hits"] = structured_placeholder_hits

    if structured_standalone_hits:
        reasons.append(
            "structured field is a banned standalone token: "
            + "; ".join(structured_standalone_hits)
        )
    rules["banned_standalone_hits"] = structured_standalone_hits

    # 13. Structural emptiness / generic-only checks.
    if normalized:
        if not normalized.get("english_subject"):
            reasons.append("english_subject is empty")
        if not normalized.get("english_question"):
            reasons.append("english_question is empty")
        if not normalized.get("correct_answer"):
            reasons.append("correct_answer is empty")
        if not normalized.get("narration_script"):
            reasons.append("narration_script is empty")
        scene_plan = normalized.get("scene_plan") or []
        if not scene_plan:
            reasons.append("scene_plan is empty")
        else:
            for s in scene_plan:
                if not s.get("visual"):
                    reasons.append(f"scene {s.get('scene_id')} missing visual")
                    break
                if not s.get("narration"):
                    reasons.append(f"scene {s.get('scene_id')} missing narration")
                    break
        ost = normalized.get("allowed_on_screen_text") or []
        if len(ost) < 2:
            reasons.append(
                f"allowed_on_screen_text has {len(ost)} entries (min 2)"
            )
        elif all(
            x.lower().rstrip("?") in GENERIC_OST_FRAGMENTS for x in ost
        ):
            reasons.append(
                "allowed_on_screen_text is entirely generic (Question/Answer/Why?)"
            )
        # Inherit normalize-stage block reasons too — they are real failures.
        for r in normalized.get("quality_block_reasons") or []:
            if r not in reasons:
                reasons.append(r)

        rules["english_subject_present"] = bool(normalized.get("english_subject"))
        rules["english_question_present"] = bool(normalized.get("english_question"))
        rules["correct_answer_present"] = bool(normalized.get("correct_answer"))
        rules["narration_present"] = bool(normalized.get("narration_script"))
        rules["scene_count"] = len(scene_plan)
        rules["on_screen_text_count"] = len(ost)

    # 14. Duration coherence.
    if duration_seconds is not None:
        try:
            ds = int(duration_seconds)
        except Exception:
            ds = None
        if ds is not None:
            rules["duration_seconds"] = ds
            normalized_duration = normalized.get("duration_seconds") if normalized else None
            if normalized_duration is not None and int(normalized_duration) != ds:
                reasons.append(
                    f"normalized duration ({normalized_duration}) != requested ({ds})"
                )
            # The compiled prompt should mention the requested duration.
            if not re.search(rf"\b{ds}\s*-?\s*second", prompt_str, re.IGNORECASE) \
               and not re.search(rf"\b{ds}\s*seconds\b", prompt_str, re.IGNORECASE) \
               and not re.search(rf"Mandatory duration:\s*{ds}\s*seconds", prompt_str, re.IGNORECASE):
                reasons.append(f"prompt does not mention duration {ds}")

    passed = not reasons
    rules["passed"] = passed
    return passed, reasons, rules


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class SeedancePromptCompiler:
    """Offline Seedance prompt compiler (v0.6.2)."""

    provider = "seedance"
    future_provider = "seedance"
    compiler_version = COMPILER_VERSION
    network_enabled = False

    def __init__(self, profile: Optional[Dict[str, Any]] = None) -> None:
        self._profile_loaded_from: Optional[str] = None
        if profile is None:
            profile = self._load_default_profile()
        self.profile: Dict[str, Any] = profile or {}

    def _load_default_profile(self) -> Dict[str, Any]:
        try:
            if DEFAULT_PROFILE_PATH.exists():
                with open(DEFAULT_PROFILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._profile_loaded_from = str(DEFAULT_PROFILE_PATH)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
        return {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def compile_from_assets(
        self,
        topic_analysis: Optional[Dict[str, Any]] = None,
        reasoning: Optional[Dict[str, Any]] = None,
        video_script: Optional[Dict[str, Any]] = None,
        storyboard: Optional[Dict[str, Any]] = None,
        provider_request_preview: Optional[Dict[str, Any]] = None,
        topic: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        warnings: List[str] = []

        ta = topic_analysis if isinstance(topic_analysis, dict) else {}
        rs = reasoning if isinstance(reasoning, dict) else {}
        sc = video_script if isinstance(video_script, dict) else {}
        sb = storyboard if isinstance(storyboard, dict) else {}
        pr = provider_request_preview if isinstance(provider_request_preview, dict) else {}

        if not ta:
            warnings.append("topic_analysis missing; compiler used safe defaults.")
        if not rs:
            warnings.append("reasoning missing; compiler used safe defaults.")
        if not sc:
            warnings.append("video_script missing; compiler used safe defaults.")
        if not sb:
            warnings.append("storyboard missing; compiler used safe defaults.")

        normalized = normalize_seedance_prompt_input(
            topic_analysis=ta,
            reasoning=rs,
            video_script=sc,
            storyboard=sb,
            provider_request_preview=pr,
            topic=topic,
        )
        # v0.6.2: output language is forced English regardless of input.
        recorded_input_language = (
            language
            or ta.get("input_language")
            or ta.get("language")
            or pr.get("input_language")
            or pr.get("language")
            or "en"
        )

        seedance_prompt = self.build_seedance_prompt(normalized)
        negative_prompt = self.build_negative_prompt(
            topic_analysis=ta, storyboard=sb, provider_request_preview=pr,
        )

        passed, gate_reasons, gate_rules = validate_seedance_prompt_quality(
            seedance_prompt,
            compiled_payload={"normalized_input": normalized},
            duration_seconds=normalized.get("duration_seconds"),
        )

        prompt_quality = {
            "passed": passed,
            "reasons": gate_reasons,
            "rules": gate_rules,
            "normalize_block_reasons": list(normalized.get("quality_block_reasons") or []),
            "normalize_passed": not normalized.get("prompt_quality_failed"),
        }
        if not passed:
            warnings.append(
                "Seedance prompt quality gate FAILED: " + "; ".join(gate_reasons)
            )

        debug_payload = self.build_debug_payload(
            topic=_safe_str(topic),
            language="en",
            input_language=_safe_str(recorded_input_language, "en"),
            seedance_prompt=seedance_prompt,
            negative_prompt=negative_prompt,
            warnings=warnings,
            inputs_present={
                "topic_analysis": bool(ta),
                "reasoning": bool(rs),
                "video_script": bool(sc),
                "storyboard": bool(sb),
                "provider_request_preview": bool(pr),
            },
            normalized_input=normalized,
            prompt_quality=prompt_quality,
        )

        return {
            "compiler_version": COMPILER_VERSION,
            "profile_version": self.profile.get("profile_version", PROFILE_SCHEMA_VERSION),
            "provider": self.provider,
            "future_provider": self.future_provider,
            "network_call_performed": False,
            "real_video_generated": False,
            "topic": _safe_str(topic),
            "language": "en",
            "input_language": _safe_str(recorded_input_language, "en"),
            "seedance_prompt": seedance_prompt,
            "negative_prompt": negative_prompt,
            "normalized_input": normalized,
            "prompt_quality": prompt_quality,
            "seedance_prompt_debug": debug_payload,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Final-prompt builder — compact v0.6.2 format
    # ------------------------------------------------------------------
    def build_seedance_prompt(self, normalized: Dict[str, Any]) -> str:
        n = normalized
        duration = int(n.get("duration_seconds") or DEFAULT_DURATION_SECONDS)
        aspect_ratio = n.get("aspect_ratio") or DEFAULT_ASPECT_RATIO
        resolution = n.get("resolution") or DEFAULT_RESOLUTION
        style = n.get("style") or DEFAULT_STYLE

        english_subject = n.get("english_subject") or ""
        english_question = n.get("english_question") or ""
        core_concept = n.get("core_concept") or english_subject
        correct_answer = n.get("correct_answer") or ""
        hook_line = n.get("hook_line") or ""
        narration = n.get("narration_script") or ""
        ending = n.get("ending_line") or ""
        scene_plan = n.get("scene_plan") or []
        allowed_ost = n.get("allowed_on_screen_text") or []

        sections: List[str] = []

        # --- Task ---
        task_subject = english_question or english_subject or "this educational topic"
        sections.append(
            "Task:\n"
            f"Create a {duration}-second {aspect_ratio} landscape educational explainer "
            f"video about: \"{task_subject}\"."
        )

        # --- Format ---
        sections.append(
            "Format:\n"
            f"{aspect_ratio} landscape, {resolution}, {style}, white background, simple "
            f"line art, large readable English text only."
        )

        # --- Voiceover ---
        sections.append(
            "Voiceover:\n"
            "Use one clear English narrator voiceover. Single narrator monologue only. "
            "No dialogue, no interview, no podcast, no two speakers."
        )

        # --- Core explanation ---
        explanation_lines: List[str] = []
        if core_concept:
            explanation_lines.append(f"Core concept: {core_concept}.")
        if correct_answer:
            explanation_lines.append(f"Correct answer (must be shown correctly): {correct_answer}.")
        if hook_line:
            explanation_lines.append(f"Hook: {hook_line}")
        if narration:
            explanation_lines.append(f"Narration body: {narration}")
        if ending:
            explanation_lines.append(f"Closing: {ending}")
        if not explanation_lines:
            explanation_lines.append("(no explicit reasoning supplied)")
        sections.append("Core explanation:\n" + "\n".join(explanation_lines))

        # --- Scene plan ---
        scene_lines: List[str] = []
        for sc_item in scene_plan:
            sid = sc_item.get("scene_id") or "?"
            tr = sc_item.get("time_range") or ""
            visual = sc_item.get("visual") or ""
            narr = sc_item.get("narration") or ""
            ost_list = sc_item.get("on_screen_text") or []
            ost_text = " | ".join(ost_list) if ost_list else ""
            line = f"Scene {sid} ({tr}): visual: {visual}; narration: {narr}"
            if ost_text:
                line += f"; on-screen text: {ost_text}"
            scene_lines.append(line)
        if not scene_lines:
            scene_lines.append("(no storyboard scenes supplied)")
        sections.append("Scene plan:\n" + "\n".join(scene_lines))

        # --- Allowed on-screen text ---
        ost_section: List[str] = []
        if allowed_ost:
            for item in allowed_ost:
                ost_section.append(f"- {item}")
        else:
            ost_section.append("- (no on-screen text fragments supplied)")
        sections.append("Allowed on-screen text only:\n" + "\n".join(ost_section))

        # --- Text rules ---
        sections.append(
            "Text rules:\n"
            "Use only the exact on-screen text listed above. only render the exact provided "
            "on-screen text fragments — do not invent extra text. Each on-screen text fragment "
            "is at most max 8 English words. Do not render Chinese characters. Do not misspell "
            "text. If text rendering is uncertain, use diagrams and icons instead of extra words."
        )

        # --- Motion ---
        sections.append(
            "Motion:\n"
            "Clean, slow, educational motion. Stable camera. No clutter. No dark cinematic "
            "scene. No 3D. No realistic humans."
        )

        # --- Negative constraints ---
        sections.append(
            "Negative constraints:\n"
            "No Chinese characters, no misspelled words, no random letters, no placeholder "
            "text, no dialogue, no podcast, no interview, no two-host conversation, no stock "
            "footage, no clutter, no dark background, no unrelated objects, no portrait 9:16 "
            "framing."
        )

        # --- Final rules ---
        sections.append(
            "Final rules:\n"
            f"Mandatory duration: {duration} seconds. Ignore any conflicting duration instruction "
            "from earlier sections.\n"
            f"Mandatory format: {aspect_ratio} landscape, {resolution}.\n"
            "English only.\n"
            "Single narrator monologue only.\n"
            "The final answer must be correct."
        )

        compiled = "\n\n".join(sections).strip() + "\n"
        # Defensive sweep: strip CJK that could have leaked through profile data.
        if _CJK_RE.search(compiled):
            compiled = _CJK_RE.sub("", compiled)
        return compiled

    # ------------------------------------------------------------------
    # Negative prompt
    # ------------------------------------------------------------------
    def build_negative_prompt(
        self,
        topic_analysis: Optional[Dict[str, Any]] = None,
        storyboard: Optional[Dict[str, Any]] = None,
        provider_request_preview: Optional[Dict[str, Any]] = None,
    ) -> str:
        profile = self.profile or {}
        items: List[str] = []
        seen = set()

        def _add(item: Any) -> None:
            text = _safe_str(item).strip()
            if not text:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            items.append(text)

        for entry in _safe_list(profile.get("negative_prompt_defaults")) or list(
            DEFAULT_NEGATIVE_PROMPT_DEFAULTS
        ):
            _add(entry)

        sb = storyboard if isinstance(storyboard, dict) else {}
        for entry in _safe_list(sb.get("negative_constraints")):
            _add(entry)

        pr = provider_request_preview if isinstance(provider_request_preview, dict) else {}
        pr_negative = pr.get("negative_prompt")
        if isinstance(pr_negative, str):
            for fragment in pr_negative.split(","):
                _add(fragment)

        ta = topic_analysis if isinstance(topic_analysis, dict) else {}
        for risk in _safe_list(ta.get("risk_points")):
            risk_text = _safe_str(risk).strip()
            if risk_text:
                _add(f"avoid: {risk_text}")

        if not items:
            items = list(DEFAULT_NEGATIVE_PROMPT_DEFAULTS)

        joined = ", ".join(items)
        if _CJK_RE.search(joined):
            joined = _CJK_RE.sub("", joined)
        return joined

    # ------------------------------------------------------------------
    # Debug payload
    # ------------------------------------------------------------------
    def build_debug_payload(
        self,
        topic: str,
        language: str,
        input_language: str,
        seedance_prompt: str,
        negative_prompt: str,
        warnings: List[str],
        inputs_present: Dict[str, bool],
        normalized_input: Optional[Dict[str, Any]] = None,
        prompt_quality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = self.profile or {}
        section_order = _safe_list(profile.get("section_order")) or [
            "Task",
            "Format",
            "Voiceover",
            "Core explanation",
            "Scene plan",
            "Allowed on-screen text",
            "Text rules",
            "Motion",
            "Negative constraints",
            "Final rules",
        ]

        n = normalized_input or {}
        scene_count = len(n.get("scene_plan") or [])
        duration_seconds = int(n.get("duration_seconds") or DEFAULT_DURATION_SECONDS)
        aspect_ratio = n.get("aspect_ratio") or DEFAULT_ASPECT_RATIO

        prompt_words = len(seedance_prompt.split())
        prompt_chars = len(seedance_prompt)
        negative_words = len(negative_prompt.split())
        negative_chars = len(negative_prompt)

        prompt_has_cjk = bool(_CJK_RE.search(seedance_prompt))
        negative_has_cjk = bool(_CJK_RE.search(negative_prompt))

        prompt_metrics = {
            "prompt_words": prompt_words,
            "negative_prompt_words": negative_words,
            "prompt_chars": prompt_chars,
            "negative_prompt_chars": negative_chars,
            "scene_count": scene_count,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "orientation": n.get("orientation") or DEFAULT_ORIENTATION,
            "resolution": n.get("resolution") or DEFAULT_RESOLUTION,
            "prompt_contains_cjk": prompt_has_cjk,
            "negative_prompt_contains_cjk": negative_has_cjk,
            "english_subject": n.get("english_subject") or "",
            "english_question": n.get("english_question") or "",
            "correct_answer": n.get("correct_answer") or "",
        }

        compiler_checks = {
            "uses_notebooklm_template": False,
            "single_narrator_required": True,
            "single_narrator_monologue_required": True,
            "no_dialogue_required": True,
            "no_interview_required": True,
            "no_podcast_required": True,
            "no_two_host_conversation_required": True,
            "no_multiple_speakers_required": True,
            "english_only_on_screen_text_required": True,
            "no_cjk_required": True,
            "no_misspelled_text_required": True,
            "only_provided_on_screen_text_required": True,
            "max_8_words_per_on_screen_text_item": True,
            "landscape_16_9_required": True,
            "resolution_1920x1080_required": True,
            "english_voiceover_required": True,
            "no_does_not_yet_generate_audio_text": (
                "does not yet generate audio" not in seedance_prompt.lower()
            ),
            "large_text_required": True,
            "accuracy_constraints_included": True,
            "storyboard_included": scene_count > 0,
            "network_call_performed": False,
            "real_video_generated": False,
            "prompt_quality_gate_passed": bool((prompt_quality or {}).get("passed", False)),
        }

        return {
            "schema_version": DEBUG_SCHEMA_VERSION,
            "compiler_version": COMPILER_VERSION,
            "profile_version": profile.get("profile_version", PROFILE_SCHEMA_VERSION),
            "profile_loaded_from": self._profile_loaded_from,
            "provider": self.provider,
            "future_provider": self.future_provider,
            "compiled_at": _utc_now_iso(),
            "topic": topic,
            "language": language,
            "input_language": input_language,
            "section_order": section_order,
            "inputs_present": inputs_present,
            "prompt_strategy": profile.get("prompt_strategy", "scene_by_scene"),
            "preferred_prompt_language": profile.get("preferred_prompt_language", "en"),
            "negative_prompt_count": len(
                [x for x in negative_prompt.split(",") if x.strip()]
            ),
            "seedance_prompt_char_length": len(seedance_prompt),
            "seedance_prompt_word_count": len(seedance_prompt.split()),
            "prompt_metrics": prompt_metrics,
            "compiler_checks": compiler_checks,
            "normalized_input": n,
            "prompt_quality": prompt_quality or {},
            "warnings": list(warnings),
            "network_call_performed": False,
            "real_video_generated": False,
        }


__all__ = [
    "SeedancePromptCompiler",
    "COMPILER_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "DEBUG_SCHEMA_VERSION",
    "BANNED_PLACEHOLDER_STRINGS",
    "BANNED_STANDALONE_TOKENS",
    "REQUIRED_PROMPT_KEYWORDS",
    "GENERIC_OST_FRAGMENTS",
    "normalize_seedance_prompt_input",
    "validate_seedance_prompt_quality",
]
