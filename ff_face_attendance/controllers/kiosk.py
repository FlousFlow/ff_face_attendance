import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
import logging
from urllib.parse import urlsplit

import requests
from werkzeug.wrappers import Response

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _json(payload, status=200):
    return Response(json.dumps(payload), status=status, content_type="application/json; charset=utf-8")


def _safe_enrollment_error(response):
    allowed = {
        "exactly_one_face_required", "invalid_image", "invalid_face_crop",
        "enrollment_requires_3_to_10_samples", "yunet_model_missing",
        "pilot_not_enrolled_or_insufficient_frames",
    }
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) and detail in allowed else "pilot_enrollment_rejected"


def _same_origin_request():
    origin = request.httprequest.headers.get("Origin") or request.httprequest.headers.get("Referer")
    if not origin:
        return False
    try:
        return urlsplit(origin).netloc.lower() == request.httprequest.host.lower()
    except ValueError:
        return False


class FaceKioskController(http.Controller):
    """Small public API surface. Identity is resolved only from signed service evidence."""

    def _device(self):
        authorization = request.httprequest.headers.get("Authorization", "")
        raw = authorization[7:].strip() if authorization.startswith("Bearer ") else request.httprequest.cookies.get("ff_face_kiosk", "")
        if not raw or len(raw) > 256:
            return None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        device = request.env["ff.face.device"].sudo().search([
            ("credential_hash", "=", digest), ("active", "=", True), ("revoked_at", "=", False),
        ], limit=1)
        if device and hmac.compare_digest(device.credential_hash or "", digest):
            return device
        return None

    def _enrollment_company(self):
        """Return the kiosk company, or the authenticated HR manager company."""
        device = self._device()
        if device:
            return device.company_id
        if request.env.user.has_group("hr.group_hr_manager"):
            return request.env.company
        return None

    @http.route("/ff_face_attendance/kiosk", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def kiosk_page(self, **kwargs):
        # Keep the old URL as a compatibility alias, but always use the native
        # Odoo Attendance Kiosk so face verification lives inside the standard
        # Odoo kiosk experience rather than a separate frontend page.
        device = self._device()
        company = device.company_id if device else request.env.company
        kiosk_url = company.sudo().attendance_kiosk_url
        if not kiosk_url:
            return request.not_found()
        return request.redirect(kiosk_url)

    @http.route("/ff_face_attendance/enroll", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def enrollment_page(self, **kwargs):
        """Open the dedicated face-enrollment page from the native Odoo kiosk."""
        requested_language = kwargs.get("lang")
        language_aliases = {"ar": "ar_001", "ar_001": "ar_001", "en": "en_US", "en_US": "en_US"}
        language_code = language_aliases.get(requested_language)
        if language_code:
            language_code = request.env["res.lang"]._get_code(language_code)
            if language_code:
                request.update_context(lang=language_code)
        device = self._device()
        company = device.company_id if device else request.env.company
        requested_employee_id = False
        if request.env.user.has_group("hr.group_hr_manager"):
            try:
                candidate_id = int(kwargs.get("employee_id") or 0)
            except (TypeError, ValueError):
                candidate_id = 0
            if candidate_id and request.env["hr.employee"].sudo().search_count([
                ("id", "=", candidate_id), ("company_id", "=", company.id), ("active", "=", True),
            ]):
                requested_employee_id = candidate_id
        response = request.render("ff_face_attendance.public_face_kiosk", {
            "local_demo": self._is_local_demo(),
            "enrollment_only": bool(request.env.user.has_group("hr.group_hr_manager") and not device),
            "requested_employee_id": requested_employee_id,
            "kiosk_language": request.env.lang,
        })
        if language_code:
            response.set_cookie(
                "frontend_lang", language_code, max_age=60 * 60 * 24 * 365,
                path="/", secure=request.httprequest.is_secure, httponly=False, samesite="Lax",
            )
        return response

    @http.route("/ff_face_attendance/device/status", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def kiosk_device_status(self, **kwargs):
        return _json({"paired": bool(self._device())})

    @http.route("/ff_face_attendance/native_kiosk", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def native_attendance_kiosk(self, **kwargs):
        device = self._device()
        if not device and not request.env.user.has_group("hr.group_hr_manager"):
            return _json({"error": "paired_kiosk_or_hr_login_required"}, 403)
        company = (device.company_id if device else request.env.company).sudo()
        target = company.attendance_kiosk_url if "attendance_kiosk_url" in company._fields else False
        if not target:
            return _json({"error": "standard_attendance_kiosk_not_configured"}, 404)
        return request.redirect(target)

    @staticmethod
    def _is_local_demo():
        params = request.env["ir.config_parameter"].sudo()
        return (
            params.get_param("ff_face_attendance.allow_insecure_local_pairing") == "true"
            and request.httprequest.remote_addr in {"127.0.0.1", "::1"}
        )

    @http.route("/ff_face_attendance/device/local_pair", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def pair_local_demo_device(self, **kwargs):
        """Automatically pair the single kiosk in the explicitly enabled loopback demo."""
        if not self._is_local_demo():
            return _json({"error": "local_pilot_only"}, 403)
        devices = request.env["ff.face.device"].sudo().search([
            ("company_id", "=", request.env.company.id),
            ("active", "=", True),
            ("revoked_at", "=", False),
        ], limit=2)
        if len(devices) != 1:
            return _json({"error": "local_kiosk_not_configured"}, 503)
        device = devices[0]
        credential = secrets.token_urlsafe(32)
        device.write({
            "credential_hash": device._hash_credential(credential),
            "credential_hint": credential[-6:],
        })
        response = _json({"result": "device_enrolled"})
        response.set_cookie(
            "ff_face_kiosk", credential,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            secure=False,
            samesite="Strict",
            path="/ff_face_attendance",
        )
        return response

    @http.route("/ff_face_attendance/employee/status", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def employee_status(self, **kwargs):
        device = self._device()
        company = self._enrollment_company()
        if not company:
            return _json({"error": "unauthorized_device"}, 401)
        try:
            data = json.loads(request.httprequest.get_data(cache=False))
            employee_id = data.get("employee_id")
            if not isinstance(employee_id, int):
                return _json({"error": "employee_number_required"}, 400)
            employee = request.env["hr.employee"].sudo().search([
                ("id", "=", employee_id), ("company_id", "=", company.id), ("active", "=", True),
            ], limit=1)
            if not employee:
                return _json({"error": "employee_not_found"}, 404)
            last_attendance = request.env["hr.attendance"].sudo().search(
                [("employee_id", "=", employee.id)], order="check_in desc, id desc", limit=1
            )
            return _json({
                "employee_id": employee.id,
                "employee_name": employee.name,
                "enrolled": employee.ff_face_enrollment_status == "enrolled" and bool(employee.ff_face_template_ref),
                "enrollment_status": employee.ff_face_enrollment_status,
                "checked_in": bool(last_attendance and not last_attendance.check_out),
                "can_enroll": request.env.user.has_group("hr.group_hr_manager"),
                "can_register": (
                    request.env.user.has_group("hr.group_hr_manager")
                    and employee.ff_face_enrollment_status != "revocation_pending"
                ),
            })
        except (ValueError, TypeError):
            return _json({"error": "invalid_request"}, 400)

    @http.route("/ff_face_attendance/employee/search", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def employee_search(self, **kwargs):
        company = self._enrollment_company()
        if not company:
            return _json({"error": "unauthorized_device"}, 401)
        try:
            data = json.loads(request.httprequest.get_data(cache=False))
            query = data.get("query")
            if not isinstance(query, str) or not query.strip():
                return _json({"employees": []})
            term = query.strip()
            employees = request.env["hr.employee"].sudo().search([
                ("company_id", "=", company.id),
                ("active", "=", True),
                "|", "|", "|", "|",
                ("name", "ilike", term),
                ("work_email", "ilike", term),
                ("work_phone", "ilike", term),
                ("barcode", "ilike", term),
                ("user_id.login", "ilike", term),
            ], order="name, id", limit=20)
            return _json({"employees": [{
                "id": employee.id,
                "name": employee.name,
                "department": employee.department_id.name or "",
            } for employee in employees]})
        except (ValueError, TypeError, AttributeError):
            return _json({"error": "invalid_request"}, 400)

    @http.route("/ff_face_attendance/device/enroll", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def enroll_device(self, **kwargs):
        # The one-time manager-provisioned credential is exchanged for a browser-managed
        # cookie; it is never persisted by kiosk JavaScript. Require TLS at the edge.
        params = request.env["ir.config_parameter"].sudo()
        local_dev_pairing = (
            params.get_param("ff_face_attendance.allow_insecure_local_pairing") == "true"
            and request.httprequest.remote_addr in {"127.0.0.1", "::1"}
        )
        if not request.httprequest.is_secure and not local_dev_pairing:
            return _json({"error": "https_required"}, 400)
        device = self._device()
        if not device:
            return _json({"error": "unauthorized_device"}, 401)
        response = _json({"result": "device_enrolled"})
        response.set_cookie(
            "ff_face_kiosk", request.httprequest.headers.get("Authorization", "")[7:].strip(),
            max_age=60 * 60 * 24 * 30, httponly=True, secure=True, samesite="Strict",
            path="/ff_face_attendance",
        )
        return response

    @http.route("/ff_face_attendance/device/logout", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def logout_device(self, **kwargs):
        response = _json({"result": "device_logged_out"})
        response.delete_cookie("ff_face_kiosk", path="/ff_face_attendance", secure=True, httponly=True, samesite="Strict")
        return response

    @http.route("/ff_face_attendance/pilot/enroll", type="http", auth="user", methods=["POST"], csrf=False, sitemap=False)
    def pilot_enroll(self, **kwargs):
        if not _same_origin_request():
            return _json({"error": "same_origin_required"}, 403)
        if not request.env.user.has_group("hr.group_hr_manager"):
            return _json({"error": "hr_manager_required"}, 403)
        try:
            raw_body = request.httprequest.get_data(cache=False)
            if len(raw_body) > 16_000_000:
                return _json({"error": "request_too_large"}, 413)
            data = json.loads(raw_body)
            employee_id = data.get("employee_id")
            samples = data.get("samples")
            consent_acknowledged = data.get("consent_acknowledged") is True
            consent_version = data.get("consent_version")
            if not isinstance(employee_id, int) or not isinstance(samples, list) or not 3 <= len(samples) <= 10 or not all(isinstance(sample, str) for sample in samples):
                return _json({"error": "invalid_enrollment_request"}, 400)
            if not consent_acknowledged or consent_version != "2026-11-02-v1":
                return _json({"error": "employee_acknowledgment_required"}, 400)
            employee = request.env["hr.employee"].browse(employee_id).exists()
            if not employee or employee.company_id != request.env.company or not employee.active:
                return _json({"error": "employee_not_available"}, 404)
            if employee.ff_face_enrollment_status == "revocation_pending":
                return _json({"error": "revocation_pending"}, 409)
            if any(len(sample) > 2_700_000 for sample in samples):
                return _json({"error": "sample_too_large"}, 413)
            params = request.env["ir.config_parameter"].sudo()
            service_url = params.get_param("ff_face_attendance.service_url")
            admin_token = params.get_param("ff_face_attendance.pilot_admin_token")
            if not service_url or not service_url.startswith("https://") or not admin_token:
                return _json({"error": "pilot_service_unconfigured"}, 503)
            template_ref = (
                employee.ff_face_template_ref
                if employee.ff_face_enrollment_status in ("enrolled", "re_enrollment") and employee.ff_face_template_ref
                else "odoo-" + uuid.uuid4().hex
            )
            local_tls_test = (
                params.get_param("ff_face_attendance.allow_insecure_local_service") == "true"
                and service_url.startswith("https://127.0.0.1")
            )
            response = requests.post(
                service_url.rstrip("/") + "/v1/pilot/enroll",
                json={"template_ref": template_ref, "samples": samples},
                headers={"X-FF-Admin-Token": admin_token},
                timeout=(2, 30),
                verify=not local_tls_test,
            )
            if response.status_code != 200:
                reason = _safe_enrollment_error(response)
                _logger.warning("face_enrollment_service_rejected employee=%s status=%s reason=%s", employee.id, response.status_code, reason)
                return _json({"error": reason}, 422)
            result = response.json()
            model_version = result.get("model_version")
            if not isinstance(model_version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", model_version):
                return _json({"error": "invalid_pilot_response"}, 502)
            request.env["ff.face.consent.receipt"].create({
                "employee_id": employee.id, "notice_version": consent_version,
            })
            employee.sudo().write({
                "ff_face_enrollment_status": "enrolled",
                "ff_face_template_ref": template_ref,
                "ff_face_model_version": model_version,
                "ff_face_enrolled_at": fields.Datetime.now(),
                "ff_face_enrollment_operator_id": request.env.user.id,
                "ff_face_sample_count": len(samples),
                "ff_face_quality_status": "accepted",
            })
            return _json({"result": "enrolled", "model_version": model_version, "sample_count": len(samples)})
        except (ValueError, TypeError, KeyError, requests.RequestException):
            return _json({"error": "pilot_enrollment_unavailable"}, 503)

    @http.route("/ff_face_attendance/pilot/enroll_public", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def pilot_enroll_public(self, **kwargs):
        """Loopback-only local demo enrollment; never enable this switch in production."""
        params = request.env["ir.config_parameter"].sudo()
        if not (
            params.get_param("ff_face_attendance.allow_insecure_local_pairing") == "true"
            and request.httprequest.remote_addr in {"127.0.0.1", "::1"}
        ):
            return _json({"error": "local_pilot_only"}, 403)
        if not _same_origin_request():
            return _json({"error": "same_origin_required"}, 403)
        device = self._device()
        if not device:
            return _json({"error": "unauthorized_device"}, 401)
        if not request.env.user.has_group("hr.group_hr_manager"):
            return _json({"error": "hr_manager_required"}, 403)
        try:
            data = json.loads(request.httprequest.get_data(cache=False))
            employee_id, samples = data.get("employee_id"), data.get("samples")
            if not isinstance(employee_id, int) or not isinstance(samples, list) or not 3 <= len(samples) <= 10:
                return _json({"error": "invalid_enrollment_request"}, 400)
            if data.get("consent_acknowledged") is not True or data.get("consent_version") != "2026-11-02-v1":
                return _json({"error": "employee_acknowledgment_required"}, 400)
            employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
            if not employee or employee.company_id != device.company_id or not employee.active:
                return _json({"error": "employee_not_available"}, 404)
            if employee.ff_face_enrollment_status == "revocation_pending":
                return _json({"error": "revocation_pending"}, 409)
            service_url = params.get_param("ff_face_attendance.service_url")
            admin_token = params.get_param("ff_face_attendance.pilot_admin_token")
            if not service_url or not service_url.startswith("https://") or not admin_token:
                return _json({"error": "pilot_service_unconfigured"}, 503)
            # The public endpoint is loopback-only. In this local supervised pilot,
            # re-enrollment replaces the samples for this same employee template.
            template_ref = (
                employee.ff_face_template_ref
                if employee.ff_face_enrollment_status in ("enrolled", "re_enrollment") and employee.ff_face_template_ref
                else "odoo-" + uuid.uuid4().hex
            )
            response = requests.post(
                service_url.rstrip("/") + "/v1/pilot/enroll",
                json={"template_ref": template_ref, "samples": samples},
                headers={"X-FF-Admin-Token": admin_token},
                timeout=(2, 30),
                verify=not (
                    params.get_param("ff_face_attendance.allow_insecure_local_service") == "true"
                    and service_url.startswith("https://127.0.0.1")
                ),
            )
            if response.status_code != 200:
                reason = _safe_enrollment_error(response)
                _logger.warning("local_face_enrollment_rejected employee=%s status=%s reason=%s samples=%s", employee.id, response.status_code, reason, len(samples))
                return _json({"error": reason}, 422)
            result = response.json()
            model_version = result.get("model_version")
            if not isinstance(model_version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", model_version):
                return _json({"error": "invalid_pilot_response"}, 502)
            if not request.env.user._is_public():
                request.env["ff.face.consent.receipt"].create({
                    "employee_id": employee.id, "notice_version": "2026-11-02-v1",
                })
            employee.sudo().write({
                "ff_face_enrollment_status": "enrolled",
                "ff_face_template_ref": template_ref,
                "ff_face_model_version": model_version,
                "ff_face_enrolled_at": fields.Datetime.now(),
                "ff_face_enrollment_operator_id": request.env.user.id if not request.env.user._is_public() else False,
                "ff_face_sample_count": len(samples),
                "ff_face_quality_status": "accepted",
            })
            return _json({"result": "enrolled", "model_version": model_version, "sample_count": len(samples)})
        except (ValueError, TypeError, KeyError, requests.RequestException):
            return _json({"error": "pilot_enrollment_unavailable"}, 503)

    @http.route("/ff_face_attendance/landmarks", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def face_landmarks(self, **kwargs):
        """Return five YuNet alignment points only while the user explicitly enables the guide."""
        if not _same_origin_request():
            return _json({"error": "same_origin_required"}, 403)
        device = self._device()
        if not device:
            return _json({"error": "unauthorized_device"}, 401)
        try:
            encoded_limit = ((device.policy_id.max_capture_bytes + 2) // 3) * 4
            if request.httprequest.content_length and request.httprequest.content_length > encoded_limit + 1024:
                return _json({"error": "request_too_large"}, 413)
            raw_body = request.httprequest.get_data(cache=False)
            if len(raw_body) > encoded_limit + 1024:
                return _json({"error": "request_too_large"}, 413)
            data = json.loads(raw_body)
            capture = data.get("capture")
            if not isinstance(capture, str) or not 4 <= len(capture) <= encoded_limit:
                return _json({"error": "invalid_capture"}, 400)

            # Serialize preview calls and cap this opt-in camera upload to one frame per second.
            request.env.cr.execute("SELECT id FROM ff_face_device WHERE id = %s FOR UPDATE", [device.id])
            device.invalidate_recordset(["last_landmark_request_at"])
            now = fields.Datetime.now()
            last_request = fields.Datetime.to_datetime(device.last_landmark_request_at) if device.last_landmark_request_at else None
            if last_request and (now - last_request).total_seconds() < 1.0:
                return _json({"error": "landmark_rate_limited"}, 429)
            device.sudo().write({"last_landmark_request_at": now})

            params = request.env["ir.config_parameter"].sudo()
            service_url = params.get_param("ff_face_attendance.service_url")
            request_secret = params.get_param("ff_face_attendance.service_request_secret")
            response_secret = params.get_param("ff_face_attendance.service_hmac_secret")
            if not service_url or not service_url.startswith("https://") or not request_secret or not response_secret:
                return _json({"error": "face_service_unavailable"}, 503)
            nonce = secrets.token_urlsafe(32)
            timestamp = str(int(time.time()))
            capture_hash = hashlib.sha256(capture.encode("ascii")).hexdigest()
            message = "\n".join((timestamp, nonce, str(device.id), str(device.company_id.id), capture_hash)).encode()
            signature = hmac.new(request_secret.encode(), message, hashlib.sha256).hexdigest()
            local_tls_test = (
                params.get_param("ff_face_attendance.allow_insecure_local_service") == "true"
                and service_url.startswith("https://127.0.0.1")
            )
            service_response = requests.post(
                service_url.rstrip("/") + "/v1/landmarks",
                json={"capture": capture, "nonce": nonce, "device_ref": str(device.id), "company_ref": str(device.company_id.id)},
                headers={"Content-Type": "application/json", "X-FF-Timestamp": timestamp, "X-FF-Request-Signature": signature},
                timeout=(2, 5),
                verify=not local_tls_test,
            )
            if service_response.status_code != 200:
                reason = "one_face_required" if service_response.status_code == 422 else "face_service_unavailable"
                return _json({"error": reason}, 422 if service_response.status_code == 422 else 503)
            result = service_response.json()
            if not self._validate_landmarks(result, nonce, response_secret):
                return _json({"error": "invalid_landmark_response"}, 502)
            return _json({key: result[key] for key in ("width", "height", "face_box", "points", "confidence")})
        except (ValueError, TypeError, KeyError, requests.RequestException):
            _logger.exception("face_landmark_preview_failed device=%s", device.id)
            return _json({"error": "face_service_unavailable"}, 503)

    @staticmethod
    def _validate_landmarks(result, nonce, secret):
        if not isinstance(result, dict):
            return False
        signed = dict(result)
        signature = signed.pop("signature", None)
        if not signature or signed.get("nonce") != nonce:
            return False
        try:
            if abs(time.time() - int(signed["issued_at"])) > 20:
                return False
            if not 1 <= int(signed["width"]) <= 4096 or not 1 <= int(signed["height"]) <= 4096:
                return False
            if not 0 <= float(signed["confidence"]) <= 1:
                return False
            points = signed["points"]
            if set(points) != {"left_eye", "right_eye", "nose", "mouth_left", "mouth_right"}:
                return False
            for point in points.values():
                if not 0 <= float(point["x"]) <= 1 or not 0 <= float(point["y"]) <= 1:
                    return False
        except (KeyError, TypeError, ValueError):
            return False
        expected = hmac.new(secret.encode(), json.dumps(signed, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature))

    @http.route("/ff_face_attendance/session", type="http", auth="public", methods=["POST"], csrf=False)
    def create_session(self, **kwargs):
        device = self._device()
        if not device:
            return _json({"error": "unauthorized_device"}, 401)
        if not device.policy_id.active or not device.policy_id.biometric_enabled:
            return _json({"error": "device_or_biometric_policy_unavailable"}, 403)
        request.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", [812734, device.id])
        request.env.cr.execute("SELECT count(*) FROM ff_face_session WHERE device_id = %s AND create_date >= (NOW() AT TIME ZONE 'UTC') - interval '1 minute'", [device.id])
        if request.env.cr.fetchone()[0] >= 20:
            return _json({"error": "device_rate_limited"}, 429)
        session, nonce = request.env["ff.face.session"].sudo().issue(device)
        return _json({"session_id": session.id, "nonce": nonce, "challenge": session.challenge, "expires_in": 45})

    @http.route("/ff_face_attendance/verify", type="http", auth="public", methods=["POST"], csrf=False)
    def verify(self, **kwargs):
        device = self._device()
        if not device:
            return _json({"error": "unauthorized_device"}, 401)
        phase = "read_request"
        try:
            encoded_frame_bytes = ((device.policy_id.max_capture_bytes + 2) // 3) * 4
            max_request_bytes = (encoded_frame_bytes * 6) + 16384  # Five prompted frames plus the signed first-frame field.
            if request.httprequest.content_length and request.httprequest.content_length > max_request_bytes:
                return _json({"error": "request_too_large"}, 413)
            raw_body = request.httprequest.get_data(cache=False)
            if len(raw_body) > max_request_bytes:
                return _json({"error": "request_too_large"}, 413)
            data = json.loads(raw_body)
            session_id = data.get("session_id")
            nonce = data.get("nonce")
            capture = data.get("capture")
            frames = data.get("frames")
            challenge = data.get("challenge")
            action = data.get("action")
            expected_employee_id = data.get("expected_employee_id")
            if action not in ("check_in", "check_out") or isinstance(expected_employee_id, bool) or not isinstance(expected_employee_id, int) or expected_employee_id < 1:
                return _json({"error": "invalid_attendance_action"}, 400)
            if frames is not None:
                if not isinstance(frames, list) or not 3 <= len(frames) <= 5 or not all(isinstance(frame, str) for frame in frames):
                    return _json({"error": "invalid_frames"}, 400)
                capture = frames[0]
            if not isinstance(session_id, int) or not isinstance(nonce, str) or not isinstance(capture, str):
                return _json({"error": "invalid_request"}, 400)
            if len(capture) > ((device.policy_id.max_capture_bytes + 2) // 3) * 4:
                return _json({"error": "capture_too_large"}, 413)
            if frames and any(len(frame) > ((device.policy_id.max_capture_bytes + 2) // 3) * 4 for frame in frames):
                return _json({"error": "capture_too_large"}, 413)
            Session = request.env["ff.face.session"].sudo()
            session = Session.browse(session_id).exists()
            expected_nonce_hash = Session.hash_nonce(nonce)
            if not session or session.device_id != device or not hmac.compare_digest(session.nonce_hash, expected_nonce_hash):
                return _json({"error": "invalid_session"}, 403)
            if challenge not in ("turn_left", "turn_right") or challenge != session.challenge:
                return _json({"error": "challenge_mismatch"}, 403)
            # Consume before network I/O. Returning a response (rather than raising) commits this state on service errors.
            try:
                request.env.cr.execute("SELECT id FROM ff_face_session WHERE id = %s FOR UPDATE", [session.id])
                session.invalidate_recordset(["consumed_at", "expires_at"])
                session.consume()
            except ValidationError:
                return _json({"error": "expired_or_replayed_session"}, 409)

            phase = "call_face_service"
            result = self._call_service(capture, nonce, device, frames=frames, challenge=challenge)
            if isinstance(result, dict) and result.get("service_error"):
                reason = result["service_error"]
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "event_id": str(uuid.uuid4()), "result": "rejected", "reason_code": reason,
                })
                return _json({"error": reason}, 422)
            if not result:
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "event_id": str(uuid.uuid4()), "result": "error", "reason_code": "service_unavailable",
                })
                return _json({"error": "verification_unavailable"}, 503)
            phase = "validate_face_service_evidence"
            if not self._validate_result(result, nonce):
                _logger.error("face_verification_rejected phase=%s reason=invalid_service_evidence", phase)
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "event_id": str(uuid.uuid4()), "result": "rejected", "reason_code": "invalid_service_evidence",
                })
                return _json({"error": "verification_rejected"}, 401)

            phase = "resolve_employee"
            employee = request.env["hr.employee"].sudo().search([
                ("ff_face_template_ref", "=", result["template_ref"]),
                ("company_id", "=", device.company_id.id),
                ("active", "=", True),
                ("ff_face_enrollment_status", "=", "enrolled"),
            ], limit=2)
            if len(employee) != 1:
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "event_id": result["event_id"], "result": "rejected", "reason_code": "unknown_or_ambiguous_identity", "model_version": result["model_version"],
                })
                return _json({"error": "verification_rejected"}, 401)
            if employee.id != expected_employee_id:
                _logger.warning(
                    "face_identity_mismatch device=%s expected_employee=%s matched_employee=%s event=%s",
                    device.id, expected_employee_id, employee.id, result["event_id"],
                )
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "event_id": result["event_id"], "result": "rejected",
                    "reason_code": "face_identity_mismatch", "model_version": result["model_version"],
                })
                return _json({"error": "face_identity_mismatch"}, 409)

            # Serialize state changes by employee to prevent two devices opening the same interval concurrently.
            phase = "lock_attendance_state"
            request.env.cr.execute("SELECT id FROM hr_employee WHERE id = %s FOR UPDATE", [employee.id])
            employee.invalidate_recordset(["attendance_state", "last_attendance_id"])
            last = request.env["hr.attendance"].sudo().search([("employee_id", "=", employee.id)], order="check_in desc, id desc", limit=1)
            if action == "check_in" and last and last.check_in and (fields.Datetime.to_datetime(fields.Datetime.now()) - fields.Datetime.to_datetime(last.check_in)).total_seconds() < device.policy_id.minimum_event_interval_seconds:
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "employee_id": employee.id, "event_id": result["event_id"], "result": "rejected", "reason_code": "minimum_event_interval", "model_version": result["model_version"],
                })
                return _json({"error": "duplicate_event_suppressed"}, 409)
            is_checked_in = bool(last and not last.check_out)
            if action == "check_in" and is_checked_in:
                return _json({"error": "already_checked_in", "checked_in": True}, 409)
            if action == "check_out" and not is_checked_in:
                return _json({"error": "not_checked_in", "checked_in": False}, 409)
            phase = "write_attendance"
            with request.env.cr.savepoint():
                attendance = employee._face_attendance_action(result["event_id"], device, result["model_version"])
                request.env["ff.face.attempt"].sudo().create({
                    "device_id": device.id, "employee_id": employee.id, "event_id": result["event_id"], "result": "accepted", "model_version": result["model_version"], "attendance_id": attendance.id,
                })
                attendance_action = "check_out" if attendance.check_out else "check_in"
                success_response = _json({"result": "accepted", "action": attendance_action})
            _logger.info("face_attendance_recorded device=%s employee=%s action=%s attendance=%s", device.id, employee.id, attendance_action, attendance.id)
            return success_response
        except (ValueError, TypeError, KeyError, requests.RequestException) as exc:
            _logger.exception("face_verification_failed phase=%s error_type=%s", phase, type(exc).__name__)
            return _json({"error": "verification_unavailable"}, 503)

    @staticmethod
    def _call_service(capture, nonce, device, frames=None, challenge=None):
        params = request.env["ir.config_parameter"].sudo()
        url = params.get_param("ff_face_attendance.service_url")
        if not url or not url.startswith("https://"):
            return None
        try:
            request_secret = params.get_param("ff_face_attendance.service_request_secret")
            if not request_secret:
                return None
            timestamp = str(int(time.time()))
            signed_capture = "\n".join(frames) if frames else capture
            capture_hash = hashlib.sha256(signed_capture.encode("ascii")).hexdigest()
            message = "\n".join((timestamp, nonce, str(device.id), str(device.company_id.id), capture_hash)).encode()
            signature = hmac.new(request_secret.encode(), message, hashlib.sha256).hexdigest()
            payload = {"capture": capture, "nonce": nonce, "device_ref": str(device.id), "company_ref": str(device.company_id.id)}
            if frames:
                payload.update({"frames": frames, "challenge": challenge})
            local_tls_test = (
                params.get_param("ff_face_attendance.allow_insecure_local_service") == "true"
                and url.startswith("https://127.0.0.1")
            )
            response = requests.post(
                url.rstrip("/") + "/v1/verify",
                json=payload,
                timeout=(2, 8),
                verify=not local_tls_test,
                headers={"Content-Type": "application/json", "X-FF-Timestamp": timestamp, "X-FF-Request-Signature": signature},
            )
            if response.status_code != 200:
                service_error = "face_service_unavailable"
                try:
                    detail = response.json().get("detail")
                    if isinstance(detail, str) and detail in {
                        "motion_challenge_failed", "face_match_failed", "exactly_one_face_required",
                        "invalid_image", "invalid_face_crop", "pilot_not_enrolled_or_insufficient_frames",
                    }:
                        service_error = detail
                except (ValueError, AttributeError):
                    pass
                _logger.warning(
                    "face_service_rejected device=%s status=%s reason=%s frames=%s",
                    device.id, response.status_code, service_error, len(frames or []),
                )
                return {"service_error": service_error}
            _logger.info("face_service_verified device=%s frames=%s", device.id, len(frames or []))
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            _logger.exception("face_service_call_failed error_type=%s", type(exc).__name__)
            return None

    @staticmethod
    def _validate_result(result, nonce):
        if not isinstance(result, dict):
            return False
        required = ("nonce", "template_ref", "passed", "event_id", "model_version", "issued_at", "signature")
        if any(key not in result for key in required) or result["passed"] is not True or result["nonce"] != nonce:
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", str(result["event_id"])):
            return False
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(result["model_version"])):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,160}", str(result["template_ref"])):
            return False
        try:
            if abs(time.time() - int(result["issued_at"])) > 20:
                return False
        except (TypeError, ValueError):
            return False
        params = request.env["ir.config_parameter"].sudo()
        secret = params.get_param("ff_face_attendance.service_hmac_secret")
        if not secret:
            return False
        signed = {key: result[key] for key in required if key != "signature"}
        expected = hmac.new(secret.encode(), json.dumps(signed, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(result["signature"]))
