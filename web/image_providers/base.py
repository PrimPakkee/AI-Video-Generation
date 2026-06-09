"""Abstract image provider interface (v0.6.4).

Every concrete provider returns a ``RenderedImage`` (raw PNG bytes plus a
small debug dict) or raises ``ImageProviderError``. The image_video
pipeline consumes the bytes directly — no on-disk hand-off, no second
network round-trip.

The base module deliberately avoids importing ``requests``: provider
modules that need it import it lazily inside their ``generate`` method,
so this package can still load (and the rest of the pipeline can import
``ImageProvider`` for type hints) when ``requests`` is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


class ImageProviderError(Exception):
    """Raised when a provider cannot return a usable image."""


class TransientImageProviderError(ImageProviderError):
    """Raised when the failure is likely temporary (network timeout,
    gateway 5xx, connection reset). The pipeline retries these.

    Permanent failures — bad prompt, 4xx auth/quota errors, malformed
    responses — should raise the plain ``ImageProviderError`` so the
    pipeline does not waste retries on them.
    """


@dataclass
class RenderedImage:
    """Result of a single ``ImageProvider.generate`` call."""

    png_bytes: bytes
    width: int
    height: int
    provider_name: str
    debug: Dict[str, Any] = field(default_factory=dict)


class ImageProvider:
    """Abstract base. Subclasses must implement ``name`` and ``generate``.

    Implementations MUST never raise on transient failures except by
    raising ``ImageProviderError`` — that contract lets the pipeline fall
    back to the local Pillow renderer for a single slide without taking
    down the entire run.
    """

    name: str = "abstract"

    def is_configured(self) -> bool:
        """Override to report whether the provider has the env it needs."""
        return False

    def generate(
        self,
        prompt: str,
        *,
        size: str = "1792x1024",
        quality: str = "high",
    ) -> RenderedImage:
        raise NotImplementedError
