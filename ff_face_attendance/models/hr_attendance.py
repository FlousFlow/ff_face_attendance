from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    ff_face_device_id = fields.Many2one("ff.face.device", readonly=True, copy=False, ondelete="restrict", check_company=True, groups="ff_face_attendance.group_ff_face_user")
    ff_face_check_in_event_id = fields.Char(readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_user")
    ff_face_check_out_event_id = fields.Char(readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_user")
    ff_face_model_version = fields.Char(readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_user")
    ff_face_verification_method = fields.Selection([("passive", "Passive"), ("challenge", "Challenge")], readonly=True, copy=False, groups="ff_face_attendance.group_ff_face_user")

