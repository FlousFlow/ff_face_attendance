import hashlib
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class FaceVerificationSession(models.Model):
    _name = "ff.face.session"
    _description = "Single-use Face Verification Session"
    _check_company_auto = True

    nonce_hash = fields.Char(required=True, index=True, copy=False)
    challenge = fields.Selection(
        [("turn_left", "Turn left"), ("turn_right", "Turn right")],
        required=True,
        default=lambda self: secrets.choice(("turn_left", "turn_right")),
        copy=False,
    )
    device_id = fields.Many2one("ff.face.device", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    expires_at = fields.Datetime(required=True, index=True)
    consumed_at = fields.Datetime(readonly=True)

    _nonce_unique = models.Constraint("unique (nonce_hash)", "A verification nonce can only be issued once.")

    @api.model
    def issue(self, device):
        nonce = secrets.token_urlsafe(32)
        session = self.create({
            "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
            "challenge": secrets.choice(("turn_left", "turn_right")),
            "device_id": device.id,
            "expires_at": fields.Datetime.now() + timedelta(seconds=45),
        })
        return session, nonce

    def consume(self):
        self.ensure_one()
        if self.consumed_at or self.expires_at < fields.Datetime.now():
            raise ValidationError(_("The verification session is expired or already used."))
        self.write({"consumed_at": fields.Datetime.now()})

    @api.model
    def hash_nonce(self, nonce):
        return hashlib.sha256(nonce.encode()).hexdigest()


class FaceAttempt(models.Model):
    _name = "ff.face.attempt"
    _description = "Face Attendance Verification Audit"
    # hr.attendance has no company_id; company consistency is validated explicitly below.
    _order = "create_date desc"

    device_id = fields.Many2one("ff.face.device", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", check_company=True, index=True)
    event_id = fields.Char(required=True, index=True, copy=False)
    result = fields.Selection([("accepted", "Accepted"), ("rejected", "Rejected"), ("error", "Service Error")], required=True)
    reason_code = fields.Char()
    model_version = fields.Char()
    # hr.attendance has no company_id field; validate its company through employee_id.
    attendance_id = fields.Many2one("hr.attendance", ondelete="set null")

    _event_unique = models.Constraint("unique (event_id)", "An event identifier may only be processed once.")

    @api.model_create_multi
    def create(self, vals_list):
        # Public routes never accept caller-supplied employee or attendance IDs as trusted identity.
        if not self.env.su:
            raise AccessError(_("Verification audit records can only be created by the trusted server flow."))
        return super().create(vals_list)

    @api.constrains("device_id", "employee_id", "attendance_id")
    def _check_audit_company_consistency(self):
        for attempt in self:
            if attempt.employee_id and attempt.device_id and attempt.employee_id.company_id != attempt.device_id.company_id:
                raise ValidationError(_("The audit employee must belong to the kiosk company."))
            if attempt.attendance_id:
                attendance_employee = attempt.attendance_id.employee_id
                if attempt.employee_id and attendance_employee != attempt.employee_id:
                    raise ValidationError(_("The linked attendance must belong to the audit employee."))
                if attendance_employee.company_id != attempt.device_id.company_id:
                    raise ValidationError(_("The linked attendance must belong to the kiosk company."))
