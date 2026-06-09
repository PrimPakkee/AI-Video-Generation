"""APX gpt-image-2 image generation provider (v0.6.4).

This is the **only** file in the v0.6.4 image_video pipeline that is
allowed to make real network calls. It reads ``APX_IMAGE2_*`` from the
environment, posts a single ``images/generations`` request per slide,
and returns the decoded PNG bytes.

Hygiene:
    - The API key is read from the environment, never logged, never
      written to disk, never returned to the frontend.
    - Only ``api_key_configured: bool`` and the request shape (model /
      size / quality / endpoint host) appear in debug output.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict

from .base import (
    ImageProvider,
    ImageProviderError,
    RenderedImage,
    TransientImageProviderError,
)


class ApxImage2Provider(ImageProvider):
    """Real ``gpt-image-2`` provider via the company OpenAI-compatible gateway.

    Endpoint (default):
        POST {APX_IMAGE2_BASE_URL}/images/generations

    Headers:
        api-key: {APX_IMAGE2_API_KEY}     # the gateway's "appId:apiKey" string
        Content-Type: application/json

    Body:
        {"model": APX_IMAGE2_MODEL, "prompt": <prompt>,
         "size": APX_IMAGE2_SIZE, "quality": APX_IMAGE2_QUALITY}

    Response (verified 2026-06-05):
        {"created": ..., "data": [{"b64_json": "<png base64>"}],
         "size": "...", "quality": "...", "output_format": "png"}
    """

    name = "apx_image2"

    def __init__(self) -> None:
        self.base_url = (os.getenv("APX_IMAGE2_BASE_URL")
                         or "http://ai-service.tal.com/openai-compatible/v1").rstrip("/")
        self.model = os.getenv("APX_IMAGE2_MODEL") or "gpt-image-2"
        self.api_key = (os.getenv("APX_IMAGE2_API_KEY") or "").strip()
        self.default_size = os.getenv("APX_IMAGE2_SIZE") or "1792x1024"
        self.default_quality = os.getenv("APX_IMAGE2_QUALITY") or "high"
        try:
            # v0.6.5.1 — bumped from 180 → 300. The gateway's tail latency
            # routinely exceeds 180s for `quality=high`, which forced the
            # pipeline into Pillow fallback for those slides. With 300s the
            # tail gets covered while the new retry layer in the pipeline
            # handles whatever still times out.
            self.timeout = int(os.getenv("APX_IMAGE2_TIMEOUT", "300"))
        except Exception:
            self.timeout = 300

    def is_configured(self) -> bool:
        enabled = (os.getenv("APX_IMAGE2_ENABLED") or "").strip().lower()
        return enabled in ("1", "true", "yes", "on") and bool(self.api_key)

    def _safe_debug(self, **extra: Any) -> Dict[str, Any]:
        debug: Dict[str, Any] = {
            "provider": self.name,
            "endpoint": f"{self.base_url}/images/generations",
            "model": self.model,
            "default_size": self.default_size,
            "default_quality": self.default_quality,
            "api_key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout,
        }
        debug.update(extra)
        return debug

    def generate(
        self,
        prompt: str,
        *,
        size: str | None = None,
        quality: str | None = None,
    ) -> RenderedImage:
        if not self.is_configured():
            raise ImageProviderError(
                "APX_IMAGE2_ENABLED + APX_IMAGE2_API_KEY are required. "
                "Set them in .env (APX_IMAGE2_ENABLED=true, "
                "APX_IMAGE2_API_KEY=<your key>) and restart the server."
            )

        # Lazy import — keeps the rest of the module loadable when requests
        # is unavailable (smoke tests, offline reproduction).
        try:
            import requests  # type: ignore
        except Exception as exc:
            raise ImageProviderError(
                f"`requests` package is required for ApxImage2Provider: {exc}"
            ) from exc

        chosen_size = size or self.default_size
        chosen_quality = quality or self.default_quality

        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": chosen_size,
            "quality": chosen_quality,
        }

        # Network-layer failures (timeout, connection reset, DNS) are
        # almost always recoverable on a retry — surface them as
        # `TransientImageProviderError` so the pipeline knows to try
        # again. Anything else (the request reached the gateway but the
        # response shape was wrong) stays a plain `ImageProviderError`.
        try:
            resp = requests.post(
                f"{self.base_url}/images/generations",
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise TransientImageProviderError(
                f"image2 request timed out after {self.timeout}s: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        except requests.ConnectionError as exc:
            raise TransientImageProviderError(
                f"image2 connection error: {type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:
            # Unknown low-level failure — treat as transient by default
            # so we get a retry; if it's truly permanent, the second/third
            # attempt will surface the same shape and we'll bail out then.
            raise TransientImageProviderError(
                f"image2 request failed: {type(exc).__name__}: {exc}"
            ) from exc

        if resp.status_code != 200:
            # Trim error body to 400 chars in case the gateway echoes the prompt back.
            body_preview = (resp.text or "")[:400]
            status = resp.status_code
            # 5xx and 429 are "the server is having a moment" — retry.
            if status >= 500 or status == 429:
                raise TransientImageProviderError(
                    f"image2 HTTP {status} (transient): {body_preview}"
                )
            # v0.6.5.2 — Azure / OpenAI content moderation often returns
            # HTTP 400 with `moderation_blocked` / `safety_violations` /
            # `content_policy_violation` / `content_filter` / `image_generation_user_error`.
            # These are NOT deterministic: the same prompt can pass on a
            # second attempt, especially after the pipeline rewrites the
            # prompt with safer wording. Treat them as transient so the
            # retry layer + safe-rewrite layer get a chance to recover.
            preview_lower = body_preview.lower()
            moderation_markers = (
                "moderation_blocked",
                "safety_violations",
                "safety_violation",
                "content_policy_violation",
                "content_filter",
                "image_generation_user_error",
                "rejected by the safety system",
            )
            if status == 400 and any(m in preview_lower for m in moderation_markers):
                raise TransientImageProviderError(
                    f"image2 HTTP {status} (moderation): {body_preview}"
                )
            # All other 4xx (real auth/quota/bad request) are permanent.
            raise ImageProviderError(
                f"image2 HTTP {status}: {body_preview}"
            )

        try:
            body = resp.json()
        except Exception as exc:
            raise ImageProviderError(
                f"image2 response was not JSON: {type(exc).__name__}: {exc}"
            ) from exc

        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise ImageProviderError(
                "image2 response missing data[] field"
            )
        first = data[0] or {}
        b64 = first.get("b64_json")
        if not b64:
            url = first.get("url")
            if url:
                # The gateway *should* return b64_json (we tested), but if a
                # future tier returns a signed URL instead, surface this
                # explicitly so we can wire a downloader without guessing.
                raise ImageProviderError(
                    "image2 returned data[0].url instead of data[0].b64_json — "
                    "downloader not implemented (v0.6.4 expects base64)."
                )
            raise ImageProviderError(
                "image2 response missing b64_json (and no url either)."
            )

        try:
            png_bytes = base64.b64decode(b64, validate=False)
        except Exception as exc:
            raise ImageProviderError(
                f"image2 base64 decode failed: {type(exc).__name__}: {exc}"
            ) from exc

        # The gateway already returned the chosen size, but we don't trust
        # that field (some tiers truncate). Probe the PNG header instead so
        # the pipeline can resize correctly.
        width, height = _probe_png_dimensions(png_bytes)

        return RenderedImage(
            png_bytes=png_bytes,
            width=width,
            height=height,
            provider_name=self.name,
            debug=self._safe_debug(
                http_status=resp.status_code,
                response_size=body.get("size"),
                response_quality=body.get("quality"),
                response_output_format=body.get("output_format"),
                response_bytes=len(png_bytes),
            ),
        )


def _probe_png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Read width/height from a PNG header without spinning up Pillow.

    Returns ``(0, 0)`` if the bytes don't look like a PNG. A real PNG
    starts with the 8-byte signature, then an IHDR chunk; width/height
    are the first two big-endian 4-byte integers in IHDR's data field.
    """
    if len(png_bytes) < 24:
        return 0, 0
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    try:
        width = int.from_bytes(png_bytes[16:20], "big")
        height = int.from_bytes(png_bytes[20:24], "big")
        return width, height
    except Exception:
        return 0, 0
