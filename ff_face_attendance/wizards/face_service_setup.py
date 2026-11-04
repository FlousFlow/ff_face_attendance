import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class FaceServiceSetupWizard(models.TransientModel):
    _name = "face.service.setup.wizard"
    _description = "Face Service Setup Wizard"

    pairing_code = fields.Char(string="One-time setup code")
    service_connected = fields.Boolean(
        compute="_compute_service_status",
        string="Service connected",
    )
    service_url = fields.Char(compute="_compute_service_status", string="Service URL")

    @api.depends()
    def _compute_service_status(self):
        params = self.env["ir.config_parameter"].sudo()
        service_url = params.get_param("ff_face_attendance.service_url") or ""
        service_ready = params.get_param("ff_face_attendance.service_ready") == "true"
        request_secret = params.get_param("ff_face_attendance.service_request_secret")
        hmac_secret = params.get_param("ff_face_attendance.service_hmac_secret")
        connected = bool(service_url and service_ready and request_secret and hmac_secret)
        for wizard in self:
            wizard.service_connected = connected
            wizard.service_url = service_url

    def action_connect(self):
        self.ensure_one()
        if not self.env.user.has_group("ff_face_attendance.group_ff_face_manager"):
            raise AccessError(_("Only an HR manager can connect the face service."))
        if self.service_connected:
            raise UserError(_("The face service is already connected and ready."))
        code = (self.pairing_code or "").strip()
        if len(code) < 24 or len(code) > 128:
            raise UserError(_("The setup code is invalid. Run the server installer again to generate a new code."))

        service_url = "https://127.0.0.1:8787"
        try:
            response = requests.post(
                service_url + "/v1/setup/pair",
                json={"pairing_code": code},
                timeout=(2, 8),
                verify=False,
            )
            if response.status_code != 200:
                raise UserError(_("The local face service rejected the setup code. Check that the server installer completed and the code is current."))
            credentials = response.json()
            request_secret = credentials.get("service_request_secret")
            result_secret = credentials.get("service_hmac_secret")
            admin_token = credentials.get("pilot_admin_token")
            if not all(isinstance(value, str) and len(value) >= 32 for value in (request_secret, result_secret, admin_token)):
                raise UserError(_("The local face service returned an invalid setup response."))

            health = requests.get(service_url + "/health/ready", timeout=(2, 8), verify=False)
            if health.status_code != 200 or health.json().get("status") != "ready":
                raise UserError(_("The face service is installed but not ready. Check its model and storage, then reconnect."))

            params = self.env["ir.config_parameter"].sudo()
            values = {
                "ff_face_attendance.service_url": service_url,
                "ff_face_attendance.service_request_secret": request_secret,
                "ff_face_attendance.service_hmac_secret": result_secret,
                "ff_face_attendance.pilot_admin_token": admin_token,
                "ff_face_attendance.allow_insecure_local_service": "true",
                "ff_face_attendance.service_ready": "true",
            }
            for key, value in values.items():
                params.set_param(key, value)

            completed = requests.post(
                service_url + "/v1/setup/complete",
                json={"pairing_code": code},
                timeout=(2, 8),
                verify=False,
            )
            if completed.status_code != 200 or completed.json().get("result") != "paired":
                for key in values:
                    params.set_param(key, False)
                raise UserError(_("Odoo could not finish pairing with the local face service. Retry with the same setup code."))
        except requests.RequestException as exc:
            raise UserError(_("Odoo could not reach the face service on this server. Confirm the installer is running on the same Linux server, then retry.")) from exc

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Face service connected"),
                "message": _("The local service is ready. Face attendance remains off until an HR manager enables the company policy."),
                "type": "success",
                "sticky": False,
            },
        }
