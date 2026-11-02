# Companion face service setup

The Face Attendance download now includes the companion `ff_face_ai_service` source and the verified YuNet detector under `deployment/`. The included installer supports self-hosted Ubuntu 22.04/24.04 when Odoo is installed directly on that same host. It creates a private non-root systemd service, binds it to loopback, generates distinct secrets and an encrypted-gallery key, verifies readiness, and prints a one-time pairing code.

## Guided same-server setup

1. Install the Odoo addon and update the Apps list.
2. On the same Ubuntu host, run `sudo bash /path/to/ff_face_attendance/deployment/install-local-face-service.sh`. The installer checks the OS and bundled YuNet SHA-256, installs the service dependencies, creates protected key/config files, generates local TLS, and starts `ff-face-ai.service`.
3. In Odoo, open **Face Attendance → Connect Face Service** as an HR manager and enter the one-time code shown at the end of installation. Odoo verifies the local `/health/ready` endpoint and stores the generated service credentials.
4. Enable the company face policy only after reviewing the pilot notice. The standard Badge/PIN kiosk remains available.

The setup code is local-only, accepted once, and deleted from service storage after pairing. Service configuration, gallery encryption keys, and gallery data stay on the customer's server. The installer refuses to overwrite an existing environment so it cannot accidentally replace an active gallery key.

## Support boundary

The guided installer targets Ubuntu 22.04/24.04, systemd, and a native Odoo process on the same host. It does not support Odoo Online, Odoo.sh, containers, or other Linux distributions. For those environments, deploy the service separately on a private network with HTTPS, then configure the protected Odoo parameters described below.

## Manual service configuration

Configure protected Odoo system parameters through an authorized administrative path:

- `ff_face_attendance.service_url`: private HTTPS base URL.
- `ff_face_attendance.service_request_secret`: exact value of `FF_ODOO_SHARED_SECRET`.
- `ff_face_attendance.service_hmac_secret`: exact value of `FF_RESULT_HMAC_SECRET`.
- `ff_face_attendance.pilot_admin_token`: exact value of `FF_PILOT_ADMIN_TOKEN`.
- `ff_face_attendance.service_ready`: readiness attestation set only after authenticated health, enrollment, verification, and deletion checks.

The systemd service binds to `127.0.0.1:8787`; do not expose this port publicly. Keep service secrets and encryption keys out of source control and logs.

## Back up and rotate

Enrollment crops are held in encrypted `gallery.enc`. Attendance verification frames and explicitly enabled face-alignment guide frames are processed in memory and are not persisted. Back up the gallery and encryption key separately in approved encrypted storage. For key rotation, configure `NEW_KEY,OLD_KEY`, restart once so the gallery is re-encrypted with the new primary key, restart with only `NEW_KEY`, then verify readiness. Do not remove the old key before migration succeeds. HR revocation requests deletion and Odoo retries until the service confirms it; keep the key available until deletion/rotation work is complete.

## Pilot limits

The service uses YuNet detection, OpenCV LBPH matching, and a basic head-turn prompt. It does not provide robust anti-spoofing or guaranteed liveness. Do not use it as sole evidence for unattended payroll or disciplinary decisions. Complete privacy/legal review, camera testing, and a representative performance validation before broad rollout.
