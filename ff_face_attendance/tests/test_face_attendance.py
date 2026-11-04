from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestFaceAttendanceFoundation(HttpCase):
    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ff_face_attendance.service_ready", "false")
        params.set_param("ff_face_attendance.allow_insecure_local_pairing", "false")

    def test_biometric_policy_defaults_disabled(self):
        policy = self.env["ff.face.policy"].create({"name": "Disabled by default", "company_id": self.env.company.id})
        self.assertFalse(policy.biometric_enabled)

    def test_biometric_policy_cannot_enable_without_service(self):
        policy = self.env["ff.face.policy"].create({"name": "Blocked", "company_id": self.env.company.id})
        self.env["ir.config_parameter"].sudo().set_param("ff_face_attendance.service_ready", "false")
        with self.assertRaises(ValidationError):
            policy.biometric_enabled = True

    def test_device_credential_is_hashed_and_rotatable(self):
        policy = self.env["ff.face.policy"].create({"name": "Device policy", "company_id": self.env.company.id})
        device = self.env["ff.face.device"].create({"name": "Test kiosk", "policy_id": policy.id, "company_id": self.env.company.id})
        self.assertFalse(device.credential_hash)
        action = device.action_rotate_credential()
        self.assertTrue(device.credential_hash)
        self.assertEqual(device.credential_hash, device._hash_credential(action["params"]["credential"]))
        self.assertEqual(device.credential_hint, action["params"]["credential"][-6:])

    def test_kiosk_page_is_public_and_fails_closed(self):
        response = self.url_open("/ff_face_attendance/kiosk")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Free supervised pilot", response.content)
        self.assertIn(b"ff-enrollment-consent", response.content)
        self.assertIn(b"ff-employee-search", response.content)

    def test_camera_preview_does_not_upload_frames_passively(self):
        from pathlib import Path
        js_path = Path(__file__).parents[1] / "static/src/kiosk.js"
        source = js_path.read_text()
        self.assertNotIn("pilot/inspect", source)
        self.assertNotIn("setInterval(inspectFace", source)

    def test_kiosk_pairing_requires_https(self):
        response = self.url_open("/ff_face_attendance/device/enroll", data=b"", method="POST")
        self.assertIn(response.status_code, (400, 401))
        if response.status_code == 400:
            self.assertEqual(response.json()["error"], "https_required")
        else:
            self.assertEqual(response.json()["error"], "unauthorized_device")

    def test_session_endpoint_rejects_unpaired_kiosk(self):
        response = self.url_open("/ff_face_attendance/session", data=b"", method="POST")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "unauthorized_device")

    def test_device_status_does_not_pair_an_unconfigured_browser(self):
        response = self.url_open("/ff_face_attendance/device/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["paired"])

    def test_employee_face_action_opens_selected_employee_kiosk(self):
        employee = self.env["hr.employee"].create({"name": "Kiosk Action Test"})
        action = employee.action_open_face_enrollment_kiosk()
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["url"], f"/ff_face_attendance/enroll?employee_id={employee.id}")

    def test_enrollment_acknowledgment_is_immutable(self):
        employee = self.env["hr.employee"].create({"name": "Consent Test"})
        receipt = self.env["ff.face.consent.receipt"].create({
            "employee_id": employee.id, "notice_version": "2026-11-02-v1",
        })
        self.assertEqual(receipt.recorded_by, self.env.user)
        with self.assertRaises(AccessError):
            receipt.write({"notice_version": "changed"})

    def test_enrollment_requires_current_employee_acknowledgment(self):
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/ff_face_attendance/pilot/enroll",
            json={"employee_id": 1, "samples": ["AAAA", "BBBB", "CCCC"]},
            headers={"Origin": self.base_url()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "employee_acknowledgment_required")

    def test_revocation_stays_pending_until_remote_delete_succeeds(self):
        employee = self.env["hr.employee"].create({"name": "Revocation Test"})
        employee.sudo().write({
            "ff_face_template_ref": "odoo-template-12345678",
            "ff_face_enrollment_status": "enrolled",
            "ff_face_sample_count": 4,
        })
        employee.action_revoke_face_enrollment()
        self.assertEqual(employee.ff_face_enrollment_status, "revocation_pending")
        self.assertEqual(employee.ff_face_template_ref, "odoo-template-12345678")

        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return {"result": "revoked", "deleted": True}

        from unittest.mock import patch
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ff_face_attendance.service_url", "https://face-service.invalid")
        params.set_param("ff_face_attendance.pilot_admin_token", "test-token")
        with patch("odoo.addons.ff_face_attendance.models.hr_employee.requests.post", return_value=_Response()):
            self.env["hr.employee"]._cron_revoke_face_templates()
        self.assertEqual(employee.ff_face_enrollment_status, "revoked")
        self.assertFalse(employee.ff_face_template_ref)

    def test_accepted_attempt_can_link_native_attendance_without_company_field_error(self):
        company = self.env.company
        policy = self.env["ff.face.policy"].create({"name": "Audit link", "company_id": company.id})
        device = self.env["ff.face.device"].create({
            "name": "Audit-link kiosk", "company_id": company.id, "policy_id": policy.id,
        })
        employee = self.env["hr.employee"].create({"name": "Audit-link employee", "company_id": company.id})
        attendance = self.env["hr.attendance"].create({"employee_id": employee.id})
        attempt = self.env["ff.face.attempt"].sudo().create({
            "device_id": device.id, "employee_id": employee.id,
            "event_id": "test-event-company-link-0001", "result": "accepted",
            "attendance_id": attendance.id,
        })
        self.assertEqual(attempt.attendance_id, attendance)
