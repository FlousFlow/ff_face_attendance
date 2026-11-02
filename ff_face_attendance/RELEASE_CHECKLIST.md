# Odoo 19.0.0.2.5 release checklist

## Odoo Apps branch contents

- One installable Odoo 19 addon at repository root; manifest dependencies are Community `hr` and `hr_attendance`.
- No face-service source, shell installer, external dependencies installer, or service launcher is in branch `19.0`. The Odoo addon does not download, install, or launch separate executable code.
- The service is a separately versioned Linux deployment package. The module listing and `FACE_SERVICE_SETUP.md` provide a single checksum-verified command for an authorized server administrator on supported Ubuntu hosts.
- Face attendance stays opt-in and policy-disabled until HR pairs and enables it.

## Verification evidence

- Odoo 19 focused suite: 13/13 passed on disposable databases for 19.0.0.2.3.
- Face service suite: 18 tests passed for 0.1.2. The 0.1.3 installer/pair endpoints remain unverified on Ubuntu.
- Odoo accepted the 2.4 setup-wizard upgrade on the local disposable database. Version 2.5 changes packaging/docs, but the complete test suite was not rerun for 2.5.
- Ubuntu package installation, service start, one-time pairing, real camera, performance, and legal/privacy review are NOT RUN/NOT ESTABLISHED.
- Odoo Apps submission and acceptance are NOT DONE. This layout avoids automatic external executable installation from the module; final store review remains authoritative.

## Deployment scope and limitations

The one-command installer supports native Odoo on Ubuntu 22.04/24.04 with systemd and internet access. Odoo Online, Odoo.sh, containers, and other distributions require another deployment profile. Keep Badge/PIN available. YuNet/LBPH plus random head-turn is a supervised pilot, not strong anti-spoofing/PAD. Never commit service secrets, employee captures, gallery data, or private keys.
