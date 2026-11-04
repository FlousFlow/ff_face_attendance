from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class FaceAttendanceException(models.Model):
    _name = "ff.face.exception"
    _description = "Face Attendance HR Exception"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "create_date desc"

    name = fields.Char(required=True, default=lambda self: _("Attendance review"), tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict", check_company=True, index=True)
    company_id = fields.Many2one("res.company", related="employee_id.company_id", store=True, index=True)
    device_id = fields.Many2one("ff.face.device", ondelete="restrict", check_company=True)
    reason = fields.Selection([("open_attendance", "Existing open attendance"), ("service_unavailable", "Verification service unavailable"), ("manual_review", "Manual HR review")], required=True, tracking=True)
    details = fields.Text(groups="ff_face_attendance.group_ff_face_manager")
    state = fields.Selection([("open", "Open"), ("review", "Under Review"), ("resolved", "Resolved"), ("rejected", "Rejected")], default="open", required=True, tracking=True)
    resolution = fields.Text(groups="ff_face_attendance.group_ff_face_manager", tracking=True)

    def action_start_review(self):
        self._check_hr()
        self.write({"state": "review"})

    def action_resolve(self):
        self._check_hr()
        if any(not exception.resolution for exception in self):
            raise UserError(_("Add a resolution note before closing the exception."))
        self.write({"state": "resolved"})

    def action_reject(self):
        self._check_hr()
        self.write({"state": "rejected"})

    def _check_hr(self):
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_user"):
            raise AccessError(_("Only authorized HR staff can process attendance exceptions."))
