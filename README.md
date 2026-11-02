# Flous Flow Face Attendance Service 0.1.3

Standalone Ubuntu installer payload for the Flous Flow Face Attendance Odoo 19 addon. Supported target: Ubuntu 22.04/24.04 with native Odoo on the same server, systemd, root access, and internet access for apt/Python package installation.

The installer binds the private API to localhost, generates local TLS and unique service/gallery secrets, creates a non-root system account, and prints a one-time Odoo pairing code. It refuses to overwrite an existing environment. Keep the generated gallery key backed up.

This is the free experimental YuNet/LBPH supervised pilot, not a strong anti-spoofing service. Do not expose port 8787 publicly.
