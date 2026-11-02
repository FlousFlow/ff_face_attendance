import base64
import importlib.util
import pathlib
import time
import pytest
from pydantic import ValidationError

from fastapi.testclient import TestClient

MODULE = pathlib.Path(__file__).parents[1] / "ff_face_ai_service" / "main.py"
spec = importlib.util.spec_from_file_location("face_service", MODULE)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
client = TestClient(service.app)


def test_liveness_and_recognition_not_ready_by_default():
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "no_approved_recognition_and_pad_models"


def test_verification_never_fabricates_success():
    service.ODOO_SHARED_SECRET = ""
    service.RESULT_HMAC_SECRET = ""
    response = client.post("/v1/verify", json={
        "capture": base64.b64encode(b"synthetic test frame").decode(),
        "nonce": "n" * 40,
        "device_ref": "device-1",
        "company_ref": "company-1",
    })
    assert response.status_code == 503


def test_landmark_preview_rejects_unauthenticated_frames():
    service.ODOO_SHARED_SECRET = "request-test-secret"
    service.RESULT_HMAC_SECRET = "result-test-secret"
    response = client.post("/v1/landmarks", json={
        "capture": base64.b64encode(b"synthetic test frame").decode(),
        "nonce": "landmark-nonce-" + "x" * 30,
        "device_ref": "device-1",
        "company_ref": "company-1",
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "missing_request_authentication"


def test_health_liveness_is_independent_of_model_readiness():
    assert client.get("/health/live").json() == {"status": "live"}


def test_signed_request_nonce_cannot_be_replayed(tmp_path):
    service.ODOO_SHARED_SECRET = "request-test-secret"
    service.RESULT_HMAC_SECRET = "result-test-secret"
    service.NONCE_DB_PATH = str(tmp_path / "shared-nonces.sqlite3")
    payload = {
        "capture": base64.b64encode(b"synthetic image bytes").decode(),
        "nonce": "unique-nonce-" + "x" * 30,
        "device_ref": "device-1",
        "company_ref": "company-1",
    }
    timestamp = str(int(time.time()))
    signature = service.request_signature(timestamp, payload["nonce"], payload["device_ref"], payload["company_ref"], payload["capture"])
    headers = {"X-FF-Timestamp": timestamp, "X-FF-Request-Signature": signature}
    first = client.post("/v1/verify", json=payload, headers=headers)
    replay = client.post("/v1/verify", json=payload, headers=headers)
    assert first.status_code == 503
    assert replay.status_code == 409


def test_nonce_claim_is_shared_across_service_instances(tmp_path):
    service.NONCE_DB_PATH = str(tmp_path / "shared-nonces.sqlite3")
    claim = ("device-a", "company-a", "single-use-nonce")
    assert service._claim_nonce(*claim) is True
    # A second worker uses the same persistent SQLite file and sees the replay.
    assert service._claim_nonce(*claim) is False


def test_enrollment_template_can_be_revoked_with_admin_token(monkeypatch):
    service.PILOT_ENABLED = True
    service.PILOT_ADMIN_TOKEN = "pilot-admin-secret"

    class FakePilot:
        def revoke(self, template_ref):
            return {"result": "revoked", "deleted": template_ref == "odoo-template-123456"}

    monkeypatch.setattr(service, "pilot", lambda: FakePilot())
    response = client.post(
        "/v1/pilot/revoke",
        json={"template_ref": "odoo-template-123456"},
        headers={"X-FF-Admin-Token": "pilot-admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"result": "revoked", "deleted": True}


def test_oversized_request_is_rejected_before_json_parsing():
    response = client.post("/v1/verify", content=b"x" * (service.MAX_BODY_BYTES + 1))
    assert response.status_code == 413


def test_oversized_enrollment_is_rejected_before_json_parsing():
    response = client.post("/v1/pilot/enroll", content=b"x" * (service.MAX_ENROLLMENT_BODY_BYTES + 1))
    assert response.status_code == 413


def test_frame_sequence_uses_all_frames_in_request_signature():
    payload = service.VerifyRequest(
        capture="first-frame",
        nonce="n" * 40,
        device_ref="device-1",
        company_ref="company-1",
        frames=["first-frame", "second-frame", "third-frame"],
        challenge="turn_left",
    )
    assert service.signed_capture_for_payload(payload) == "first-frame\nsecond-frame\nthird-frame"


def test_verification_caps_prompted_frames_at_five():
    payload = service.VerifyRequest(
        capture="first-frame", nonce="n" * 40, device_ref="device-1", company_ref="company-1",
        frames=["frame-%s" % index for index in range(5)], challenge="turn_left",
    )
    assert len(payload.frames) == 5
    with pytest.raises(ValidationError):
        service.VerifyRequest(
            capture="first-frame", nonce="n" * 40, device_ref="device-1", company_ref="company-1",
            frames=["frame-%s" % index for index in range(6)], challenge="turn_left",
        )
