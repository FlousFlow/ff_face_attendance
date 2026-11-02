# Companion face service setup

The Odoo addon does not bundle a web-facing AI process. Install the companion `ff_face_ai_service` package separately on a private host or private network, and keep it off the public internet. Do not enable biometric attendance until the service, TLS path, storage directory, key backup, and deletion flow have been verified.

## Install the service

1. Use Python 3.11 or later in a dedicated virtual environment and install the companion package with its pilot extras (`pip install -e '.[pilot]'`).
2. Obtain the YuNet artifact `face_detection_yunet_2023mar.onnx` from the OpenCV Zoo source recorded in `model-manifest.json`; verify the published SHA-256 in that manifest before use.
3. Copy `.env.example` to a protected environment file owned by the service account. Provision distinct random values for `FF_ODOO_SHARED_SECRET`, `FF_RESULT_HMAC_SECRET`, and `FF_PILOT_ADMIN_TOKEN`; match those values to Odoo parameters.
4. Generate `FF_PILOT_GALLERY_KEYS` directly into a mode-`0600` file without printing the key. Configure a private `FF_PILOT_GALLERY_DIR` and `FF_NONCE_DB_PATH` on persistent local storage.
5. Enable the free pilot with `FF_PILOT_ENABLED=true` only for the supervised evaluation. Configure `FF_PILOT_DETECTOR_PATH`, and keep `FF_MAX_CAPTURE_BYTES` consistent with the Odoo policy's maximum frame size.
6. Run the service under a dedicated non-root account behind TLS. Bind the app to a private interface, configure the proxy/host firewall to accept requests only from Odoo, and use the included systemd unit as a starting point.
7. Confirm `/health/ready` is healthy, then exercise the authenticated enrollment and revocation paths with a disposable test template before linking production employee data.

## Configure Odoo

Set the protected system parameters through Odoo's authorized configuration path:

- `ff_face_attendance.service_url`: the private HTTPS base URL reachable from the Odoo host.
- `ff_face_attendance.service_request_secret`: exact value of `FF_ODOO_SHARED_SECRET`.
- `ff_face_attendance.service_hmac_secret`: exact value of `FF_RESULT_HMAC_SECRET`.
- `ff_face_attendance.pilot_admin_token`: exact value of `FF_PILOT_ADMIN_TOKEN`.
- `ff_face_attendance.service_ready`: operator readiness attestation, set only after the end-to-end service and deletion checks.

Create the company policy with biometric mode disabled by default. Enable it only for the supervised pilot after verifying the paired kiosk. Keep Badge/PIN attendance configured as the alternative.

## Storage and key handling

Enrollment crops are held in encrypted `gallery.enc`. Attendance verification frames and explicitly enabled face-alignment guide frames are processed in memory and are not persisted. Back up the gallery and encryption key separately in approved encrypted storage. To rotate, configure `NEW_KEY,OLD_KEY`, restart once so the gallery re-encrypts with the new primary key, restart with only `NEW_KEY`, then verify readiness. Do not remove the old key before migration succeeds. HR revocation requests deletion and Odoo retries until the service confirms it; keep the key available until deletion/rotation work is complete.

## Pilot limits

The service uses YuNet detection, OpenCV LBPH matching, and a basic head-turn prompt. It does not provide robust anti-spoofing or guaranteed liveness. Do not use it as sole evidence for unattended payroll or disciplinary decisions. Complete a privacy/legal review and a representative camera/performance validation before any broader rollout.
