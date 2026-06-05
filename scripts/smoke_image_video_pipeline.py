#!/usr/bin/env python3
"""
Offline smoke test for the v0.6.3 Image Video pipeline.

Default behaviour (no flags):
    - 100% local, no network. Sets ``IMAGE_VIDEO_DISABLE_LLM=1`` so the
      pipeline never reaches out to AI_VIDEO_LLM_*. Static slide template
      is used. NEVER calls APX, Seedance, Image2, or TTS.
    - Runs durations 5s / 15s / 30s.

Flags:
    --with-llm   Allow the pipeline to call AI_VIDEO_LLM_* (gpt-5-chat by
                 default). Use only when explicitly testing LLM content.
    --full       Add 60s and 90s to the duration set.

Examples:
    python3 scripts/smoke_image_video_pipeline.py
    python3 scripts/smoke_image_video_pipeline.py --full
    python3 scripts/smoke_image_video_pipeline.py --with-llm --full
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


SMOKE_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "smoke_tests"

DURATION_TITLES = [
    (5,  "A"),
    (15, "Why is the average misleading?"),
    (30, "Why does Simpson paradox happen with overall expected value ratio compare"),
    (60, "Why does Simpson paradox happen with overall expected value ratio compare proof illusion logic group"),
    (90, "Why does Simpson paradox happen with overall expected value ratio compare proof illusion logic group fallacy puzzle bayes monty"),
]


def _check_pipeline(generate_fn, resolve_fn, ranges, title: str, duration: int,
                    output_dir: Path) -> dict:
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = generate_fn(
        title=title,
        duration_seconds=duration,
        output_dir=output_dir,
        slug=f"smoke_{duration}s",
    )

    failures: list[str] = []

    expected_lo, expected_hi = ranges[duration]
    sc = result.get("slide_count")
    if sc is None or not (expected_lo <= int(sc) <= expected_hi):
        failures.append(
            f"slide_count={sc} not in [{expected_lo}, {expected_hi}]"
        )

    # Per-provider flags must always be False on the image_video route.
    for flag in ("seedance_called", "apx_called", "image2_called", "tts_called"):
        if result.get(flag):
            failures.append(f"{flag} must be False")
    if result.get("media_api_called"):
        failures.append("media_api_called must be False on image_video route")
    if result.get("has_audio"):
        failures.append("has_audio must be False")
    if result.get("tts_status") != "not_implemented_v0.6.3":
        failures.append(
            f"tts_status={result.get('tts_status')} != 'not_implemented_v0.6.3'"
        )

    slide_plan_path = result.get("slide_plan_path")
    overlay_plan_path = result.get("overlay_plan_path")
    if not slide_plan_path or not Path(slide_plan_path).exists():
        failures.append("slide_plan.json missing")
    if not overlay_plan_path or not Path(overlay_plan_path).exists():
        failures.append("overlay_plan.json missing")

    slides_dir = result.get("slides_dir")
    if not slides_dir:
        failures.append("slides_dir missing")
    else:
        png_files = sorted(Path(slides_dir).glob("slide_*.png"))
        if len(png_files) != int(sc or 0):
            failures.append(
                f"slides/*.png count {len(png_files)} != slide_count {sc}"
            )

    if shutil.which("ffmpeg") or os.getenv("FFMPEG_BIN"):
        # Use the pipeline's own resolver to mirror production behaviour.
        ffmpeg_path, _ = resolve_fn()
    else:
        ffmpeg_path, _ = resolve_fn()

    if ffmpeg_path:
        if result.get("route_status") != "succeeded":
            failures.append(
                f"FFmpeg present ({ffmpeg_path}) but route_status="
                f"{result.get('route_status')} (error={result.get('error')})"
            )
        final = result.get("final_video_path")
        if not final or not Path(final).exists():
            failures.append("final_video.mp4 missing")
    else:
        if result.get("route_status") != "failed":
            failures.append(
                f"FFmpeg missing but route_status={result.get('route_status')}"
            )
        msg = result.get("error") or ""
        if "FFmpeg is required for Image Video composition" not in msg:
            failures.append(f"FFmpeg-missing message wrong: {msg!r}")
        if "brew install ffmpeg" not in msg.lower():
            failures.append("FFmpeg-missing message should mention brew install ffmpeg")

    return {
        "duration": duration,
        "slide_count": sc,
        "route_status": result.get("route_status"),
        "ffmpeg_present": bool(ffmpeg_path),
        "content_source": result.get("content_source"),
        "content_llm_called": bool(result.get("content_llm_called")),
        "media_api_called": bool(result.get("media_api_called")),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline smoke test for the Image Video pipeline."
    )
    parser.add_argument(
        "--with-llm", action="store_true",
        help="Allow the pipeline to call AI_VIDEO_LLM_* (default: disabled).",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Add 60s and 90s durations (default: 5/15/30s only).",
    )
    args = parser.parse_args()

    offline_mode = not args.with_llm
    if offline_mode:
        os.environ["IMAGE_VIDEO_DISABLE_LLM"] = "1"
    elif "IMAGE_VIDEO_DISABLE_LLM" in os.environ:
        del os.environ["IMAGE_VIDEO_DISABLE_LLM"]

    # Import after env is set so the pipeline reads the flag correctly.
    from web.image_video_pipeline import (  # noqa: E402
        DURATION_SLIDE_RANGES,
        generate_image_video_package,
        resolve_ffmpeg_binary,
        resolve_slide_count,
    )

    ffmpeg_path, _ = resolve_ffmpeg_binary()
    print(f"[smoke] Image Video pipeline smoke test")
    print(f"[smoke] offline_mode = {offline_mode}")
    print(f"[smoke] with_llm     = {args.with_llm}")
    print(f"[smoke] ffmpeg       = {ffmpeg_path or '(not found)'}")
    print(f"[smoke] outputs      = {SMOKE_OUTPUT_ROOT}")
    print()

    SMOKE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if args.full:
        durations = [5, 15, 30, 60, 90]
    else:
        durations = [5, 15, 30]
    checks = [(t, d) for d, t in DURATION_TITLES if d in durations]

    print("[smoke] resolve_slide_count direct probes:")
    for d in durations:
        lo = resolve_slide_count(d, "A")
        hi = resolve_slide_count(d, DURATION_TITLES[-1][1])
        rng = DURATION_SLIDE_RANGES[d]
        print(f"   {d:>2}s -> simple={lo}, complex={hi}, range={rng}")
    print()

    overall_failures: list[str] = []
    for title, duration in checks:
        out_dir = SMOKE_OUTPUT_ROOT / f"image_video_{duration}s"
        report = _check_pipeline(
            generate_image_video_package,
            resolve_ffmpeg_binary,
            DURATION_SLIDE_RANGES,
            title, duration, out_dir,
        )
        status = "OK" if not report["failures"] else "FAIL"
        print(
            f"[smoke] {status:>4} duration={report['duration']:>2}s "
            f"slide_count={report['slide_count']} "
            f"route_status={report['route_status']} "
            f"ffmpeg={report['ffmpeg_present']} "
            f"content_source={report['content_source']} "
            f"content_llm_called={report['content_llm_called']} "
            f"media_api_called={report['media_api_called']}"
        )
        for line in report["failures"]:
            overall_failures.append(f"{report['duration']}s: {line}")
            print(f"     - {line}")

        # Offline mode invariant: never call the LLM, never call any media API.
        if offline_mode and report["content_llm_called"]:
            overall_failures.append(
                f"{report['duration']}s: offline mode but content_llm_called=True"
            )
        if report["media_api_called"]:
            overall_failures.append(
                f"{report['duration']}s: media_api_called must always be False"
            )

    print()
    if overall_failures:
        print(f"[smoke] FAILED: {len(overall_failures)} check(s) failed")
        return 1
    print("[smoke] PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
