#!/usr/bin/env python3
"""Smoke test for the edge-tts narration provider (v0.6.7).

Run from project root:
    source .venv/bin/activate && python scripts/test_edge_tts.py

If it succeeds, you'll get an mp3 you can `open` to hear the voice.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Manually load .env so EDGE_TTS_VOICE etc. are picked up.
import os
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

from web.audio_providers.edge_tts_provider import (
    synthesize_narration,
    EdgeTtsError,
)


SAMPLE = (
    "Why does a small change sometimes cause a huge result? "
    "Mathematicians call this the butterfly effect. "
    "It is not magic. It is the way tiny errors grow over time. "
    "Today we will explore why a single flap can shift the whole forecast."
)


def main():
    output = PROJECT_ROOT / "scripts" / "edge_tts_test_output.mp3"
    voice = os.environ.get("EDGE_TTS_VOICE") or "en-US-AriaNeural"
    print(f"Voice: {voice}")
    print(f"Text length: {len(SAMPLE)} chars")
    print(f"Synthesizing -> {output}")
    print()
    try:
        result = synthesize_narration(SAMPLE, output)
    except EdgeTtsError as exc:
        print(f"FAILED: {exc}")
        return 1
    print("SUCCESS")
    print(f"  voice_id:        {result.voice_id}")
    print(f"  duration_seconds: {result.duration_seconds:.2f}")
    print(f"  char_count:      {result.char_count}")
    print(f"  size on disk:    {result.audio_path.stat().st_size} bytes")
    print()
    print("Play it:")
    print(f"  open '{result.audio_path}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
