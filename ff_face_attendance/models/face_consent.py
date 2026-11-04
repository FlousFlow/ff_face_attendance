from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class FaceConsentReceipt(models.Model):
    _name = "ff.face.consent.receipt"
    _description = "Face Processing Acknowledgment Receipt"
    _order = "acknowledged_at desc, id desc"
    _check_company_auto = True

    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict", check_company=True, index=True)
    company_id = fields.Many2one(related="employee_id.company_id", store=True, index=True)
    notice_version = fields.Char(required=True, readonly=True)
    acknowledged_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    recorded_by = fields.Many2one("res.users", required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_manager"):
            raise AccessError(_("Only an HR manager can record an enrollment acknowledgment."))
        for vals in vals_list:
            vals["recorded_by"] = self.env.user.id
            vals["acknowledged_at"] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Acknowledgment receipts are immutable."))

    def unlink(self):
        raise AccessError(_("Acknowledgment receipts cannot be removed from the audit trail."))
