"""Audio providers (v0.6.5+).

Currently shipped:
    - bgm_selector — picks a local mp3 from assets/bgm/manifest.json based
      on the LLM's bgm_choice. NEVER calls a TTS / music-generation API.

Future (planned):
    - apx_tts_provider — real text-to-speech for v0.6.5 narration phase.
"""

from .bgm_selector import (
    BgmSelectionError,
    BgmTrack,
    bgm_disabled_by_env,
    list_bgm_tracks,
    load_bgm_manifest,
    resolve_bgm_track,
)

__all__ = [
    "BgmSelectionError",
    "BgmTrack",
    "bgm_disabled_by_env",
    "list_bgm_tracks",
    "load_bgm_manifest",
    "resolve_bgm_track",
]
