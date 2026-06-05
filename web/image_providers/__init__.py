"""Image providers (v0.6.4+).

Image_video pipeline pluggable image generation layer. The pipeline
imports providers lazily (inside functions) so the base module loads even
when ``requests`` / network access is unavailable.

Currently shipped:
    - ApxImage2Provider — real ``gpt-image-2`` calls via the company's
      OpenAI-compatible gateway.

Forbidden in this layer:
    - APX video generation (Seedance) — handled by web/video_providers/.
    - TTS — handled by web/audio_providers/ (planned for v0.6.5).
"""

from .base import ImageProvider, ImageProviderError, RenderedImage

__all__ = ["ImageProvider", "ImageProviderError", "RenderedImage"]
