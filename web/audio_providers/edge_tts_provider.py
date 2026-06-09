"""Microsoft Edge TTS narration provider (v0.6.7).

Uses the open-source `edge-tts` package — no API key, no quota, no
payment-tier gates. Voices come from Microsoft's Azure Edge service
(the same neural voices the Edge browser uses for "Read Aloud").

Why this over ElevenLabs in v0.6.7:
  - Free tier ElevenLabs locks library voices behind paid plans.
  - Edge-tts is fully free, no auth.
  - English voices like en-US-AriaNeural / en-US-JennyNeural sound
    competitive with ElevenLabs Rachel for narration use cases.

Public API matches the previous ElevenLabs provider so the pipeline
caller doesn't need to change shape:
    synthesize_narration(text, output_path, voice_id?, ...) -> TtsResult
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


DEFAULT_VOICE = "en-US-AriaNeural"   # neutral female, news-anchor quality
DEFAULT_RATE = "+0%"
DEFAULT_VOLUME = "+0%"


class EdgeTtsError(RuntimeError):
    """Raised when synthesis fails."""


@dataclass
class SentenceTiming:
    """One sentence with its on-screen start/end (seconds, relative to
    the start of the audio file). Edge-tts streams SentenceBoundary
    events with 100-nanosecond ticks; we convert to seconds here so
    callers don't need to."""
    text: str
    start_s: float
    end_s: float


@dataclass
class TtsResult:
    audio_path: Path
    duration_seconds: float
    voice_id: str
    model_id: str
    char_count: int
    sentence_timings: List[SentenceTiming] = field(default_factory=list)


def _probe_duration_seconds(audio_path: Path) -> float:
    """Use ffprobe to measure mp3 duration (we already depend on ffmpeg
    for compose, so ffprobe is essentially free)."""
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        out = subprocess.check_output(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(audio_path),
            ],
            stderr=subprocess.STDOUT,
            timeout=15,
        )
        data = json.loads(out)
        return float(data.get("format", {}).get("duration") or 0.0)
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return 0.0


async def _run_edge_tts(text: str, voice: str, rate: str, volume: str,
                        output_path: Path) -> List[SentenceTiming]:
    """Stream the synthesis to disk and capture SentenceBoundary events.

    edge-tts's `stream()` yields:
      - {"type": "audio", "data": <bytes>} → write to disk
      - {"type": "SentenceBoundary", "offset": N, "duration": N, "text": "..."}
        offsets/durations are in 100-ns ticks → / 1e7 = seconds.

    SentenceBoundary is what we want: each subtitle line corresponds to
    exactly one sentence the TTS spoke, so the start/end times are
    word-perfect — whatever is on screen is exactly what is being said.
    """
    import edge_tts
    communicate = edge_tts.Communicate(
        text, voice=voice, rate=rate, volume=volume,
        boundary="SentenceBoundary",
    )
    sentence_timings: List[SentenceTiming] = []
    with open(output_path, "wb") as audio_out:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_out.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                offset = chunk.get("offset", 0)
                duration = chunk.get("duration", 0)
                sent_text = (chunk.get("text") or "").strip()
                if not sent_text:
                    continue
                sentence_timings.append(SentenceTiming(
                    text=sent_text,
                    start_s=offset / 1e7,
                    end_s=(offset + duration) / 1e7,
                ))
    return sentence_timings


def synthesize_narration(
    text: str,
    output_path: Path,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,           # accepted for API compat — ignored
    api_key: Optional[str] = None,            # accepted for API compat — ignored
    timeout_seconds: int = 120,               # accepted for API compat
    retry_attempts: int = 3,
) -> TtsResult:
    """Synthesize `text` with edge-tts and save the resulting mp3.

    `voice_id` defaults to en-US-AriaNeural. Override via the
    EDGE_TTS_VOICE env var or the parameter. `model_id` is accepted but
    ignored — edge-tts doesn't expose a model selector.
    """
    text = (text or "").strip()
    if not text:
        raise EdgeTtsError("Empty narration text — nothing to synthesize.")

    voice = voice_id or os.environ.get("EDGE_TTS_VOICE", "").strip() or DEFAULT_VOICE
    rate = os.environ.get("EDGE_TTS_RATE", DEFAULT_RATE).strip() or DEFAULT_RATE
    volume = os.environ.get("EDGE_TTS_VOLUME", DEFAULT_VOLUME).strip() or DEFAULT_VOLUME

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: Optional[Exception] = None
    for attempt in range(1, retry_attempts + 1):
        try:
            sentence_timings = asyncio.run(
                _run_edge_tts(text, voice, rate, volume, output_path)
            )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise EdgeTtsError(
                    f"edge-tts wrote no bytes to {output_path}. "
                    f"Voice '{voice}' may be unavailable."
                )
            duration = _probe_duration_seconds(output_path)
            if duration <= 0.0:
                raise EdgeTtsError(
                    f"Saved mp3 at {output_path} but ffprobe could not "
                    f"measure its duration — file may be corrupt."
                )
            return TtsResult(
                audio_path=output_path,
                duration_seconds=duration,
                voice_id=voice,
                model_id="edge-tts",
                char_count=len(text),
                sentence_timings=sentence_timings,
            )
        except Exception as exc:
            last_error = exc
            if attempt < retry_attempts:
                # Edge-tts failures are usually transient network blips;
                # a short fixed sleep is enough.
                import time
                time.sleep(min(2 ** (attempt - 1), 4))

    assert last_error is not None
    if isinstance(last_error, EdgeTtsError):
        raise last_error
    raise EdgeTtsError(
        f"edge-tts failed after {retry_attempts} attempts: {last_error}"
    ) from last_error
