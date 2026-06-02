"""
SeedanceContractAdapter (v0.5.5 / v0.5.6).

Dry-run contract adapter that prepares the future Seedance provider payload
without performing any network call. v0.5.5/v0.5.6 do NOT call any real
Seedance endpoint, do NOT generate any mp4, and do NOT download any video
file. Real submit / poll / download is reserved for v0.6.0.

v0.5.6 extends ``build_seedance_payload_preview`` so it can consume a
compiled Seedance prompt + negative prompt produced by
``SeedancePromptCompiler``. The payload's ``prompt`` and
``negative_prompt`` fields prefer the compiled values; if the compiler
output is missing, the adapter falls back to the upstream
``provider_request_preview`` and emits a warning. The adapter still does
not import the prompt-mode template and still does not access the network.

This module is deliberately not named ``seedance_provider.py`` — it is a
contract validator + payload preview builder, not a real provider.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CONTRACT_VALIDATION_SCHEMA_VERSION = "seedance_contract_validation_v0.5.5"
PAYLOAD_PREVIEW_SCHEMA_VERSION = "seedance_payload_preview_v0.5.6"
PAYLOAD_PREVIEW_LEGACY_SCHEMA_VERSION = "seedance_payload_preview_v0.5.5"
LIFECYCLE_PREVIEW_SCHEMA_VERSION = "provider_lifecycle_preview_v0.5.5"
PROVIDER_CONTRACT_SCHEMA_VERSION = "seedance_contract_v0.5.5"

DEFAULT_DURATION_SECONDS = 60
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_RESOLUTION = "1080p"
DEFAULT_FPS = 24
DEFAULT_LANGUAGE = "zh-CN"
DEFAULT_STYLE = "clean whiteboard line-art educational short video"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scan_for_unsafe_strings(payload: Dict[str, Any]) -> Dict[str, bool]:
    """Serialise the dict and look for any obvious leakage indicators."""
    try:
        blob = json.dumps(payload, ensure_ascii=False, default=str).lower()
    except Exception:
        blob = ""
    return {
        "contains_api_key": ("api_key" in blob) or ("api-key" in blob),
        "contains_authorization": "authorization" in blob,
        "contains_http_endpoint": ("http://" in blob) or ("https://" in blob),
        "contains_real_video_url": (
            ".mp4" in blob or ".mov" in blob or ".m3u8" in blob
        ),
    }


class SeedanceContractAdapter:
    """v0.5.5 dry-run contract adapter for the future Seedance provider.

    network_enabled is hard-coded False. No method in this class makes a
    real HTTP request. No method writes a real video file or returns a
    real video URL.
    """

    provider_name = "mock"
    future_provider = "seedance"
    network_enabled = False

    def validate_provider_request_preview(self, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(payload, dict):
            errors.append("provider_request_preview is missing or not a JSON object.")
            return {
                "schema_version": CONTRACT_VALIDATION_SCHEMA_VERSION,
                "valid": False,
                "future_provider": self.future_provider,
                "provider": self.provider_name,
                "checked_at": _utc_now_iso(),
                "errors": errors,
                "warnings": warnings,
                "required_fields": {},
                "safety_checks": {
                    "contains_api_key": False,
                    "contains_authorization": False,
                    "contains_http_endpoint": False,
                    "contains_real_video_url": False,
                },
                "network_call_performed": False,
                "real_video_generated": False,
            }

        provider = str(payload.get("provider") or "").strip().lower()
        future_provider = str(payload.get("future_provider") or "").strip().lower()

        if provider != "mock":
            errors.append(f"provider must be 'mock' in v0.5.5, got '{payload.get('provider')!r}'.")
        if future_provider != "seedance":
            errors.append(
                f"future_provider must be 'seedance', got '{payload.get('future_provider')!r}'."
            )

        prompt = payload.get("prompt")
        if not (isinstance(prompt, str) and prompt.strip()):
            errors.append("prompt is required and must be a non-empty string.")

        required_fields = {
            "prompt": isinstance(payload.get("prompt"), str) and bool(str(payload.get("prompt")).strip()),
            "duration_seconds": isinstance(payload.get("duration_seconds"), (int, float)),
            "aspect_ratio": isinstance(payload.get("aspect_ratio"), str)
            and bool(str(payload.get("aspect_ratio")).strip()),
            "resolution": isinstance(payload.get("resolution"), str)
            and bool(str(payload.get("resolution")).strip()),
            "fps": isinstance(payload.get("fps"), (int, float)),
            "language": isinstance(payload.get("language"), str)
            and bool(str(payload.get("language")).strip()),
            "style": isinstance(payload.get("style"), str)
            and bool(str(payload.get("style")).strip()),
            "submit_mode": isinstance(payload.get("submit_mode"), str)
            and bool(str(payload.get("submit_mode")).strip()),
        }

        for key, ok in required_fields.items():
            if not ok and key not in ("prompt",):  # prompt already error-reported above
                warnings.append(f"required field '{key}' missing or invalid; using default for preview.")

        submit_mode = str(payload.get("submit_mode") or "").strip().lower()
        if submit_mode != "not_connected":
            errors.append(
                f"submit_mode must be 'not_connected' in v0.5.5, got '{payload.get('submit_mode')!r}'."
            )

        real_video_generated = bool(payload.get("real_video_generated"))
        if real_video_generated:
            errors.append("real_video_generated must be false in v0.5.5.")

        safety_checks = _scan_for_unsafe_strings(payload)
        if safety_checks["contains_api_key"]:
            errors.append("provider_request_preview must not include 'api_key'.")
        if safety_checks["contains_authorization"]:
            errors.append("provider_request_preview must not include 'authorization'.")
        if safety_checks["contains_http_endpoint"]:
            errors.append("provider_request_preview must not include real http(s) endpoints.")
        if safety_checks["contains_real_video_url"]:
            errors.append("provider_request_preview must not include real video URLs.")

        valid = not errors
        return {
            "schema_version": CONTRACT_VALIDATION_SCHEMA_VERSION,
            "valid": valid,
            "future_provider": self.future_provider,
            "provider": self.provider_name,
            "checked_at": _utc_now_iso(),
            "errors": errors,
            "warnings": warnings,
            "required_fields": required_fields,
            "safety_checks": safety_checks,
            "network_call_performed": False,
            "real_video_generated": False,
        }

    def build_seedance_payload_preview(
        self,
        payload: Optional[Dict[str, Any]],
        compiled_prompt: Optional[str] = None,
        compiled_negative_prompt: Optional[str] = None,
        prompt_compiler_version: Optional[str] = None,
        prompt_source: Optional[str] = None,
        negative_prompt_source: Optional[str] = None,
        compiler_ready: Optional[bool] = None,
    ) -> Dict[str, Any]:
        src = payload if isinstance(payload, dict) else {}

        upstream_prompt = src.get("prompt") if isinstance(src.get("prompt"), str) else ""
        upstream_negative = (
            src.get("negative_prompt") if isinstance(src.get("negative_prompt"), str) else ""
        )

        warnings: List[str] = []

        if isinstance(compiled_prompt, str) and compiled_prompt.strip():
            prompt = compiled_prompt
            resolved_prompt_source = prompt_source or "video_assets/seedance_prompt.txt"
            prompt_from_compiler = True
        else:
            prompt = upstream_prompt
            resolved_prompt_source = prompt_source or "video_assets/provider_prompt.txt"
            prompt_from_compiler = False
            if compiler_ready is False or compiled_prompt is not None:
                warnings.append(
                    "Compiled Seedance prompt was empty; payload fell back to provider_prompt."
                )

        if isinstance(compiled_negative_prompt, str) and compiled_negative_prompt.strip():
            negative_prompt = compiled_negative_prompt
            resolved_neg_source = (
                negative_prompt_source or "video_assets/seedance_negative_prompt.txt"
            )
            negative_from_compiler = True
        else:
            negative_prompt = upstream_negative
            resolved_neg_source = (
                negative_prompt_source
                or "video_assets/provider_request_preview.json#negative_prompt"
            )
            negative_from_compiler = False

        duration = src.get("duration_seconds") if isinstance(
            src.get("duration_seconds"), (int, float)
        ) else DEFAULT_DURATION_SECONDS
        aspect_ratio = src.get("aspect_ratio") if isinstance(
            src.get("aspect_ratio"), str
        ) and src.get("aspect_ratio") else DEFAULT_ASPECT_RATIO
        resolution = src.get("resolution") if isinstance(
            src.get("resolution"), str
        ) and src.get("resolution") else DEFAULT_RESOLUTION
        fps = src.get("fps") if isinstance(src.get("fps"), (int, float)) else DEFAULT_FPS
        language = src.get("language") if isinstance(
            src.get("language"), str
        ) and src.get("language") else DEFAULT_LANGUAGE
        style = src.get("style") if isinstance(
            src.get("style"), str
        ) and src.get("style") else DEFAULT_STYLE

        return {
            "schema_version": PAYLOAD_PREVIEW_SCHEMA_VERSION,
            "legacy_schema_version": PAYLOAD_PREVIEW_LEGACY_SCHEMA_VERSION,
            "future_provider": self.future_provider,
            "network_call_performed": False,
            "real_video_generated": False,
            "real_video_downloaded": False,
            "provider_status": "provider_not_configured",
            "submit_mode": "dry_run_contract_only",
            "endpoint": None,
            "prompt_compiler_version": prompt_compiler_version,
            "prompt_source": resolved_prompt_source,
            "negative_prompt_source": resolved_neg_source,
            "prompt_from_compiler": prompt_from_compiler,
            "negative_prompt_from_compiler": negative_from_compiler,
            "auth": {
                "api_key_required_in_v0_6_0": True,
                "api_key_present_in_payload": False,
                "authorization_header_present": False,
            },
            "payload": {
                "model": None,
                "prompt": prompt,
                "duration_seconds": duration,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "fps": fps,
                "language": language,
                "style": style,
                "negative_prompt": negative_prompt,
                "metadata": {
                    "source": "video_assets_v0.5.6",
                    "real_video_generated": False,
                    "prompt_source": resolved_prompt_source,
                    "negative_prompt_source": resolved_neg_source,
                    "prompt_compiler_version": prompt_compiler_version,
                },
            },
            "warnings": warnings,
            "notes": [
                "This is a Seedance payload preview built locally.",
                "No real Seedance endpoint is called.",
                "No API key is included.",
                "Real Seedance provider calls are reserved for v0.6.0.",
                "payload.prompt is sourced from the compiled Seedance prompt when available.",
            ],
        }

    def build_lifecycle_preview(
        self,
        payload: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        contract_ready = bool(validation and validation.get("valid"))
        message = (
            "Seedance contract adapter is ready, but real Seedance provider calls are reserved for v0.6.0."
            if contract_ready
            else "Seedance contract validation failed; real Seedance provider calls remain blocked."
        )
        return {
            "schema_version": LIFECYCLE_PREVIEW_SCHEMA_VERSION,
            "future_provider": self.future_provider,
            "network_call_performed": False,
            "real_video_generated": False,
            "real_video_downloaded": False,
            "contract_ready": contract_ready,
            "canonical_lifecycle": [
                {
                    "step": "prepare_payload",
                    "status": "ready" if contract_ready else "validation_failed",
                    "description": "Provider payload preview has been built locally.",
                },
                {
                    "step": "submit",
                    "status": "blocked_until_v0.6.0",
                    "description": "Real Seedance submit API is reserved for v0.6.0.",
                },
                {
                    "step": "poll",
                    "status": "blocked_until_v0.6.0",
                    "description": "Real Seedance polling is reserved for v0.6.0.",
                },
                {
                    "step": "download",
                    "status": "blocked_until_v0.6.0",
                    "description": "Real video asset download is reserved for v0.6.0.",
                },
            ],
            "canonical_status_mapping": {
                "not_submitted": "provider_not_configured",
                "submitted": "submitted",
                "queued": "pending",
                "processing": "running",
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
            },
            "current_status": "provider_not_configured",
            "message": message,
        }

    def dry_run_submit(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        provider_job_id = f"dry_run_seedance_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        return {
            "dry_run": True,
            "network_call_performed": False,
            "future_provider": self.future_provider,
            "provider_job_id": provider_job_id,
            "status": "provider_not_configured",
            "stage": "contract_ready",
            "progress": 90,
            "message": "Seedance contract is ready. Real submit is disabled until v0.6.0.",
        }

    def dry_run_poll(self, provider_job_id: str) -> Dict[str, Any]:
        return {
            "dry_run": True,
            "network_call_performed": False,
            "provider_job_id": provider_job_id or "",
            "status": "provider_not_configured",
            "stage": "poll_blocked_until_v0.6.0",
            "progress": 90,
            "message": "Real Seedance polling is reserved for v0.6.0.",
        }

    def dry_run_download(self, provider_job_id: str) -> Dict[str, Any]:
        return {
            "dry_run": True,
            "network_call_performed": False,
            "provider_job_id": provider_job_id or "",
            "status": "provider_not_configured",
            "stage": "download_blocked_until_v0.6.0",
            "real_video_downloaded": False,
            "result_video_path": None,
            "result_video_url": None,
            "message": "Real video download is reserved for v0.6.0.",
        }


__all__ = [
    "SeedanceContractAdapter",
    "PROVIDER_CONTRACT_SCHEMA_VERSION",
    "CONTRACT_VALIDATION_SCHEMA_VERSION",
    "PAYLOAD_PREVIEW_SCHEMA_VERSION",
    "PAYLOAD_PREVIEW_LEGACY_SCHEMA_VERSION",
    "LIFECYCLE_PREVIEW_SCHEMA_VERSION",
]
