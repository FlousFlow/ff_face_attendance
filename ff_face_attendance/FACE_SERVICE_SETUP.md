# Private face-service setup

The Odoo Apps module is a standard Odoo addon. It does not install or launch another executable. The optional face service is distributed separately so server administrators explicitly install it on self-hosted infrastructure.

## One-command Ubuntu installation

Supported: Ubuntu 22.04/24.04, systemd, native Odoo on the same host, root/sudo access, and internet access for package installation. Run this command on the Odoo server. It downloads a pinned service release, verifies its SHA-256, installs the service, and prints a one-time code.

```bash
sudo bash -c 'set -eu; d=$(mktemp -d); trap '\''rm -rf "$d"'\'' EXIT; f="$d/face-service.tar.gz"; curl -fsSL "https://github.com/FlousFlow/ff_face_attendance/releases/download/face-service-0.1.3/ff_face_ai_service-0.1.3.tar.gz" -o "$f"; printf "%s  %s\n" "91a6fc42f4f46f8d7f265496019b161871cccd345a960692f0e86ab1f84200b8" "$f" | sha256sum -c -; tar -xzf "$f" -C "$d"; bash "$d/ff_face_ai_service-0.1.3/deployment/install-local-face-service.sh"'
```

The command installs `ff-face-ai.service` as a non-root system service bound to `127.0.0.1:8787`; it generates TLS and service/gallery secrets, and does not overwrite an existing gallery key. Keep the printed pairing code private.

Then in Odoo open **Face Attendance → Connect Face Service** as an HR manager, paste the code, and wait for the health check. The face-attendance company policy remains disabled until HR enables it.

The service package and release source are available at [face-service-0.1.3](https://github.com/FlousFlow/ff_face_attendance/releases/tag/face-service-0.1.3). The face gallery and generated secrets remain on the customer's server. Port 8787 must not be exposed publicly.

## Other hosting

Odoo Online, Odoo.sh, containers, and other Linux distributions require a separately managed private service and a deployment profile compatible with that platform. The setup wizard in this addon pairs only with a service on the same host (`https://127.0.0.1:8787`).

## Manual/private-network configuration

For a different private service URL, authorized administrators must configure protected Odoo system parameters:

- `ff_face_attendance.service_url`
- `ff_face_attendance.service_request_secret`
- `ff_face_attendance.service_hmac_secret`
- `ff_face_attendance.pilot_admin_token`
- `ff_face_attendance.service_ready` (only after readiness and authenticated verification/deletion checks)

Back up the encrypted gallery and key separately. Attendance and optional landmark frames are processed in memory, not stored. HR revocation blocks matching and queues deletion. This supervised LBPH pilot is not robust anti-spoofing or guaranteed liveness; complete camera, privacy, and performance review before rollout.
