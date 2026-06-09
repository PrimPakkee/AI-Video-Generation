"""Local BGM library selector (v0.6.5).

The LLM picks a track filename from ``assets/bgm/manifest.json``. This
module loads the manifest, validates the file exists on disk, and resolves
the chosen track to a usable absolute path. It NEVER calls a remote audio
generation service — we ship a curated local library instead.

Operator overrides:
    IMAGE_VIDEO_DISABLE_BGM=1      Skip BGM entirely (ffmpeg mux skipped).
    IMAGE_VIDEO_BGM_FORCE=<file>   Override the LLM and use this filename.

Hygiene: this file does not import requests, openai, or any network
library. It only reads JSON + checks file existence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BGM_DIR = PROJECT_ROOT / "assets" / "bgm"
DEFAULT_MANIFEST_PATH = DEFAULT_BGM_DIR / "manifest.json"


class BgmSelectionError(Exception):
    """Raised when no usable BGM track can be resolved."""


@dataclass
class BgmTrack:
    filename: str
    display_name: str
    mood_keywords: List[str] = field(default_factory=list)
    fits: str = ""
    tempo: str = ""
    energy: str = ""
    instruments: str = ""
    absolute_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "display_name": self.display_name,
            "mood_keywords": list(self.mood_keywords or []),
            "fits": self.fits,
            "tempo": self.tempo,
            "energy": self.energy,
            "instruments": self.instruments,
            "exists": bool(self.absolute_path is not None),
        }


def bgm_disabled_by_env() -> bool:
    flag = (os.getenv("IMAGE_VIDEO_DISABLE_BGM") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def load_bgm_manifest(
    manifest_path: Optional[Path] = None,
) -> Tuple[List[BgmTrack], Optional[BgmTrack], Dict[str, Any]]:
    """Load the BGM manifest and return ``(tracks, default_track, debug)``.

    ``tracks`` only contains entries whose mp3 actually exists on disk.
    ``default_track`` is the manifest's ``default_track`` if it resolved.
    """
    debug: Dict[str, Any] = {
        "manifest_path": str(manifest_path or DEFAULT_MANIFEST_PATH),
        "manifest_exists": False,
        "tracks_total": 0,
        "tracks_resolved": 0,
        "tracks_missing_files": [],
        "default_track": None,
        "default_track_resolved": False,
        "schema_version": None,
        "error": None,
    }
    path = Path(manifest_path or DEFAULT_MANIFEST_PATH)
    if not path.exists():
        debug["error"] = f"manifest not found at {path}"
        return [], None, debug
    debug["manifest_exists"] = True

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        debug["error"] = f"manifest parse failed: {type(exc).__name__}: {exc}"
        return [], None, debug

    debug["schema_version"] = data.get("schema_version")
    raw_tracks = data.get("tracks") or []
    debug["tracks_total"] = len(raw_tracks)

    bgm_dir = path.parent
    resolved: List[BgmTrack] = []
    missing: List[str] = []
    for entry in raw_tracks:
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("filename") or "").strip()
        if not filename:
            continue
        track_path = bgm_dir / filename
        if not track_path.exists():
            missing.append(filename)
            continue
        resolved.append(BgmTrack(
            filename=filename,
            display_name=str(entry.get("display_name") or filename),
            mood_keywords=list(entry.get("mood_keywords") or []),
            fits=str(entry.get("fits") or ""),
            tempo=str(entry.get("tempo") or ""),
            energy=str(entry.get("energy") or ""),
            instruments=str(entry.get("instruments") or ""),
            absolute_path=track_path,
        ))
    debug["tracks_resolved"] = len(resolved)
    debug["tracks_missing_files"] = missing

    default_filename = str(data.get("default_track") or "").strip()
    debug["default_track"] = default_filename or None
    default_track: Optional[BgmTrack] = None
    if default_filename:
        for t in resolved:
            if t.filename == default_filename:
                default_track = t
                debug["default_track_resolved"] = True
                break
    if default_track is None and resolved:
        default_track = resolved[0]
    return resolved, default_track, debug


def list_bgm_tracks(manifest_path: Optional[Path] = None) -> List[BgmTrack]:
    tracks, _, _ = load_bgm_manifest(manifest_path)
    return tracks


def resolve_bgm_track(
    chosen_filename: Optional[str],
    manifest_path: Optional[Path] = None,
) -> Tuple[Optional[BgmTrack], Dict[str, Any]]:
    """Resolve a chosen filename (typically from the LLM's bgm_choice) to
    a real BgmTrack. Honors ``IMAGE_VIDEO_DISABLE_BGM`` (returns ``None``)
    and ``IMAGE_VIDEO_BGM_FORCE`` (operator override).

    Returns ``(track_or_None, debug)``. Never raises.
    """
    debug: Dict[str, Any] = {
        "disabled_by_env": False,
        "forced_by_env": None,
        "chosen_filename": chosen_filename,
        "resolved_filename": None,
        "fallback_used": False,
        "fallback_reason": None,
        "manifest_debug": None,
    }

    if bgm_disabled_by_env():
        debug["disabled_by_env"] = True
        debug["fallback_reason"] = "IMAGE_VIDEO_DISABLE_BGM enabled"
        return None, debug

    forced = (os.getenv("IMAGE_VIDEO_BGM_FORCE") or "").strip()
    if forced:
        debug["forced_by_env"] = forced

    tracks, default_track, manifest_debug = load_bgm_manifest(manifest_path)
    debug["manifest_debug"] = manifest_debug

    if not tracks:
        debug["fallback_reason"] = (
            "BGM manifest produced no usable tracks "
            f"({manifest_debug.get('error') or 'no tracks resolved'})"
        )
        return None, debug

    by_filename = {t.filename: t for t in tracks}
    by_filename_lower = {t.filename.lower(): t for t in tracks}

    def _lookup(name: str) -> Optional[BgmTrack]:
        if not name:
            return None
        if name in by_filename:
            return by_filename[name]
        return by_filename_lower.get(name.lower())

    if forced:
        forced_track = _lookup(forced)
        if forced_track is not None:
            debug["resolved_filename"] = forced_track.filename
            return forced_track, debug
        debug["fallback_reason"] = (
            f"IMAGE_VIDEO_BGM_FORCE={forced!r} not found in manifest"
        )
        # fall through to default below

    chosen_track = _lookup(chosen_filename or "")
    if chosen_track is not None:
        debug["resolved_filename"] = chosen_track.filename
        return chosen_track, debug

    debug["fallback_used"] = True
    if not chosen_filename:
        debug["fallback_reason"] = "no bgm_choice from LLM; using default"
    else:
        debug["fallback_reason"] = (
            f"LLM chose {chosen_filename!r} but it isn't in the manifest; "
            "using default"
        )
    if default_track is not None:
        debug["resolved_filename"] = default_track.filename
        return default_track, debug

    debug["fallback_reason"] = (
        debug["fallback_reason"] or "no resolvable track and no default"
    )
    return None, debug
