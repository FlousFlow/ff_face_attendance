import re

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class FaceDevicePinWizard(models.TransientModel):
    _name = "ff.face.device.pin.wizard"
    _description = "Set Face Attendance Kiosk PIN"

    device_id = fields.Many2one("ff.face.device", required=True, readonly=True)
    pin = fields.Char(string="Kiosk PIN", required=True)
    pin_confirmation = fields.Char(string="Confirm Kiosk PIN", required=True)

    def action_set_pin(self):
        self.ensure_one()
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_manager"):
            raise AccessError(_("Only an HR manager can set the kiosk PIN."))
        if not re.fullmatch(r"[0-9]{4,12}", self.pin or ""):
            raise ValidationError(_("The kiosk PIN must contain 4 to 12 digits."))
        if self.pin != self.pin_confirmation:
            raise ValidationError(_("The kiosk PIN confirmation does not match."))
        self.device_id.sudo().write({"kiosk_pin_hash": self.device_id._hash_kiosk_pin(self.pin)})
        return {"type": "ir.actions.act_window_close"}
