# Release candidate checklist — 19.0.0.2.4

## Included

- Core Odoo 19 addon and its standard manifest dependencies (`hr`, `hr_attendance`).
- Companion face API source, its Python dependency manifest, tests, systemd unit, and the YuNet detector with a recorded SHA-256 and MIT notice. These deployment files are inside the addon download under `deployment/`; they are not Odoo modules.
- Ubuntu 22.04/24.04 same-host installer creates a non-root loopback service, distinct keys, local TLS, and a one-time setup code. An HR-manager Odoo wizard pairs the local service and verifies readiness.
- HR can enroll/revoke faces, audit acknowledgment, and use randomized directional prompts. Arabic and English kiosk copy, icon, screenshot, setup documentation, and privacy disclosures are included.

## Previously verified before the 2.4 setup changes

- Odoo 19 focused suite: 13/13 passed on disposable databases for version 19.0.0.2.3.
- Companion face service suite: 18 tests passed for version 0.1.2 (the 0.1.3 local pairing endpoints are not yet verified).
- Arabic/English kiosk rendering, RTL, and dynamic status localization were verified in the local Odoo browser.

## Not yet verified for 2.4

- Odoo accepted the 2.4 module upgrade on the local disposable database. Translation occurrence syntax and explicit wizard model naming were corrected after inspecting that upgrade log. The full Odoo test suite has not been rerun for 2.4.
- The local Linux installer has not been executed on Ubuntu 22.04/24.04. Its systemd, certificate, dependency installation, one-time pairing, and key-preservation behavior still require a disposable Linux host run.
- The upgraded service pairing endpoints and 0.1.3 service suite have not been exercised.
- Real-person camera enrollment/check-in/check-out, landmark overlay, direction calibration, representative load, and host performance remain NOT RUN.
- YuNet/LBPH with a randomized head-turn remains a supervised pilot, not strong anti-spoofing/PAD. Do not rely on it alone for payroll or disciplinary decisions.
- Jurisdiction-specific privacy/legal approval, lawful basis, employee notice, and retention policy are deployment responsibilities, not established by software tests.
- Source is in public repository `FlousFlow/ff_face_attendance`, Odoo branch `19.0`. This version has not been submitted to or accepted by Odoo Apps.

## Installer support boundary

The bundled installer supports native Odoo on the same Ubuntu 22.04/24.04 systemd host. It does not support Odoo Online, Odoo.sh, containers, or other Linux distributions. Those deployments must host the service separately on a private network and configure the protected Odoo system parameters manually.

The installer refuses to overwrite an existing service environment, so rerunning it cannot replace the gallery encryption key. Keep backups of the database, filestore, encrypted gallery, and gallery key. Never commit credentials, employee captures, or gallery data.
