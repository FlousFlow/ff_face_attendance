# Face Attendance for Odoo 19 Community

Adds an opt-in, supervised face-attendance pilot around native `hr.attendance`, plus HR device, policy, exception, verification-audit, acknowledgment, and revocation workflows. Requires Odoo 19 Community with `hr` and `hr_attendance`.

## What happens to camera data

- Opening the camera shows a browser-local preview. The addon does not upload a frame during preview by default.
- The optional face-point guide requires an explicit checkbox and button click. While enabled, it sends at most one resized still frame per second to the configured private face service, which returns YuNet's five alignment points. Frames are processed in memory, are not stored, and sending stops when the guide is turned off. The guide is for alignment only; it does not identify the employee.
- When an employee explicitly starts enrollment or Check in/Check out, the kiosk captures only the prompted 3–5 frames and sends them to the separately deployed private face service over HTTPS.
- Enrollment face crops are stored by that service in an encrypted gallery. The encryption key is supplied by the operator and must be backed up and rotated using the service instructions.
- Attendance verification frames are decoded and processed in memory; the service does not write them to disk. Odoo stores attendance events and verification metadata, not those frames.
- Odoo records the acknowledgment version, employee, HR operator, and timestamp. HR revocation blocks matching immediately, requests deletion at the service, and retries every five minutes until confirmed.
- Audit receipts are immutable and retained in Odoo. Define a retention policy for those receipts and attendance/audit records before deployment.

The kiosk exposes the company's configured standard Odoo attendance kiosk as an alternative. Do not require face enrollment as the only attendance method.

## Supervised pilot limits

The optional free service uses YuNet face detection, OpenCV LBPH matching, and a server-issued random left/right head-turn challenge for each attendance attempt. The service checks the direction of measured movement against that challenge, so a prerecorded clip with the wrong turn should fail. This is not strong liveness or presentation-attack detection and does not guarantee resistance to adaptive/re-recorded video, masks, or camera injection. Keep a human-supervised pilot; do not use it as sole evidence for payroll or disciplinary decisions. Face verification is blocked by default until an HR manager enables a ready service and company policy.

## Install and update

1. Back up the database and filestore.
2. Add this module directory to `addons_path` and update the Apps list.
3. Install **Face Attendance** in a test database first; test enrollment, attendance check-in/out, revocation, and the native attendance alternative.
4. Configure the private face service and protected Odoo system parameters below. Keep the service private and require HTTPS.
5. Create a company policy and kiosk device as an HR manager. Rotate the one-time kiosk credential, open `/ff_face_attendance/kiosk` over HTTPS on the kiosk, and pair it once.

This addon has no Enterprise dependency and does not require PayrollFlow.

## Service configuration

Configure protected Odoo system parameters:

- `ff_face_attendance.service_url`: private HTTPS base URL.
- `ff_face_attendance.service_request_secret`: same value as `FF_ODOO_SHARED_SECRET`.
- `ff_face_attendance.service_hmac_secret`: same value as `FF_RESULT_HMAC_SECRET`.
- `ff_face_attendance.pilot_admin_token`: same value as `FF_PILOT_ADMIN_TOKEN`.
- `ff_face_attendance.service_ready`: operator-maintained readiness attestation.

For local TLS development only, `ff_face_attendance.allow_insecure_local_service=true` accepts the local self-signed test certificate. Never enable it for a deployed service.

## HR enrollment and revocation

From the employee record's **Face Attendance** tab, HR selects **Open Enrollment Kiosk**. The paired kiosk opens with that employee selected. An HR manager asks the employee to review the notice and check its acknowledgment box, then follows the guided camera prompts. Re-enrollment is HR-only. The endpoint requires an authenticated Odoo HR manager and same-origin browser request; the loopback public endpoint is restricted to local demo mode.

From the employee's **Face Attendance** tab, HR can inspect the enrollment state and immutable acknowledgment history. **Revoke Enrollment** immediately sets `Revocation Pending`; that employee can no longer match. Odoo retries template deletion from the service. After confirmed deletion, Odoo clears the external template reference and enrollment metadata. Keep the service key available through this process; deleting the key first makes encrypted samples unreadable but prevents verified deletion and orderly rotation.

## Optional service setup

See [`FACE_SERVICE_SETUP.md`](FACE_SERVICE_SETUP.md) for companion-service installation, model artifact verification, encrypted gallery provisioning, backup, and key rotation. The service is disabled by default. If enabling the free pilot, use only for a supervised evaluation and preserve the Badge/PIN alternative.

## Privacy and release gates

This module provides technical controls; it does not determine a lawful basis, establish valid employee consent, or provide legal compliance. Biometric-data processing in employment requires a privacy/legal review for the deployment jurisdiction, purpose, notice, access, retention, deletion, and employee alternatives before rollout. The app listing must disclose that camera samples are sent to a separately operated private service.

## Local verification evidence

The module was upgraded and its focused Odoo 19 suite passed on a disposable test database. The companion service tests also pass. These checks do not validate the customer deployment, production camera hardware, face-match accuracy across a workforce, load, or official Odoo Apps acceptance.


## دليل سريع بالعربية

### للموظف

1. افتح رابط كشك الحضور الذي وفرته الموارد البشرية، واختر اسمك من قائمة الموظفين ثم اضغط **متابعة**.
2. اسمح للمتصفح باستخدام الكاميرا، واجعل وجهك كاملًا داخل الإطار وفي إضاءة جيدة.
3. عند التسجيل لأول مرة، يجب أن يساعدك مسؤول الموارد البشرية في التسجيل، بعد قراءة إشعار معالجة بيانات الوجه والإقرار به. اتبع التعليمات الظاهرة: انظر للكاميرا مباشرة ثم أدر رأسك إلى الاتجاه الذي يظهر لك.
4. لتسجيل الحضور اضغط **تسجيل الحضور**؛ وعند نهاية الوردية اضغط **تسجيل الانصراف**. إذا كنت مسجل حضور بالفعل، سيمنع النظام تسجيل حضور مكرر ويوجهك للانصراف.
5. إذا تعذر التحقق، استخدم كشك أودو القياسي بالبطاقة أو الرقم السري، أو تواصل مع الموارد البشرية.

### لمسؤول الموارد البشرية

- من سجل الموظف افتح تبويب **الحضور بالوجه** ثم اضغط **فتح شاشة تسجيل الوجه**. هذه هي شاشة تسجيل الوجه الأول وإعادة التسجيل؛ أزرار التسجيل والاستبدال محمية بصلاحية مدير الموارد البشرية.
- قبل الاستخدام، اربط جهاز الكشك واضبط سياسة الشركة وخدمة الوجه. لا تفعّل التجربة إلا بعد التأكد من إبقاء طريقة البطاقة أو الرقم السري متاحة.
- راجع حالة التسجيل وسجل الإقرار ومحاولات التحقق والاستثناءات من قوائم **الحضور بالوجه**. إلغاء التسجيل يمنع المطابقة فورًا ويطلب حذف الصور من الخدمة.
- نقاط المحاذاة اختيارية: لا تعمل إلا بعد تحديد مربع الموافقة والضغط على إظهار النقاط. تُرسل صورة صغيرة كل ثانية للخدمة الخاصة ولا تُحفظ، وهي دليل لوضع الوجه وليست مطابقة هوية.

> هذه نسخة تجريبية خاضعة للإشراف. التحدي العشوائي لحركة الرأس وLBPH لا يوفّران كشف تزوير قويًا، فلا تعتمد عليهما وحدهما للرواتب أو الإجراءات التأديبية. راجع متطلبات الخصوصية والاحتفاظ بالبيانات في بلدك قبل التشغيل.

لإظهار الواجهة العربية، فعّل لغة **Arabic / العربية** من إعدادات أودو أولًا، ثم اختر **العربية** من أعلى شاشة الكشك. إذا لم تظهر اللغة في الاختيار، فعّلها من إعدادات اللغات ثم حدّث التطبيق.
