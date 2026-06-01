"""
Video provider abstraction layer (v0.5.3).

This package isolates the contract for "render a video" from any specific
backend. v0.5.3 only ships a Mock provider that performs no network call,
holds no API key, and never produces a real video file. Real providers
(e.g. Seedance) will be introduced behind the same VideoProvider interface
in a later version.
"""

from .base import VideoProvider
from .mock_provider import MockVideoProvider

__all__ = [
    "VideoProvider",
    "MockVideoProvider",
]
