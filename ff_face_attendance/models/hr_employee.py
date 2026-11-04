import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def action_open_face_enrollment_kiosk(self):
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_manager"):
            raise AccessError(_("Only an HR manager can open the face enrollment kiosk."))
        self.ensure_one()
        if not self.active:
            raise UserError(_("Archived employees cannot use the face enrollment kiosk."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/ff_face_attendance/admin/enroll?employee_id={self.id}",
            "target": "new",
        }

    def _face_attendance_action(self, event_id, device, model_version):
        """Apply trusted face evidence through the standard employee attendance flow."""
        self.ensure_one()
        attendance = self._attendance_action_change()
        if attendance.check_out:
            attendance.write({"ff_face_check_out_event_id": event_id})
        else:
            attendance.write({"ff_face_check_in_event_id": event_id})
        mode_field = "out_mode" if attendance.check_out else "in_mode"
        attendance.write({
            "ff_face_device_id": device.id,
            "ff_face_model_version": model_version,
            "ff_face_verification_method": "challenge",
            mode_field: "kiosk",
        })
        return attendance

    ff_face_enrollment_status = fields.Selection([
        ("not_enrolled", "Not Enrolled"), ("enrolled", "Enrolled"),
        ("revocation_pending", "Revocation Pending"),
        ("revoked", "Revoked"), ("re_enrollment", "Re-enrollment Required"),
    ], string="Face Enrollment Status", default="not_enrolled", copy=False, readonly=True, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_template_ref = fields.Char(string="Face Template Reference", copy=False, index=True, readonly=True, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_model_version = fields.Char(string="Face Model Version", copy=False, readonly=True, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_enrolled_at = fields.Datetime(string="Face Enrolled At", readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_enrollment_operator_id = fields.Many2one("res.users", string="Enrollment Operator", readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_sample_count = fields.Integer(string="Face Sample Count", readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_quality_status = fields.Selection([("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected")], string="Face Quality Status", readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_manager")
    ff_face_consent_receipt_ids = fields.One2many("ff.face.consent.receipt", "employee_id", string="Face Consent History", groups="ff_face_attendance.group_ff_face_manager", readonly=True)

    @api.model
    def _cron_revoke_face_templates(self):
        """Retry remote template deletion; keep identity blocked until deletion succeeds."""
        params = self.env["ir.config_parameter"].sudo()
        service_url = params.get_param("ff_face_attendance.service_url", "")
        admin_token = params.get_param("ff_face_attendance.pilot_admin_token", "")
        if not service_url.startswith("https://") or not admin_token:
            return
        employees = self.sudo().search([
            ("ff_face_enrollment_status", "=", "revocation_pending"),
            ("ff_face_template_ref", "!=", False),
        ], limit=100)
        for employee in employees:
            try:
                local_tls_test = (
                    params.get_param("ff_face_attendance.allow_insecure_local_service") == "true"
                    and service_url.startswith("https://127.0.0.1")
                )
                response = requests.post(
                    service_url.rstrip("/") + "/v1/pilot/revoke",
                    json={"template_ref": employee.ff_face_template_ref},
                    headers={"X-FF-Admin-Token": admin_token}, timeout=(2, 10),
                    verify=not local_tls_test,
                )
                if response.status_code != 200 or response.json().get("result") != "revoked":
                    _logger.warning("face_template_revoke_pending employee=%s status=%s", employee.id, response.status_code)
                    continue
                employee.write({
                    "ff_face_enrollment_status": "revoked", "ff_face_template_ref": False,
                    "ff_face_model_version": False, "ff_face_quality_status": False,
                    "ff_face_sample_count": 0,
                })
            except (requests.RequestException, ValueError, AttributeError):
                _logger.exception("face_template_revoke_retry_failed employee=%s", employee.id)

    @api.constrains("ff_face_template_ref", "company_id", "ff_face_enrollment_status")
    def _check_face_template_unique_per_company(self):
        for employee in self.filtered("ff_face_template_ref"):
            duplicate = self.search([
                ("id", "!=", employee.id),
                ("company_id", "=", employee.company_id.id),
                ("ff_face_template_ref", "=", employee.ff_face_template_ref),
                ("ff_face_enrollment_status", "=", "enrolled"),
            ], limit=1)
            if duplicate:
                raise ValidationError(_("An active face template can only belong to one employee per company."))

    def action_revoke_face_enrollment(self):
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_manager"):
            raise AccessError(_("Only an HR manager can revoke biometric enrollment."))
        for employee in self:
            employee.write({
                "ff_face_enrollment_status": "revocation_pending" if employee.ff_face_template_ref else "revoked",
                **({} if employee.ff_face_template_ref else {
                    "ff_face_model_version": False, "ff_face_quality_status": False,
                    "ff_face_sample_count": 0,
                }),
            })
        self.env.ref("ff_face_attendance.ir_cron_revoke_face_templates")._trigger()


class ResCompany(models.Model):
    _inherit = "res.company"

    ff_face_policy_ids = fields.One2many("ff.face.policy", "company_id", string="Face Attendance Policies")
    ff_face_attendance_enabled = fields.Boolean(compute="_compute_ff_face_attendance_enabled")

    def _compute_ff_face_attendance_enabled(self):
        for company in self:
            company.ff_face_attendance_enabled = bool(company.ff_face_policy_ids.filtered("biometric_enabled"))
