"""
Abstract base class for video providers (v0.5.3).

A `VideoProvider` is responsible for translating a Video Mode generation
request into provider-specific actions (submit / poll / cancel) and
returning a normalized payload that the application layer can persist on
a VideoJob row. v0.5.3 only ships MockVideoProvider; real providers must
not be added in this version.
"""

from typing import Any, Dict, Optional


class VideoProvider:
    """Abstract video provider interface.

    Subclasses MUST set ``provider_name`` to a stable lowercase identifier
    (e.g. ``'mock'``, future ``'seedance'``) and implement ``submit``,
    ``get_status``, and ``cancel``.

    All methods return a normalized dict with at least the following keys:
        provider, provider_job_id, status, stage, progress, message,
        video_url, video_path
    """

    provider_name: str = "base"

    def submit(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a new video render job. Must not raise on transient
        provider errors — surface them via the returned dict's status /
        message fields instead."""
        raise NotImplementedError("VideoProvider.submit must be implemented by subclasses")

    def get_status(self, provider_job_id: str) -> Dict[str, Any]:
        """Look up the latest provider-side state for a previously
        submitted job."""
        raise NotImplementedError("VideoProvider.get_status must be implemented by subclasses")

    def cancel(self, provider_job_id: str) -> Dict[str, Any]:
        """Best-effort cancel a running job. Returns the latest known
        normalized payload."""
        raise NotImplementedError("VideoProvider.cancel must be implemented by subclasses")

    @staticmethod
    def empty_response(provider: str, message: Optional[str] = None) -> Dict[str, Any]:
        """Helper for subclasses to build a minimal not-configured shell."""
        return {
            "provider": provider,
            "provider_job_id": None,
            "status": "provider_not_configured",
            "stage": "provider_not_connected",
            "progress": 0,
            "message": message or "Provider is not connected.",
            "video_url": None,
            "video_path": None,
        }
