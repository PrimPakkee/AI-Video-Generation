"""
MockVideoProvider (v0.5.3).

Returns a `provider_not_configured` shell for every operation. Performs no
network call, holds no API key, and never writes a video file. The mock job
ID is generated from a UUID so each Video Mode generation has a stable
provider_job_id that the UI can display.
"""

import uuid
from typing import Any, Dict

from .base import VideoProvider


_NOT_CONNECTED_MESSAGE = (
    "Real video provider is not connected in v0.5.4. Content assets were "
    "generated successfully, but no real video API was called."
)


class MockVideoProvider(VideoProvider):
    provider_name = "mock"

    def submit(self, request: Dict[str, Any]) -> Dict[str, Any]:
        provider_job_id = f"mock_{uuid.uuid4().hex[:16]}"
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "provider_not_configured",
            "stage": "provider_not_connected",
            "progress": 85,
            "message": _NOT_CONNECTED_MESSAGE,
            "video_url": None,
            "video_path": None,
        }

    def get_status(self, provider_job_id: str) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "provider_not_configured",
            "stage": "provider_not_connected",
            "progress": 85,
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
