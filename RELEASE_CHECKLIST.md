# Release candidate checklist — 19.0.0.2.3

## Verified

- Fresh Odoo 19 Community install and module upgrade passed on disposable databases.
- Focused Odoo suite: 13 post-install tests passed after the 19.0.0.2.3 changes.
- Arabic and English kiosk modes rendered in the browser; Arabic RTL and dynamic status localization were verified. Arabic must be activated in the target database for the Arabic choice to work.
- Face service suite: 18 tests passed, including directional challenge checks, normalized five-point output, and rejection of unsigned landmark-frame requests.
- Python compilation/AST, JavaScript syntax, XML parsing, manifest metadata, translation catalog, and model-manifest checks passed.
- HR can open an employee directly into the enrollment kiosk. Production enrollment requires an HR manager, same-origin request, and versioned employee acknowledgment. Re-enrollment reuses the same service template.
- Each attendance attempt receives a cryptographically random, server-issued left/right challenge persisted in its one-use session. Odoo rejects a client direction that does not match the session, and the face service checks signed movement direction.
- Camera preview stays local by default. The explicitly enabled alignment guide can send one resized frame (max 640px wide) per second to the private service; frames are processed in memory and not stored. Attendance sends up to five transient frames.
- The alignment overlay draws YuNet's five eye/nose/mouth-corner landmarks for capture guidance, not identity matching.
- Landmark snapshots require the opt-in, a paired kiosk, same-origin request, rate limits, and signed service requests.
- Revocation immediately blocks matching and retries authenticated service deletion until confirmed.
- Odoo Apps metadata, screenshot, 512×512 icon, Arabic catalog, Arabic user guide, English setup/security documentation, and privacy disclosures are included.

## Not established

- A real camera enrollment/check-in/check-out or landmark-overlay trial requires a human and the target camera/browser and has not been completed for this release.
- Direction calibration against mirrored/unmirrored target-camera frames remains to be confirmed.
- No representative host, employee population, or concurrent-kiosk performance benchmark has been run.
- YuNet/LBPH and the randomized head-turn challenge remain a supervised pilot; they do not provide strong anti-spoofing and must not be the sole basis for unattended payroll or disciplinary decisions.
- Jurisdiction-specific privacy/legal approval, lawful-basis review, employee notice, and retention policy are deployment responsibilities and have not been established by software tests.
- The source is maintained in `FlousFlow/ff_face_attendance`, branch `19.0`. It has not been submitted to or accepted by Odoo Apps.

## Deployment notes

Create deployment secrets and keys on the target host. Never commit service credentials, encryption keys, employee captures, or gallery data. Keep the optional face service private and configure it only after following `FACE_SERVICE_SETUP.md`. New installations keep biometric policies disabled until an authorized operator configures the service and enables the supervised pilot.

Arabic localization uses Odoo's JavaScript translation helper and the module's `i18n/ar.po` catalog.
