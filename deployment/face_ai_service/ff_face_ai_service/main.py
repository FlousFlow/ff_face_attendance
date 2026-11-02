"""Private API for the optional, supervised free face-attendance pilot."""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from starlette.types import ASGIApp, Receive, Scope, Send

try:
    from .free_pilot import FreeFacePilot, PilotError
except ImportError:  # Test loader imports this file directly.
    import importlib.util
    from pathlib import Path
    _pilot_spec = importlib.util.spec_from_file_location("ff_face_ai_free_pilot", Path(__file__).with_name("free_pilot.py"))
    _pilot_module = importlib.util.module_from_spec(_pilot_spec)
    _pilot_spec.loader.exec_module(_pilot_module)
    FreeFacePilot, PilotError = _pilot_module.FreeFacePilot, _pilot_module.PilotError

MAX_CAPTURE_BYTES = int(os.getenv("FF_MAX_CAPTURE_BYTES", "2000000"))
MAX_BODY_BYTES = ((((MAX_CAPTURE_BYTES + 2) // 3) * 4) * 6) + 16384
MAX_ENROLLMENT_BODY_BYTES = 16_000_000
ODOO_SHARED_SECRET = os.getenv("FF_ODOO_SHARED_SECRET", "")
RESULT_HMAC_SECRET = os.getenv("FF_RESULT_HMAC_SECRET", "")
PILOT_ENABLED = os.getenv("FF_PILOT_ENABLED", "false").lower() == "true"
PILOT_ADMIN_TOKEN = os.getenv("FF_PILOT_ADMIN_TOKEN", "")
PILOT_GALLERY_DIR = os.getenv("FF_PILOT_GALLERY_DIR", "/var/lib/ff-face-ai/pilot-gallery")
PILOT_GALLERY_KEYS = os.getenv("FF_PILOT_GALLERY_KEYS", "")
PILOT_DETECTOR_PATH = os.getenv("FF_PILOT_DETECTOR_PATH", "")
PILOT_THRESHOLD = float(os.getenv("FF_PILOT_THRESHOLD", "70"))
NONCE_DB_PATH = os.getenv("FF_NONCE_DB_PATH", "/var/lib/ff-face-ai/nonces.sqlite3")
SETUP_PAIR_CODE_FILE = Path(os.getenv("FF_SETUP_PAIR_CODE_FILE", "/var/lib/ff-face-ai/setup-code"))
SETUP_PAIRED_PATH = Path(os.getenv("FF_SETUP_PAIRED_PATH", "/var/lib/ff-face-ai/setup-paired"))
NONCE_TTL_SECONDS = 60
_pilot = None
_pilot_error = None
_logger = logging.getLogger("ff_face_ai_service")


class VerifyRequest(BaseModel):
    capture: str = Field(min_length=4)
    nonce: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    device_ref: str = Field(min_length=1, max_length=64)
    company_ref: str = Field(min_length=1, max_length=64)
    frames: list[str] | None = Field(default=None, min_length=3, max_length=5)
    challenge: str | None = Field(default=None, pattern=r"^(turn_left|turn_right)$")


class LandmarksRequest(BaseModel):
    capture: str = Field(min_length=4, max_length=2_700_000)
    nonce: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    device_ref: str = Field(min_length=1, max_length=64)
    company_ref: str = Field(min_length=1, max_length=64)


class PilotEnrollmentRequest(BaseModel):
    template_ref: str = Field(min_length=16, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    samples: list[str] = Field(min_length=3, max_length=10)

    @field_validator("samples")
    @classmethod
    def validate_sample_sizes(cls, samples):
        if any(len(sample) > 2_700_000 for sample in samples) or sum(map(len, samples)) > MAX_ENROLLMENT_BODY_BYTES:
            raise ValueError("enrollment_samples_too_large")
        return samples


class PilotRevokeRequest(BaseModel):
    template_ref: str = Field(min_length=16, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


class SetupPairRequest(BaseModel):
    pairing_code: str = Field(min_length=24, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _local_setup_code(request: Request, supplied_code: str) -> bool:
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        return False
    try:
        expected = SETUP_PAIR_CODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(expected) and hmac.compare_digest(expected, supplied_code)


def readiness():
    """The free pilot is opt-in and explicitly not production-grade."""
    if not PILOT_ENABLED:
        return False, "no_approved_recognition_and_pad_models"
    if pilot() is None:
        return False, _pilot_error or "free_pilot_unavailable"
    return True, "free_pilot_enabled"


def pilot():
    global _pilot, _pilot_error
    if not PILOT_ENABLED:
        return None
    if _pilot is None and _pilot_error is None:
        try:
            if not PILOT_DETECTOR_PATH:
                raise PilotError("FF_PILOT_DETECTOR_PATH_required")
            _pilot = FreeFacePilot(PILOT_GALLERY_DIR, PILOT_DETECTOR_PATH, PILOT_GALLERY_KEYS, PILOT_THRESHOLD)
        except (PilotError, OSError, ValueError) as exc:
            _pilot_error = str(exc)
    return _pilot


def request_signature(timestamp: str, nonce: str, device_ref: str, company_ref: str, capture: str) -> str:
    body_hash = hashlib.sha256(capture.encode("ascii")).hexdigest()
    message = "\n".join((timestamp, nonce, device_ref, company_ref, body_hash)).encode()
    return hmac.new(ODOO_SHARED_SECRET.encode(), message, hashlib.sha256).hexdigest()


def signed_capture_for_payload(payload: VerifyRequest) -> str:
    return "\n".join(payload.frames) if payload.frames else payload.capture


def _claim_nonce(device_ref: str, company_ref: str, nonce: str, now: float | None = None) -> bool:
    """Atomically claim a signed request nonce across workers sharing this host."""
    timestamp = time.time() if now is None else now
    path = Path(NONCE_DB_PATH)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5, isolation_level=None) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS consumed_nonce (
                device_ref TEXT NOT NULL,
                company_ref TEXT NOT NULL,
                nonce TEXT NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (device_ref, company_ref, nonce)
            )
        """)
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM consumed_nonce WHERE expires_at <= ?", (timestamp,))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO consumed_nonce (device_ref, company_ref, nonce, expires_at) VALUES (?, ?, ?, ?)",
                (device_ref, company_ref, nonce, timestamp + NONCE_TTL_SECONDS),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        path.chmod(0o600)
        return cursor.rowcount == 1


def result_signature(result: dict) -> str:
    message = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(RESULT_HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Flous Flow Face AI Service", version="0.1.3", lifespan=lifespan)


class RequestSizeLimitMiddleware:
    """Bound buffered request memory even when the client omits Content-Length."""

    def __init__(self, app: ASGIApp, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limits = {
            "/v1/verify": MAX_BODY_BYTES,
            "/v1/landmarks": ((MAX_CAPTURE_BYTES + 2) // 3) * 4 + 8192,
            "/v1/pilot/enroll": MAX_ENROLLMENT_BODY_BYTES,
            "/v1/pilot/revoke": 4096,
            "/v1/setup/pair": 4096,
            "/v1/setup/complete": 4096,
        }
        limit = limits.get(scope.get("path"))
        if not limit:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > limit:
                response = _error(413, "request_too_large")
                await response(scope, receive, send)
                return
            if not event.get("more_body", False):
                break
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=MAX_BODY_BYTES)


def _error(status, code):
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": code}, status_code=status)


@app.get("/health/live")
def live():
    return {"status": "live"}


@app.post("/v1/setup/pair")
def setup_pair(payload: SetupPairRequest, request: Request):
    """Exchange a local one-time code for Odoo/service credentials."""
    if SETUP_PAIRED_PATH.exists():
        raise HTTPException(status_code=409, detail="service_already_paired")
    if not _local_setup_code(request, payload.pairing_code):
        raise HTTPException(status_code=403, detail="invalid_local_setup_code")
    if not ODOO_SHARED_SECRET or not RESULT_HMAC_SECRET or not PILOT_ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="service_secrets_unconfigured")
    return {
        "service_url": "https://127.0.0.1:8787",
        "service_request_secret": ODOO_SHARED_SECRET,
        "service_hmac_secret": RESULT_HMAC_SECRET,
        "pilot_admin_token": PILOT_ADMIN_TOKEN,
    }


@app.post("/v1/setup/complete")
def setup_complete(payload: SetupPairRequest, request: Request):
    """Consume the setup code after Odoo has stored and verified the connection."""
    if not _local_setup_code(request, payload.pairing_code):
        raise HTTPException(status_code=403, detail="invalid_local_setup_code")
    SETUP_PAIRED_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(SETUP_PAIRED_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="service_already_paired") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as marker:
        marker.write("paired\n")
    SETUP_PAIR_CODE_FILE.unlink(missing_ok=True)
    return {"result": "paired"}


@app.get("/health/ready")
def ready():
    ok, reason = readiness()
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "reason": reason})
    return {"status": "ready"}


@app.post("/v1/verify")
def verify(
    payload: VerifyRequest,
    x_ff_timestamp: Annotated[str | None, Header()] = None,
    x_ff_request_signature: Annotated[str | None, Header()] = None,
):
    if not ODOO_SHARED_SECRET or not RESULT_HMAC_SECRET:
        raise HTTPException(status_code=503, detail="service_secrets_unconfigured")
    if not x_ff_timestamp or not x_ff_request_signature:
        raise HTTPException(status_code=401, detail="missing_request_authentication")
    try:
        timestamp = int(x_ff_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid_request_authentication") from exc
    if abs(time.time() - timestamp) > 15:
        raise HTTPException(status_code=401, detail="expired_request_authentication")
    expected = request_signature(str(timestamp), payload.nonce, payload.device_ref, payload.company_ref, signed_capture_for_payload(payload))
    if not hmac.compare_digest(expected, x_ff_request_signature):
        raise HTTPException(status_code=401, detail="invalid_request_authentication")
    try:
        if not _claim_nonce(payload.device_ref, payload.company_ref, payload.nonce):
            raise HTTPException(status_code=409, detail="replayed_request")
    except (sqlite3.Error, OSError) as exc:
        _logger.exception("request_nonce_store_unavailable")
        raise HTTPException(status_code=503, detail="nonce_store_unavailable") from exc
    import base64
    try:
        capture = base64.b64decode(payload.capture, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid_capture_encoding") from exc
    if not capture or len(capture) > MAX_CAPTURE_BYTES:
        raise HTTPException(status_code=413, detail="capture_too_large")
    ok, reason = readiness()
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "reason": reason})
    if not payload.frames or not payload.challenge:
        raise HTTPException(status_code=400, detail="pilot_frames_and_challenge_required")
    try:
        result = pilot().verify(payload.frames, payload.challenge)
    except PilotError as exc:
        _logger.warning(
            "pilot_verify_rejected device=%s company=%s frames=%s challenge=%s reason=%s",
            payload.device_ref, payload.company_ref, len(payload.frames), payload.challenge, str(exc),
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _logger.info(
        "pilot_verify_passed device=%s company=%s frames=%s challenge=%s template=%s",
        payload.device_ref, payload.company_ref, len(payload.frames), payload.challenge, result["template_ref"],
    )
    response = {
        "nonce": payload.nonce,
        "template_ref": result["template_ref"],
        "passed": True,
        "event_id": uuid.uuid4().hex,
        "model_version": result["model_version"],
        "issued_at": int(time.time()),
    }
    response["signature"] = result_signature(response)
    return response


@app.post("/v1/landmarks")
def face_landmarks(
    payload: LandmarksRequest,
    x_ff_timestamp: Annotated[str | None, Header()] = None,
    x_ff_request_signature: Annotated[str | None, Header()] = None,
):
    if not ODOO_SHARED_SECRET or not RESULT_HMAC_SECRET:
        raise HTTPException(status_code=503, detail="service_secrets_unconfigured")
    if not x_ff_timestamp or not x_ff_request_signature:
        raise HTTPException(status_code=401, detail="missing_request_authentication")
    try:
        timestamp = int(x_ff_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid_request_authentication") from exc
    if abs(time.time() - timestamp) > 15:
        raise HTTPException(status_code=401, detail="expired_request_authentication")
    expected = request_signature(str(timestamp), payload.nonce, payload.device_ref, payload.company_ref, payload.capture)
    if not hmac.compare_digest(expected, x_ff_request_signature):
        raise HTTPException(status_code=401, detail="invalid_request_authentication")
    try:
        if not _claim_nonce(payload.device_ref, payload.company_ref, payload.nonce):
            raise HTTPException(status_code=409, detail="replayed_request")
    except (sqlite3.Error, OSError) as exc:
        _logger.exception("landmark_nonce_store_unavailable")
        raise HTTPException(status_code=503, detail="nonce_store_unavailable") from exc
    import base64
    try:
        raw = base64.b64decode(payload.capture, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid_capture_encoding") from exc
    if not raw or len(raw) > MAX_CAPTURE_BYTES:
        raise HTTPException(status_code=413, detail="capture_too_large")
    ok, reason = readiness()
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "reason": reason})
    try:
        result = pilot().landmarks(payload.capture)
    except PilotError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = {"nonce": payload.nonce, **result, "issued_at": int(time.time())}
    response["signature"] = hmac.new(
        RESULT_HMAC_SECRET.encode(),
        json.dumps(response, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    return response


@app.post("/v1/pilot/enroll")
def pilot_enroll(payload: PilotEnrollmentRequest, x_ff_admin_token: Annotated[str | None, Header()] = None):
    if not PILOT_ENABLED:
        raise HTTPException(status_code=503, detail="free_pilot_disabled")
    if not PILOT_ADMIN_TOKEN or not hmac.compare_digest(PILOT_ADMIN_TOKEN, x_ff_admin_token or ""):
        raise HTTPException(status_code=401, detail="invalid_pilot_admin_token")
    if not pilot():
        raise HTTPException(status_code=503, detail={"status": "not_ready", "reason": _pilot_error or "free_pilot_unavailable"})
    try:
        return pilot().enroll(payload.template_ref, payload.samples)
    except PilotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/pilot/revoke")
def pilot_revoke(payload: PilotRevokeRequest, x_ff_admin_token: Annotated[str | None, Header()] = None):
    if not PILOT_ENABLED:
        raise HTTPException(status_code=503, detail="free_pilot_disabled")
    if not PILOT_ADMIN_TOKEN or not hmac.compare_digest(PILOT_ADMIN_TOKEN, x_ff_admin_token or ""):
        raise HTTPException(status_code=401, detail="invalid_pilot_admin_token")
    if not pilot():
        raise HTTPException(status_code=503, detail={"status": "not_ready", "reason": _pilot_error or "free_pilot_unavailable"})
    try:
        return pilot().revoke(payload.template_ref)
    except PilotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
