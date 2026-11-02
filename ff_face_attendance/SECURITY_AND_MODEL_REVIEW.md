# Security, model, and privacy review

## Scope

The free YuNet/LBPH face matcher and basic head-turn challenge are retained as the user's chosen supervised pilot. They are not presented as strong liveness, PAD, or protection against photos, replayed video, masks, or camera injection. Keep the normal Odoo Badge/PIN route available. Production use for unattended attendance, payroll evidence, or disciplinary decisions requires separate evaluation and approval.

## Implemented controls

- Kiosk credentials are random and stored in Odoo as SHA-256 digests; credentials are rotated by HR.
- Devices, policies, exceptions, attempts, consent receipts, and employees are constrained by company where applicable.
- Verification sessions are short-lived, tied to a device, and consumed before the external service call. Per-device advisory locking limits issuance to 20 sessions per minute.
- Odoo sends timestamped HMAC-authenticated requests to the private service and validates signed results, nonce, issue time, event ID, model version, and opaque template reference.
- Matching resolves identity on the server within the kiosk company. Client employee IDs are only an expected-identity check.
- An already open attendance interval is reviewed through the HR exception flow; duplicate check-ins and check-outs are blocked.
- Camera preview stays in the browser. Enrollment and attendance samples are transmitted only after an explicit enrollment or attendance action. Attendance frames are transient in the AI service and are not saved.
- The five-point alignment overlay is a separate opt-in: the kiosk explains that it sends one resized still per second to the private service while enabled. The service returns normalized YuNet eye, nose, and mouth-corner coordinates, processes frames in memory, and stores none. The overlay turns off when consent is unchecked or the user clicks Hide.
- Enrollment crops are stored in the pilot's encrypted gallery using a deployment-provided Fernet key. HR revocation disables the template immediately, calls the authenticated deletion API, and retries through an Odoo cron until deletion is confirmed.
- HR enrollment records an immutable acknowledgment receipt with notice version, timestamp, employee, and recording HR user. The receipt is an audit record, not proof of legal consent.
- AI service request nonces are claimed in a shared local SQLite database so replay checks work across service workers on the same host.

## Known limits and required review

- YuNet detects faces; OpenCV LBPH matches employee-provided samples. The head-turn challenge is basic and can be imitated. The system has no independently validated PAD or injection defense.
- Encryption at rest depends on protecting and backing up `FF_PILOT_GALLERY_KEYS`. Loss of the key makes the gallery unreadable. Do not delete/rotate away keys before orderly revocation and rotation steps complete.
- Verification event metadata and immutable acknowledgment receipts remain in Odoo; define access and retention periods. Service logs must not contain camera frames or secrets.
- The camera, browser, network path, service capacity, employee-wide match accuracy, restore procedures, and production backup controls need testing in the target deployment.
- Biometric processing and employee acknowledgment require jurisdiction-specific privacy/legal review, including purpose, lawful basis, employee choice, notice, retention, access, controller/processor roles, and transfers. The module does not claim legal compliance.
- Odoo Apps review and acceptance are external gates. Do not claim the listing is accepted until submitted and approved.

## Model and licensing notes

- YuNet is a detection-only artifact. The selected OpenCV Zoo artifact and its checksum are recorded in `ff_face_ai_service/model-manifest.json`; re-verify the exact upstream terms and checksum for each release.
- OpenCV LBPH comes from OpenCV-contrib. Verify the exact OpenCV version and dependency licenses in the release SBOM.
- No SFace identity model or third-party anti-spoofing model is included. No claim about their provenance or license is made here.

## Evidence

Focused AI service tests cover encrypted gallery persistence/reload/rotation, legacy migration, template deletion, authenticated deletion, and replay protection. Odoo tests cover module install/upgrade, enrollment acknowledgment audit immutability, revocation retry, camera preview not uploading, public kiosk rendering, and fail-closed device/session behavior. Automated tests do not establish real-world model quality, security certification, App Store acceptance, or legal compliance.
