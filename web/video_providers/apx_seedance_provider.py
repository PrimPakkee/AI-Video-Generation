"""
ApxSeedanceProvider (v0.6.0).

Real video provider that talks to the company APX async video gateway, which
itself calls doubao-seedance-2.0 to generate the mp4. This is the **only**
v0.6.0 module that is permitted to make real outbound HTTP requests.

Configuration is read entirely from environment variables (``APX_VIDEO_*``)
loaded from ``.env`` — nothing is hard-coded. The API key is never logged,
never written into request_json / response_json snapshots, never written into
``metadata.json``, and never returned in any API response. ``load_config()``
deliberately surfaces ``api_key_configured`` (a boolean), not the key itself.

End-to-end flow:

    submit(seedance_prompt) → POST /v1/async/chat            (returns id)
    poll(provider_job_id)   → GET  /v1/async/results/{id}    (status 1/2/3/4)
    download_video(url)     → save to outputs/<slug>/video.mp4
    download_cover(url)     → save to outputs/<slug>/video_cover.jpg
    confirm(provider_job_id) → DELETE /v1/async/results/{id} (opt-in)

The provider does **not** touch Prompt Mode. It does not modify .env. It does
not run any Celery / Redis / RQ queue. ``/api/video/generate`` calls
``submit`` and returns immediately; ``/api/video/jobs/{id}/refresh`` calls
``poll`` and (on success) ``download_video`` synchronously.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import requests


PROVIDER_NAME = "apx_seedance"
DEFAULT_BASE_URL = "http://apx-api.tal.com"
DEFAULT_MODEL = "doubao-seedance-2.0"
DEFAULT_DURATION = 5
DEFAULT_PROMPT_EXTEND = True
DEFAULT_POLL_INTERVAL = 5
DEFAULT_TIMEOUT = 600

SUBMIT_PATH = "/v1/async/chat"
RESULTS_PATH = "/v1/async/results"

STATUS_MAP = {
    1: "pending",
    2: "running",
    3: "succeeded",
    4: "failed",
}
STAGE_MAP = {
    1: "pending",
    2: "running",
    3: "video_ready_remote",
    4: "failed",
}
PROGRESS_MAP = {
    1: 25,
    2: 60,
    3: 90,
    4: 100,
}

_FALLBACK_PROMPT_MARKERS = (
    "需要人工核对",
    "Human review required",
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off", ""):
        return False
    return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _scrub_api_key(value: Any) -> Any:
    """Recursively redact anything that looks like an API key / Authorization
    header from a payload before it ever lands in a JSON snapshot.
    """
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for k, v in value.items():
            kl = str(k).lower()
            if kl in ("api-key", "api_key", "apikey", "authorization", "x-api-key"):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = _scrub_api_key(v)
        return clean
    if isinstance(value, list):
        return [_scrub_api_key(v) for v in value]
    return value


class ApxSeedanceProvider:
    """Real-network APX Seedance provider.

    The constructor performs no I/O. Network calls happen only when ``submit``,
    ``poll``, ``download_video``, ``download_cover``, or ``confirm`` are
    invoked. ``is_configured`` returns False when ``APX_VIDEO_ENABLED`` is
    falsey or any required field is missing — callers should fall back to
    ``MockVideoProvider`` in that case.
    """

    provider_name = PROVIDER_NAME
    network_enabled = True

    def __init__(self) -> None:
        self._cfg = self.load_config()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def load_config(self) -> Dict[str, Any]:
        api_key = (os.environ.get("APX_VIDEO_API_KEY") or "").strip()
        return {
            "enabled": _bool_env("APX_VIDEO_ENABLED", False),
            "base_url": (os.environ.get("APX_VIDEO_BASE_URL") or DEFAULT_BASE_URL).strip(),
            "api_key_configured": bool(api_key),
            "model": (os.environ.get("APX_VIDEO_MODEL") or DEFAULT_MODEL).strip(),
            "duration": _int_env("APX_VIDEO_DURATION", DEFAULT_DURATION),
            "prompt_extend": _bool_env("APX_VIDEO_PROMPT_EXTEND", DEFAULT_PROMPT_EXTEND),
            "poll_interval_seconds": _int_env(
                "APX_VIDEO_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL
            ),
            "timeout_seconds": _int_env("APX_VIDEO_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
            "confirm_after_download": _bool_env(
                "APX_VIDEO_CONFIRM_AFTER_DOWNLOAD", False
            ),
            "allow_fallback_submit": _bool_env(
                "APX_VIDEO_ALLOW_FALLBACK_SUBMIT", False
            ),
        }

    def is_configured(self) -> bool:
        cfg = self._cfg
        api_key = (os.environ.get("APX_VIDEO_API_KEY") or "").strip()
        return bool(
            cfg.get("enabled")
            and cfg.get("base_url")
            and cfg.get("model")
            and api_key
        )

    def public_config(self) -> Dict[str, Any]:
        cfg = dict(self._cfg)
        cfg.pop("api_key", None)
        return cfg

    # ------------------------------------------------------------------
    # Headers / payload
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        api_key = (os.environ.get("APX_VIDEO_API_KEY") or "").strip()
        return {
            "api-key": api_key,
            "X-APX-Model": self._cfg.get("model", DEFAULT_MODEL),
            "Content-Type": "application/json; charset=utf-8",
        }

    def build_submit_payload(
        self,
        seedance_prompt: str,
        duration_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        if isinstance(duration_seconds, bool):
            duration_seconds = None
        try:
            resolved = (
                int(duration_seconds)
                if duration_seconds is not None
                else int(self._cfg.get("duration", DEFAULT_DURATION) or DEFAULT_DURATION)
            )
        except Exception:
            resolved = int(self._cfg.get("duration", DEFAULT_DURATION) or DEFAULT_DURATION)
        return {
            "model": self._cfg.get("model", DEFAULT_MODEL),
            "prompt": seedance_prompt or "",
            "duration": resolved,
            "prompt_extend": bool(self._cfg.get("prompt_extend", DEFAULT_PROMPT_EXTEND)),
        }

    # ------------------------------------------------------------------
    # Fallback prompt protection
    # ------------------------------------------------------------------
    def check_fallback_safety(
        self,
        manifest: Optional[Dict[str, Any]],
        prompt_debug: Optional[Dict[str, Any]],
        seedance_prompt: str,
    ) -> Tuple[bool, Optional[str]]:
        """Return (allowed, block_reason). Default-deny: real APX submit is
        only allowed when ALL positive conditions are explicitly met. The
        ``APX_VIDEO_ALLOW_FALLBACK_SUBMIT=true`` override skips every check
        below — that override is intentionally noisy.
        """
        if self._cfg.get("allow_fallback_submit"):
            return True, None

        # 1. Compiled prompt must be a non-empty stripped string.
        if not isinstance(seedance_prompt, str) or not seedance_prompt.strip():
            return False, "Compiled Seedance prompt is empty."

        # 12 / 13. Prompt must not contain human-review placeholders.
        for marker in _FALLBACK_PROMPT_MARKERS:
            if marker in seedance_prompt:
                return False, "Compiled prompt contains human-review placeholder."

        # 3. Manifest must be a non-empty dict.
        if not isinstance(manifest, dict) or not manifest:
            return False, "generation_manifest.json is missing or empty."

        # 4. prompt_debug must be a non-empty dict.
        if not isinstance(prompt_debug, dict) or not prompt_debug:
            return False, "seedance_prompt_debug.json is missing or empty."

        # 5. llm_used must be exactly True.
        if manifest.get("llm_used") is not True:
            return False, "Asset pipeline did not confirm llm_used=true."

        # 6. fallback_used must be exactly False.
        if manifest.get("fallback_used") is not False:
            return False, "Asset pipeline marked fallback_used=true."

        # 7. seedance_prompt_ready must be exactly True.
        if manifest.get("seedance_prompt_ready") is not True:
            return False, "seedance_prompt_ready is not true."

        # 8 / 9 / 10. compiler_checks flags.
        compiler_checks = prompt_debug.get("compiler_checks")
        if not isinstance(compiler_checks, dict):
            return False, "compiler_checks block is missing in prompt debug."
        if compiler_checks.get("uses_notebooklm_template") is not False:
            return False, "compiler_checks.uses_notebooklm_template must be false."
        if compiler_checks.get("single_narrator_required") is not True:
            return False, "compiler_checks.single_narrator_required must be true."
        if compiler_checks.get("no_dialogue_required") is not True:
            return False, "compiler_checks.no_dialogue_required must be true."

        # 11. prompt_metrics.prompt_words > 0.
        prompt_metrics = prompt_debug.get("prompt_metrics")
        if not isinstance(prompt_metrics, dict):
            return False, "Prompt metrics missing or prompt_words <= 0."
        try:
            words = int(prompt_metrics.get("prompt_words", 0))
        except Exception:
            words = 0
        if words <= 0:
            return False, "Prompt metrics missing or prompt_words <= 0."

        # 12. prompt_debug.warnings — block if any warning mentions 'missing'.
        # Empty / non-list warnings are tolerated (no false-positive block).
        warnings_field = prompt_debug.get("warnings")
        if isinstance(warnings_field, list):
            for w in warnings_field:
                try:
                    if isinstance(w, str) and "missing" in w.lower():
                        return False, "Prompt debug warnings indicate missing required content."
                except Exception:
                    continue

        return True, None

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def submit(
        self,
        seedance_prompt: str,
        output_dir: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        duration_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "status": "provider_not_configured",
                "stage": "provider_not_connected",
                "progress": 0,
                "network_call_performed": False,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "message": "APX provider is not configured.",
                "request": None,
                "response": None,
            }

        payload = self.build_submit_payload(seedance_prompt, duration_seconds=duration_seconds)
        url = f"{self._cfg['base_url'].rstrip('/')}{SUBMIT_PATH}"

        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=int(self._cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
            )
        except requests.RequestException as exc:
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "status": "failed",
                "stage": "submit_failed",
                "progress": 0,
                "network_call_performed": True,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "message": f"APX submit transport error: {type(exc).__name__}",
                "request": _scrub_api_key(payload),
                "response": None,
            }

        try:
            body = resp.json()
        except Exception:
            body = {"raw_text_first_200": (resp.text or "")[:200]}

        body_clean = _scrub_api_key(body)

        if resp.status_code >= 400:
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "status": "failed",
                "stage": "submit_failed",
                "progress": 0,
                "network_call_performed": True,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "message": f"APX submit returned HTTP {resp.status_code}.",
                "request": _scrub_api_key(payload),
                "response": body_clean,
                "http_status": resp.status_code,
            }

        provider_job_id = self._extract_id(body)
        if not provider_job_id:
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "status": "failed",
                "stage": "submit_failed",
                "progress": 0,
                "network_call_performed": True,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "message": "APX submit response did not contain a task id.",
                "request": _scrub_api_key(payload),
                "response": body_clean,
                "http_status": resp.status_code,
            }

        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": "submitted",
            "stage": "submitted",
            "progress": 10,
            "network_call_performed": True,
            "real_video_generated": False,
            "real_video_downloaded": False,
            "message": "APX Seedance task submitted.",
            "request": _scrub_api_key(payload),
            "response": body_clean,
            "http_status": resp.status_code,
        }

    @staticmethod
    def _extract_id(body: Any) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        for key in ("id", "task_id"):
            v = body.get(key)
            if v:
                return str(v)
        for outer in ("data", "result"):
            inner = body.get(outer)
            if isinstance(inner, dict):
                for key in ("id", "task_id"):
                    v = inner.get(key)
                    if v:
                        return str(v)
        return None

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------
    def poll(self, provider_job_id: str) -> Dict[str, Any]:
        if not provider_job_id:
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "status": "failed",
                "stage": "poll_failed",
                "progress": 0,
                "network_call_performed": False,
                "real_video_generated": False,
                "message": "Cannot poll: provider_job_id is empty.",
                "response": None,
            }
        if not self.is_configured():
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "status": "provider_not_configured",
                "stage": "provider_not_connected",
                "progress": 0,
                "network_call_performed": False,
                "real_video_generated": False,
                "message": "APX provider is not configured.",
                "response": None,
            }

        url = f"{self._cfg['base_url'].rstrip('/')}{RESULTS_PATH}/{provider_job_id}"
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                timeout=int(self._cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
            )
        except requests.RequestException as exc:
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "status": "failed",
                "stage": "poll_failed",
                "progress": 0,
                "network_call_performed": True,
                "real_video_generated": False,
                "message": f"APX poll transport error: {type(exc).__name__}",
                "response": None,
            }

        try:
            body = resp.json()
        except Exception:
            body = {"raw_text_first_200": (resp.text or "")[:200]}
        body_clean = _scrub_api_key(body)

        if resp.status_code >= 400:
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "status": "failed",
                "stage": "poll_failed",
                "progress": 0,
                "network_call_performed": True,
                "real_video_generated": False,
                "message": f"APX poll returned HTTP {resp.status_code}.",
                "response": body_clean,
                "http_status": resp.status_code,
            }

        raw_status = self._extract_status(body)
        mapped_status = STATUS_MAP.get(raw_status, "running" if raw_status is None else "failed")
        stage = STAGE_MAP.get(raw_status, "running")
        progress = PROGRESS_MAP.get(raw_status, 60)

        result: Dict[str, Any] = {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "status": mapped_status,
            "stage": stage,
            "progress": progress,
            "network_call_performed": True,
            "real_video_generated": raw_status == 3,
            "raw_status": raw_status,
            "response": body_clean,
            "http_status": resp.status_code,
            "message": f"APX status={raw_status} ({mapped_status}).",
        }

        if raw_status == 3:
            video_url = self._extract_video_url(body)
            cover_url = self._extract_video_cover_url(body)
            result["video_url"] = video_url
            result["video_cover_url"] = cover_url
            if not video_url:
                result["status"] = "succeeded_but_no_video_url"
                result["stage"] = "video_url_missing"
                result["message"] = "APX status=3 but response.video_url was not found."
        elif raw_status == 4:
            err = self._extract_error(body) or "APX reported status=4 (failed)."
            result["error_message"] = err
            result["message"] = f"APX failed: {err}"

        return result

    @staticmethod
    def _extract_status(body: Any) -> Optional[int]:
        if not isinstance(body, dict):
            return None
        for path in ("status", "data.status", "result.status"):
            cur: Any = body
            ok = True
            for part in path.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                try:
                    return int(cur)
                except Exception:
                    continue
        return None

    @staticmethod
    def _extract_from_paths(body: Any, paths) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        for path in paths:
            cur: Any = body
            ok = True
            for part in path.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur.strip():
                return cur.strip()
        return None

    @classmethod
    def _extract_video_url(cls, body: Any) -> Optional[str]:
        return cls._extract_from_paths(
            body,
            (
                "response.video_url",
                "data.response.video_url",
                "result.response.video_url",
                "response.data.video_url",
                "video_url",
            ),
        )

    @classmethod
    def _extract_video_cover_url(cls, body: Any) -> Optional[str]:
        return cls._extract_from_paths(
            body,
            (
                "response.video_cover_url",
                "data.response.video_cover_url",
                "result.response.video_cover_url",
                "response.data.video_cover_url",
                "video_cover_url",
            ),
        )

    @staticmethod
    def _extract_error(body: Any) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        for key in ("error", "error_message", "message"):
            v = body.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for outer in ("data", "result"):
            inner = body.get(outer)
            if isinstance(inner, dict):
                for key in ("error", "error_message", "message"):
                    v = inner.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        return None

    # ------------------------------------------------------------------
    # Download video / cover
    # ------------------------------------------------------------------
    def download_video(
        self,
        video_url: str,
        output_dir: str,
        filename: str = "video.mp4",
    ) -> Dict[str, Any]:
        return self._download_to_output(
            url=video_url,
            output_dir=output_dir,
            filename=filename,
            kind="video",
        )

    def download_cover(
        self,
        video_cover_url: Optional[str],
        output_dir: str,
        filename: str = "video_cover.jpg",
    ) -> Dict[str, Any]:
        if not video_cover_url:
            return {
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": "No cover URL provided; skipping cover download.",
                "skipped": True,
            }
        return self._download_to_output(
            url=video_cover_url,
            output_dir=output_dir,
            filename=filename,
            kind="cover",
        )

    def _download_to_output(
        self,
        url: str,
        output_dir: str,
        filename: str,
        kind: str,
    ) -> Dict[str, Any]:
        # Reject anything that isn't a vanilla http(s) URL.
        try:
            parsed = urlsplit(url or "")
        except Exception:
            parsed = None
        if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"Refused to download {kind}: URL is not a valid http(s) URL.",
            }

        # Path traversal protection.
        safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "")
        if not safe_filename or safe_filename.startswith("."):
            safe_filename = "video.mp4" if kind == "video" else "video_cover.jpg"

        try:
            out_dir = Path(output_dir).resolve()
        except Exception:
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"Refused to download {kind}: output_dir invalid.",
            }
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"Refused to download {kind}: cannot create output dir ({type(exc).__name__}).",
            }

        target = (out_dir / safe_filename).resolve()
        try:
            target.relative_to(out_dir)
        except ValueError:
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"Refused to download {kind}: path traversal blocked.",
            }

        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with requests.get(
                url,
                stream=True,
                timeout=int(self._cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
            ) as resp:
                if resp.status_code >= 400:
                    return {
                        "result_video_path": None,
                        "result_thumbnail_path": None,
                        "real_video_downloaded": False,
                        "message": f"{kind} download HTTP {resp.status_code}.",
                    }
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
                tmp.replace(target)
        except requests.RequestException as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"{kind} download transport error: {type(exc).__name__}",
            }
        except Exception as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": f"{kind} download error: {type(exc).__name__}",
            }

        # Post-download integrity: file must exist and be non-empty.
        try:
            exists = target.exists()
            size = target.stat().st_size if exists else 0
        except Exception:
            exists = False
            size = 0
        if not exists or size <= 0:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return {
                "result_video_path": None,
                "result_thumbnail_path": None,
                "real_video_downloaded": False,
                "message": "Downloaded file is empty or missing.",
            }

        if kind == "video":
            return {
                "result_video_path": str(target),
                "real_video_downloaded": True,
                "bytes_written": size,
                "message": "Video downloaded successfully.",
            }
        return {
            "result_thumbnail_path": str(target),
            "real_video_downloaded": True,
            "bytes_written": size,
            "message": "Video cover downloaded successfully.",
        }

    # ------------------------------------------------------------------
    # Confirm (DELETE)
    # ------------------------------------------------------------------
    def confirm(self, provider_job_id: str) -> Dict[str, Any]:
        if not self._cfg.get("confirm_after_download"):
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "network_call_performed": False,
                "confirmed": False,
                "message": "Confirm skipped: APX_VIDEO_CONFIRM_AFTER_DOWNLOAD is false.",
            }
        if not self.is_configured():
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "network_call_performed": False,
                "confirmed": False,
                "message": "Confirm skipped: APX provider is not configured.",
            }
        if not provider_job_id:
            return {
                "provider": self.provider_name,
                "provider_job_id": None,
                "network_call_performed": False,
                "confirmed": False,
                "message": "Confirm skipped: provider_job_id is empty.",
            }

        url = f"{self._cfg['base_url'].rstrip('/')}{RESULTS_PATH}/{provider_job_id}"
        try:
            resp = requests.delete(
                url,
                headers=self._headers(),
                timeout=int(self._cfg.get("timeout_seconds", DEFAULT_TIMEOUT)),
            )
        except requests.RequestException as exc:
            return {
                "provider": self.provider_name,
                "provider_job_id": provider_job_id,
                "network_call_performed": True,
                "confirmed": False,
                "message": f"APX confirm transport error: {type(exc).__name__}",
            }
        return {
            "provider": self.provider_name,
            "provider_job_id": provider_job_id,
            "network_call_performed": True,
            "confirmed": resp.status_code < 400,
            "http_status": resp.status_code,
            "message": "APX confirm DELETE issued.",
        }


__all__ = [
    "ApxSeedanceProvider",
    "PROVIDER_NAME",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_DURATION",
    "SUBMIT_PATH",
    "RESULTS_PATH",
    "STATUS_MAP",
]
