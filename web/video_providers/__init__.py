"""
Video provider abstraction layer.

v0.5.3 introduced the Mock provider. v0.6.0 adds ``ApxSeedanceProvider``,
the first provider permitted to make real outbound network calls (gated
behind ``APX_VIDEO_*`` env vars; falls back to Mock when not configured).
"""

from .base import VideoProvider
from .mock_provider import MockVideoProvider
from .apx_seedance_provider import ApxSeedanceProvider

__all__ = [
    "VideoProvider",
    "MockVideoProvider",
    "ApxSeedanceProvider",
]
