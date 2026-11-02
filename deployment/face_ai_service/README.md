# ff_face_ai_service

Private API boundary for the optional free face-attendance pilot. It does not include a production presentation-attack detection model. Keep it private and fail-closed.

## Run locally

```sh
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e '.[test,pilot]'
uvicorn ff_face_ai_service.main:app --host 127.0.0.1 --port 8787 --workers 1
```

Use a dedicated non-root Linux account and private network binding in deployment. Put secrets in `/etc/ff-face-ai/ff-face-ai.env` with mode `0600`; provision three distinct random secrets: two HMAC keys and an encryption key. The included unit is a starting systemd profile; validate resource limits against the target Linux distribution and measured workload before deployment.

## Model gate

The optional free pilot (`FF_PILOT_ENABLED=true`) uses OpenCV YuNet for detection, employee-provided samples with LBPH for matching, and a server-issued random left/right head-turn challenge per attendance attempt. The service checks the measured movement direction against the requested turn. This can reject a fixed prerecorded clip that does not match the fresh prompt, but it does not claim resistance to adaptive/re-recorded video, injection, masks, or deepfakes. A separate authenticated `/v1/landmarks` endpoint returns five normalized alignment points for an explicitly enabled kiosk guide; it processes the resized frame in memory and does not save it. The gallery holds biometric samples in encrypted `gallery.enc`; the encryption key is required to use, rotate, or verify deletion of that gallery. Verification and guide frames are processed in memory and are not written to disk.

The addon download includes the verified YuNet artifact under `deployment/models/face_detection_yunet_2023mar.onnx`; the guided installer copies it into the private service directory and sets `FF_PILOT_DETECTOR_PATH` automatically. Set `FF_PILOT_GALLERY_KEYS` to one or more comma-separated Fernet keys; the first key is the active encryption key. Generate and store a key without printing it in the terminal or shell history:

```sh
python - <<'PY'
import os
from cryptography.fernet import Fernet

path = "/etc/ff-face-ai/gallery-key.env"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as output:
    output.write("FF_PILOT_GALLERY_KEYS=" + Fernet.generate_key().decode() + "\n")
PY
```

Load this file through the service manager alongside the main environment file; do not commit it or paste its value into logs. Set `FF_PILOT_GALLERY_DIR` to a private directory, and `FF_NONCE_DB_PATH` to a private writable path on local persistent storage (SQLite WAL is used to share replay state between workers on that host).

Enroll with `POST /v1/pilot/enroll` using `X-FF-Admin-Token`, a `template_ref` matching the Odoo employee record, and 3–10 base64 JPEG/PNG samples. Verify with `POST /v1/verify` using 3–5 frames and `challenge: turn_left` or `turn_right`. Odoo accepts only signed results, and the employee must already be marked enrolled. `POST /v1/pilot/revoke` uses the same admin token and is idempotent.

### Back up and rotate the gallery key

Back up `gallery.enc` and the key separately to approved encrypted storage. Test restore access before deleting the source copy. For rotation, set `FF_PILOT_GALLERY_KEYS` to `NEW_KEY,OLD_KEY`, restart the service, and confirm readiness. The next gallery load decrypts with the old key and atomically re-encrypts with the new primary key. Restart once with only `NEW_KEY`, then confirm the service is ready and the gallery can be loaded. Keep no retired key after the rotation window. A lost key makes the gallery unreadable; deleting the key is not a substitute for the HR revocation endpoint.

This is only a supervised pilot. For any unattended or payroll-affecting deployment, independently review exact code and weight artifacts, provenance, data restrictions, commercial-use and redistribution terms, source version, and SHA-256, then complete independent PAD and replay testing. RGB cameras cannot guarantee rejection of all sophisticated attacks.
