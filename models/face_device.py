import hashlib
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class FaceDevice(models.Model):
    _name = "ff.face.device"
    _description = "Face Attendance Kiosk Device"
    _check_company_auto = True
    _order = "name"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    location = fields.Char()
    active = fields.Boolean(default=True)
    revoked_at = fields.Datetime(readonly=True, copy=False)
    credential_hash = fields.Char(groups="hr.group_hr_manager", readonly=True, copy=False)
    credential_hint = fields.Char(readonly=True, copy=False)
    policy_id = fields.Many2one("ff.face.policy", required=True, ondelete="restrict", check_company=True)
    last_landmark_request_at = fields.Datetime(readonly=True, copy=False, groups="hr.group_hr_manager")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.user.has_group("hr.group_hr_manager"):
                raise AccessError(_("Only an HR manager can register a kiosk device."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can configure kiosk devices."))
        return super().write(vals)

    def unlink(self):
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can remove kiosk devices."))
        return super().unlink()

    @staticmethod
    def _hash_credential(raw):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def action_rotate_credential(self):
        self.ensure_one()
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can rotate device credentials."))
        secret = secrets.token_urlsafe(32)
        self.write({"credential_hash": self._hash_credential(secret), "credential_hint": secret[-6:]})
        return {
            "type": "ir.actions.client",
            "tag": "ff_face_device_credential",
            "params": {"credential": secret},
        }

    def action_revoke(self):
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can revoke a kiosk device."))
        self.write({"active": False, "revoked_at": fields.Datetime.now()})


class FacePolicy(models.Model):
    _name = "ff.face.policy"
    _description = "Face Attendance Policy"
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    active = fields.Boolean(default=True)
    biometric_enabled = fields.Boolean(default=False, help="Enables the experimental supervised face pilot. This is not strong liveness or anti-spoofing; keep Badge/PIN available.")
    minimum_event_interval_seconds = fields.Integer(default=120, required=True)
    allow_automatic_checkout = fields.Boolean(default=False)
    max_capture_bytes = fields.Integer(default=2_000_000, required=True)
    _company_name_uniq = models.Constraint("unique (company_id, name)", "Policy names must be unique per company.")
    _interval_positive = models.Constraint("check (minimum_event_interval_seconds >= 30)", "The minimum event interval must be at least 30 seconds.")
    _capture_limit = models.Constraint("check (max_capture_bytes between 1024 and 5000000)", "Capture size must be between 1 KB and 5 MB.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can configure biometric policies."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can configure biometric policies."))
        return super().write(vals)

    def unlink(self):
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise AccessError(_("Only an HR manager can delete biometric policies."))
        return super().unlink()

    @api.constrains("biometric_enabled")
    def _require_service_readiness(self):
        if any(p.biometric_enabled for p in self):
            params = self.env["ir.config_parameter"].sudo()
            ready = params.get_param("ff_face_attendance.service_ready") == "true"
            service_url = params.get_param("ff_face_attendance.service_url")
            service_secret = params.get_param("ff_face_attendance.service_hmac_secret")
            request_secret = params.get_param("ff_face_attendance.service_request_secret")
            if not (ready and service_url and service_secret and request_secret):
                raise ValidationError(_("Biometric operations cannot be enabled until the external service is configured and its readiness is verified."))
