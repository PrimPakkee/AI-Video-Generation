"""
SeedancePromptCompiler (v0.5.6).

Compiles structured Video Mode content assets (topic_analysis / reasoning /
video_script / storyboard / provider_request_preview) into a Seedance-shaped
prompt bundle: a primary ``seedance_prompt.txt``, a structured negative
prompt, and a debug payload that captures the compilation decisions.

The compiler is deliberately offline:

* No real Seedance API is called.
* No HTTP request of any kind is performed.
* No real mp4 is generated and no real video URL is produced.
* The NotebookLM Prompt Mode template is **not** imported.

The compiler is the v0.5.6 contract layer. v0.6.0 will read the produced
``seedance_prompt.txt`` directly when it makes the first real Seedance call.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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


COMPILER_VERSION = "seedance_prompt_compiler_v0.5.6"
PROFILE_SCHEMA_VERSION = "seedance_prompt_profile_v0.5.6"
DEBUG_SCHEMA_VERSION = "seedance_prompt_debug_v0.5.6"

DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "provider_profiles"
    / "seedance.json"
)

DEFAULT_NEGATIVE_PROMPT_DEFAULTS: List[str] = [
    "no dialogue",
    "no interview",
    "no podcast",
    "no two-host conversation",
    "no multiple speakers",
    "no off-topic decoration",
    "no wrong answer",
    "no unsupported visual claims",
    "no real human faces",
    "no copyrighted characters",
    "no logos or watermarks",
    "no text rendering errors",
    "no flicker",
    "no extreme camera movement",
]

DEFAULT_MUST_INCLUDE: List[str] = [
    "single narrator only",
    "no dialogue",
    "no two-host conversation",
    "no podcast format",
    "white background",
    "clean whiteboard line-art visuals",
    "large readable on-screen text",
    "visuals must match narration",
    "the final answer shown must be correct",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


class SeedancePromptCompiler:
    """Offline Seedance prompt compiler.

    The compiler converts structured content assets into a Seedance-flavored
    prompt without ever touching the network. It is the v0.5.6 deliverable;
    v0.6.0 will feed the compiled ``seedance_prompt.txt`` into the first
    real Seedance call.
    """

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

        resolved_topic = (
            topic
            or ta.get("topic")
            or pr.get("topic")
            or "Educational short video topic"
        )
        resolved_language = (
            language
            or ta.get("language")
            or pr.get("language")
            or self.profile.get("preferred_prompt_language")
            or "en"
        )

        seedance_prompt = self.build_seedance_prompt(
            topic=_safe_str(resolved_topic),
            language=_safe_str(resolved_language),
            topic_analysis=ta,
            reasoning=rs,
            script=sc,
            storyboard=sb,
            provider_request_preview=pr,
        )

        negative_prompt = self.build_negative_prompt(
            topic_analysis=ta, storyboard=sb, provider_request_preview=pr,
        )

        debug_payload = self.build_debug_payload(
            topic=_safe_str(resolved_topic),
            language=_safe_str(resolved_language),
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
            storyboard=sb,
            provider_request_preview=pr,
        )

        return {
            "compiler_version": COMPILER_VERSION,
            "profile_version": self.profile.get("profile_version", PROFILE_SCHEMA_VERSION),
            "provider": self.provider,
            "future_provider": self.future_provider,
            "network_call_performed": False,
            "real_video_generated": False,
            "topic": _safe_str(resolved_topic),
            "language": _safe_str(resolved_language),
            "seedance_prompt": seedance_prompt,
            "negative_prompt": negative_prompt,
            "seedance_prompt_debug": debug_payload,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------
    def build_seedance_prompt(
        self,
        topic: str,
        language: str,
        topic_analysis: Dict[str, Any],
        reasoning: Dict[str, Any],
        script: Dict[str, Any],
        storyboard: Dict[str, Any],
        provider_request_preview: Dict[str, Any],
    ) -> str:
        profile = self.profile or {}
        duration = (
            provider_request_preview.get("target_duration_seconds")
            or provider_request_preview.get("duration_seconds")
            or storyboard.get("duration_seconds")
            or profile.get("default_duration_seconds")
            or 5
        )
        try:
            duration = int(duration)
        except Exception:
            duration = 5
        aspect_ratio = (
            storyboard.get("aspect_ratio")
            or provider_request_preview.get("aspect_ratio")
            or profile.get("default_aspect_ratio")
            or "9:16"
        )
        resolution = (
            provider_request_preview.get("resolution")
            or profile.get("default_resolution")
            or "1080x1920"
        )
        fps = (
            provider_request_preview.get("fps")
            or profile.get("default_fps")
            or 24
        )
        style = (
            storyboard.get("style")
            or provider_request_preview.get("style")
            or profile.get("default_style")
            or "clean whiteboard line-art educational short video"
        )

        core_concept = _safe_str(topic_analysis.get("core_concept"), topic)
        video_goal = _sync_duration_text(
            _safe_str(
                topic_analysis.get("video_goal"),
                f"Explain {topic} clearly in a {duration}-second educational short video.",
            ),
            duration,
        )
        target_audience = _safe_str(
            topic_analysis.get("target_audience"), "students and short-video viewers"
        )
        correct_answer = _safe_str(reasoning.get("correct_answer"), "Human review required.")
        key_teaching_point = _safe_str(reasoning.get("key_teaching_point"), "")
        common_wrong = _safe_str(reasoning.get("common_wrong_intuition"), "")
        steps = _safe_list(reasoning.get("step_by_step_reasoning"))

        hook = _safe_str(script.get("hook"), f"Here's something surprising about {topic}.")
        narration = _safe_str(script.get("narration"), "")
        ending = _safe_str(script.get("ending"), "")
        on_screen_text = _safe_list(script.get("on_screen_text"))
        timing_plan = _safe_list(script.get("timing_plan"))

        scenes = _safe_list(storyboard.get("scenes"))

        visual_defaults = profile.get("visual_defaults") or {}
        must_include = _safe_list(profile.get("must_include_constraints")) or list(
            DEFAULT_MUST_INCLUDE
        )

        sections: List[str] = []

        sections.append(
            f"# Seedance Educational Short Video Prompt\n"
            f"Topic: {topic}\n"
            f"Target language: {language}\n"
            f"Duration: {duration} seconds\n"
            f"Aspect ratio: {aspect_ratio}\n"
            f"Resolution: {resolution}\n"
            f"Frame rate: {fps} fps"
        )

        sections.append(
            "## Video Goal\n"
            f"- Subject: {topic}\n"
            f"- Core concept: {core_concept}\n"
            f"- Goal: {video_goal}\n"
            f"- Target audience: {target_audience}"
        )

        sections.append(
            "## Visual Style\n"
            f"- Overall style: {style}\n"
            f"- Background: {visual_defaults.get('background', 'pure white')}\n"
            f"- Line art: {visual_defaults.get('line_art', 'hand-drawn black line')}\n"
            f"- Text size: {visual_defaults.get('text_size', 'large')} and "
            f"{visual_defaults.get('text_color', 'black')}\n"
            f"- Highlight color: {visual_defaults.get('highlight_color', 'yellow')}\n"
            f"- Answer box: {visual_defaults.get('answer_box_color', 'yellow')} highlight"
        )

        sections.append(
            "## Narration Mode\n"
            "- Single narrator monologue ONLY.\n"
            "- No dialogue, no two-host conversation, no podcast format, no interview format.\n"
            "- One voice carries the entire video.\n"
            f"- Hook line: {hook}\n"
            f"- Closing line: {ending}\n"
            f"- Narration body: {narration}"
        )

        explanation_lines: List[str] = []
        if common_wrong:
            explanation_lines.append(f"- Common wrong intuition: {common_wrong}")
        if steps:
            explanation_lines.append("- Step-by-step reasoning:")
            for idx, step in enumerate(steps, start=1):
                explanation_lines.append(f"  {idx}. {_safe_str(step)}")
        if correct_answer:
            explanation_lines.append(f"- Correct answer (must be shown correctly on screen): {correct_answer}")
        if key_teaching_point:
            explanation_lines.append(f"- Key teaching point: {key_teaching_point}")
        if not explanation_lines:
            explanation_lines.append("- (no explicit reasoning supplied; rely on storyboard)")
        sections.append("## Core Explanation\n" + "\n".join(explanation_lines))

        scene_lines: List[str] = []
        if scenes:
            for sc_item in scenes:
                if not isinstance(sc_item, dict):
                    continue
                scene_id = sc_item.get("scene_id", "?")
                tr = sc_item.get("time_range", "")
                visual = _safe_str(sc_item.get("visual"))
                narr = _safe_str(sc_item.get("narration"))
                ost = _safe_str(sc_item.get("on_screen_text"))
                camera = _safe_str(sc_item.get("camera"))
                notes = _safe_str(sc_item.get("notes"))
                scene_lines.append(
                    f"- Scene {scene_id} ({tr}):\n"
                    f"  visual: {visual}\n"
                    f"  narration: {narr}\n"
                    f"  on-screen text: {ost}\n"
                    f"  camera: {camera}\n"
                    f"  notes: {notes}"
                )
        else:
            scene_lines.append("- (no storyboard scenes supplied)")
        if timing_plan:
            scene_lines.append("- Timing plan: " + " | ".join(_safe_str(t) for t in timing_plan))
        sections.append("## Scene-by-scene Storyboard\n" + "\n".join(scene_lines))

        ost_rules: List[str] = [
            "- On-screen text must be large, high-contrast, and readable on a phone in 1 second.",
            "- On-screen text must match what the narrator is saying at that moment.",
            "- Highlight the answer in a yellow box.",
            "- Avoid decorative typography; favor a single legible sans-serif look.",
        ]
        if on_screen_text:
            ost_rules.append("- Required on-screen text fragments:")
            for ost in on_screen_text:
                ost_rules.append(f"  - {_safe_str(ost)}")
        sections.append("## On-screen Text Rules\n" + "\n".join(ost_rules))

        sections.append(
            "## Motion\n"
            f"- Camera: {visual_defaults.get('camera', 'mostly static, gentle zoom only')}.\n"
            f"- Transitions: {visual_defaults.get('transitions', 'simple cut, occasional cross-fade')}.\n"
            "- No extreme camera moves, no shake, no flicker."
        )

        constraint_lines = ["## Final Constraints"]
        for c in must_include:
            constraint_lines.append(f"- {_safe_str(c)}")
        constraint_lines.extend([
            "- The final answer shown on screen must match the correct answer above.",
            "- Visuals must support the narration, not contradict or distract from it.",
            "- Output must remain a single-narrator educational short video.",
            f"- Mandatory duration: {duration} seconds.",
            "- Ignore any conflicting duration instruction from earlier content.",
        ])
        sections.append("\n".join(constraint_lines))

        return "\n\n".join(sections).strip() + "\n"

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

        return ", ".join(items)

    # ------------------------------------------------------------------
    # Debug payload
    # ------------------------------------------------------------------
    def build_debug_payload(
        self,
        topic: str,
        language: str,
        seedance_prompt: str,
        negative_prompt: str,
        warnings: List[str],
        inputs_present: Dict[str, bool],
        storyboard: Optional[Dict[str, Any]] = None,
        provider_request_preview: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = self.profile or {}
        section_order = _safe_list(profile.get("section_order")) or [
            "Video Goal",
            "Visual Style",
            "Narration Mode",
            "Core Explanation",
            "Scene-by-scene Storyboard",
            "On-screen Text Rules",
            "Motion",
            "Final Constraints",
        ]

        sb = storyboard if isinstance(storyboard, dict) else {}
        pr = provider_request_preview if isinstance(provider_request_preview, dict) else {}

        scenes = _safe_list(sb.get("scenes"))
        scene_count = len([s for s in scenes if isinstance(s, dict)])

        duration_seconds = (
            pr.get("target_duration_seconds")
            or pr.get("duration_seconds")
            or sb.get("duration_seconds")
            or profile.get("default_duration_seconds")
            or 5
        )
        try:
            duration_seconds = int(duration_seconds)
        except Exception:
            duration_seconds = 5
        aspect_ratio = (
            sb.get("aspect_ratio")
            or pr.get("aspect_ratio")
            or profile.get("default_aspect_ratio")
            or ""
        )

        negative_prompt_words = len(negative_prompt.split())
        negative_prompt_chars = len(negative_prompt)
        prompt_words = len(seedance_prompt.split())
        prompt_chars = len(seedance_prompt)

        prompt_metrics = {
            "prompt_words": prompt_words,
            "negative_prompt_words": negative_prompt_words,
            "prompt_chars": prompt_chars,
            "negative_prompt_chars": negative_prompt_chars,
            "scene_count": scene_count,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
        }

        compiler_checks = {
            "uses_notebooklm_template": False,
            "single_narrator_required": True,
            "no_dialogue_required": True,
            "no_interview_required": True,
            "no_podcast_required": True,
            "no_multiple_speakers_required": True,
            "large_text_required": True,
            "accuracy_constraints_included": True,
            "storyboard_included": scene_count > 0,
            "network_call_performed": False,
            "real_video_generated": False,
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
            "section_order": section_order,
            "inputs_present": inputs_present,
            "prompt_strategy": profile.get("prompt_strategy", "scene_by_scene"),
            "preferred_prompt_language": profile.get("preferred_prompt_language", "en"),
            "must_include_constraints": _safe_list(profile.get("must_include_constraints"))
            or list(DEFAULT_MUST_INCLUDE),
            "negative_prompt_count": len(
                [x for x in negative_prompt.split(",") if x.strip()]
            ),
            "seedance_prompt_char_length": len(seedance_prompt),
            "seedance_prompt_word_count": len(seedance_prompt.split()),
            "prompt_metrics": prompt_metrics,
            "compiler_checks": compiler_checks,
            "warnings": list(warnings),
            "network_call_performed": False,
            "real_video_generated": False,
        }


__all__ = [
    "SeedancePromptCompiler",
    "COMPILER_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "DEBUG_SCHEMA_VERSION",
]
