"""
Video Mode dry-run MockVideoProvider.

Returns a ``provider_not_configured`` shell for every operation. Performs no
network call, holds no API key, and never writes a video file. The mock job
ID is generated from a UUID so each Video Mode generation has a stable
``provider_job_id`` that the UI can display.

Under v0.5.5 the mock job advances to ``stage="contract_ready"`` /
``progress=90`` to reflect that the Seedance contract adapter has produced
its dry-run payload preview, but **no real provider is invoked, no real
video API is called, and no real mp4 is generated**. Real submit / poll /
download is reserved for v0.6.0.
"""

import uuid
from typing import Any, Dict

from .base import VideoProvider


_NOT_CONNECTED_MESSAGE = (
    "Seedance prompt compiler + contract adapter are ready. Content assets, "
    "compiled Seedance prompt, and payload preview were generated, but no real "
    "video API was called. Real Seedance provider calls are reserved for v0.6.0."
)


class MockVideoProvider(VideoProvider):
    provider_name = "mock"

    def submit(self, request: Dict[str, Any]) -> Dict[str, Any]:
        provider_job_id = f"mock_{uuid.uuid4().hex[:16]}"
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "provider_not_configured",
            "stage": "contract_ready",
            "progress": 90,
            "message": _NOT_CONNECTED_MESSAGE,
            "video_url": None,
            "video_path": None,
        }

    def get_status(self, provider_job_id: str) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "provider_not_configured",
            "stage": "contract_ready",
            "progress": 90,
            "message": _NOT_CONNECTED_MESSAGE,
            "video_url": None,
            "video_path": None,
        }

    def cancel(self, provider_job_id: str) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "cancelled",
            "stage": "failed",
            "progress": 0,
            "message": "Mock job cancelled. No real provider was running.",
            "video_url": None,
            "video_path": None,
        }
