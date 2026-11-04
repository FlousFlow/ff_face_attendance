/** @odoo-module **/

import { appTranslateFn, translationIsReady } from "@web/core/l10n/translation";

const tr = (message, ...substitutions) => {
    try {
        return String(appTranslateFn(message, "ff_face_attendance", ...substitutions));
    } catch {
        // Public pages can run this callback before Odoo finishes loading locale data.
        return message;
    }
};

const initializeFaceKiosk = () => {
    const status = document.getElementById("ff-kiosk-status");
    if (!status || status.dataset.ffInitialized === "1") return Boolean(status);
    status.dataset.ffInitialized = "1";
    const byId = (id) => document.getElementById(id);
    const facePanel = byId("ff-face-panel");
    const openFaceButton = byId("ff-face-open");
    const closeFaceButton = byId("ff-face-close");
    const setFacePanelVisible = (visible) => {
        facePanel?.classList.toggle("d-none", !visible);
        if (visible) byId("ff-device-credential")?.focus();
    };
    openFaceButton?.addEventListener("click", () => setFacePanelVisible(true));
    closeFaceButton?.addEventListener("click", () => setFacePanelVisible(false));
    const localDemo = status.closest("main")?.dataset.localDemo === "true";
    const enrollmentOnly = status.closest("main")?.dataset.enrollmentOnly === "true";
    const adminMode = status.closest("main")?.dataset.adminMode === "true";
    const hasEmployeeAccess = () => !kioskLocked && (paired || enrollmentOnly);
    translationIsReady.then(() => {
        const sourceMessage = status.dataset.sourceMessage;
        if (sourceMessage) status.textContent = tr(sourceMessage);
    });
    const say = (message, kind = "info") => {
        status.className = `mt-3 alert alert-${kind}`;
        status.dataset.sourceMessage = message;
        status.textContent = tr(message);
    };
    let audioContext = null;
    const primeAudio = () => {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        try {
            audioContext ||= new AudioContextClass();
            if (audioContext.state === "suspended") audioContext.resume();
        } catch (error) {
            audioContext = null;
        }
    };
    const playCue = (frequency = 660, duration = 0.2) => {
        if (!audioContext || audioContext.state === "closed") return;
        try {
            const oscillator = audioContext.createOscillator();
            const gain = audioContext.createGain();
            oscillator.frequency.value = frequency;
            gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.95, audioContext.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + duration);
            oscillator.connect(gain);
            gain.connect(audioContext.destination);
            oscillator.start();
            oscillator.stop(audioContext.currentTime + duration);
        } catch (error) {
            // Audio is an enhancement; visible instructions remain available.
        }
    };
    const beep = (frequency = 660) => playCue(frequency);
    let stream = null;
    let paired = false;
    let currentEmployee = null;
    let selectedEmployeeId = null;
    let employeeSearchTimer = null;
    let employeeSearchController = null;
    let landmarkGuideActive = false;
    let landmarkRequestInFlight = false;
    let landmarkTimer = null;
    let kioskLocked = false;
    const setStage = (stage) => {
        const stagePin = byId("ff-stage-pin");
        const stageEmployee = byId("ff-stage-employee");
        const stageAttendance = byId("ff-stage-attendance");
        stagePin?.classList.toggle("d-none", stage !== "pin");
        stageEmployee?.classList.toggle("d-none", stage === "pin");
        stageAttendance?.classList.toggle("d-none", stage !== "attendance");
        byId("ff-kiosk-information")?.classList.toggle("d-none", stage === "pin");
        const descriptions = {
            pin: "Enter the PIN configured by HR to unlock this kiosk.",
            employee: "Search for and select the employee who is attending.",
            attendance: "Choose Check in or Check out, then follow the camera prompt.",
        };
        const description = byId("ff-kiosk-description");
        if (description && descriptions[stage]) description.textContent = tr(descriptions[stage]);
        byId("ff-employee-lookup")?.classList.toggle("d-none", stage !== "employee");
        for (const indicator of document.querySelectorAll("[data-stage-indicator]")) {
            const indicatorStage = indicator.dataset.stageIndicator;
            const active = indicatorStage === stage;
            const complete = ["employee", "attendance"].includes(stage)
                && indicatorStage === "pin";
            indicator.classList.toggle("active", active);
            indicator.classList.toggle("complete", complete || (stage === "attendance" && indicatorStage === "employee"));
        }
    };
    const setKioskLocked = (locked, message = "") => {
        kioskLocked = locked;
        byId("ff-kiosk-lock")?.classList.toggle("d-none", !locked);
        if (message) {
            const pinStatus = byId("ff-kiosk-pin-status");
            if (pinStatus) pinStatus.textContent = message;
        }
        for (const id of ["ff-kiosk-pin", "ff-kiosk-unlock"]) byId(id)?.toggleAttribute("disabled", !locked);
        for (const id of ["ff-camera-start", "ff-employee-search", "ff-employee-continue"]) byId(id)?.toggleAttribute("disabled", locked);
        if (locked) {
            byId("ff-check-in")?.toggleAttribute("disabled", true);
            byId("ff-check-out")?.toggleAttribute("disabled", true);
            setStage("pin");
        } else if (!selectedEmployeeId) {
            setStage("employee");
        }
    };
    setKioskLocked(!adminMode);
    byId("ff-kiosk-unlock")?.addEventListener("click", async () => {
        const pinInput = byId("ff-kiosk-pin");
        const pinStatus = byId("ff-kiosk-pin-status");
        const pin = pinInput?.value.trim() || "";
        if (!/^[0-9]{4,12}$/.test(pin)) {
            if (pinStatus) pinStatus.textContent = tr("Enter the 4–12 digit kiosk PIN.");
            return;
        }
        try {
            const response = await fetch("/ff_face_attendance/device/pin/verify", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ pin }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "invalid_kiosk_pin");
            paired = true;
            pinInput.value = "";
            setKioskLocked(false);
            setAttendanceReady();
            say("Kiosk unlocked. Search and select the employee name to continue.", "success");
            if (requestedEmployeeId) await loadEmployeeStatus(requestedEmployeeId);
        } catch (error) {
            if (pinStatus) pinStatus.textContent = tr("Invalid kiosk PIN. Try again or ask HR to reset it.");
        }
    });
    const requestedEmployeeId = Number(
        status.closest("main")?.dataset.requestedEmployee
        || new URLSearchParams(window.location.search).get("employee_id")
        || 0
    );
    const employeeSearch = byId("ff-employee-search");
    const employeeOptions = byId("ff-employee-options");
    const clearEmployeeSelection = () => {
        selectedEmployeeId = null;
        currentEmployee = null;
        byId("ff-employee-continue").disabled = true;
        byId("ff-employee-name").classList.add("d-none");
        byId("ff-change-employee").classList.add("d-none");
        byId("ff-first-time-enrollment").classList.add("d-none");
        byId("ff-enrolled-hint").classList.add("d-none");
        byId("ff-revocation-pending").classList.add("d-none");
        byId("ff-reenroll-controls").classList.add("d-none");
        byId("ff-check-in").disabled = true;
        byId("ff-check-out").disabled = true;
        if (!kioskLocked) setStage("employee");
    };
    const hideEmployeeOptions = () => {
        employeeOptions.classList.add("d-none");
        employeeOptions.replaceChildren();
        employeeSearch.setAttribute("aria-expanded", "false");
    };
    const showEmployeeOptions = (employees) => {
        employeeOptions.replaceChildren();
        if (!employees.length) {
            const empty = document.createElement("div");
            empty.className = "list-group-item text-muted";
            empty.textContent = tr("No matching employees found.");
            employeeOptions.appendChild(empty);
        }
        for (const employee of employees) {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "list-group-item list-group-item-action";
            option.setAttribute("role", "option");
            option.textContent = employee.department ? `${employee.name} — ${employee.department}` : employee.name;
            option.addEventListener("click", () => {
                employeeSearch.value = employee.name;
                hideEmployeeOptions();
                clearEmployeeSelection();
                selectedEmployeeId = employee.id;
                byId("ff-employee-continue").disabled = !hasEmployeeAccess();
                employeeSearch.setAttribute("aria-activedescendant", "");
            });
            employeeOptions.appendChild(option);
        }
        employeeOptions.classList.remove("d-none");
        employeeSearch.setAttribute("aria-expanded", "true");
    };
    employeeSearch.addEventListener("input", () => {
        clearEmployeeSelection();
        if (employeeSearchTimer) window.clearTimeout(employeeSearchTimer);
        if (employeeSearchController) employeeSearchController.abort();
        const query = employeeSearch.value.trim();
        if (!query || !hasEmployeeAccess()) return hideEmployeeOptions();
        employeeSearchTimer = window.setTimeout(async () => {
            employeeSearchController = new AbortController();
            try {
                const response = await fetch("/ff_face_attendance/employee/search", {
                    method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                    signal: employeeSearchController.signal, body: JSON.stringify({ query }),
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "employee_search_failed");
                showEmployeeOptions(result.employees || []);
            } catch (error) {
                if (error.name !== "AbortError") say("Could not search employees. Check the kiosk connection and retry.", "warning");
            }
        }, 250);
    });
    employeeSearch.addEventListener("keydown", (event) => {
        if (event.key === "Escape") hideEmployeeOptions();
        if (event.key === "Enter" && !employeeOptions.classList.contains("d-none")) {
            event.preventDefault();
            employeeOptions.querySelector("button")?.click();
        }
    });
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".ff-employee-lookup")) hideEmployeeOptions();
    });
    const setAttendanceReady = () => {
        const ready = Boolean(!enrollmentOnly && paired && stream && currentEmployee?.enrolled);
        byId("ff-check-in").disabled = !ready || Boolean(currentEmployee?.checked_in);
        byId("ff-check-out").disabled = !ready || !currentEmployee?.checked_in;
        if (currentEmployee?.checked_in) {
            byId("ff-enrolled-hint-text").textContent = tr("You are already checked in. Use Check out when your shift ends.");
        }
    };

    const loadEmployeeStatus = async (employeeId) => {
        if (!employeeId) return say("Search for and select your name first.", "warning");
        if (!hasEmployeeAccess()) return say("Ask HR to connect this kiosk first.", "warning");
        selectedEmployeeId = employeeId;
        try {
            const response = await fetch("/ff_face_attendance/employee/status", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ employee_id: employeeId }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "employee_lookup_failed");
            currentEmployee = result;
            setStage("attendance");
            byId("ff-employee-lookup").classList.add("d-none");
            byId("ff-employee-name").textContent = tr("Hello, %s").replace("%s", result.employee_name);
            byId("ff-employee-name").classList.remove("d-none");
            byId("ff-change-employee").classList.remove("d-none");
            const revocationPending = result.enrollment_status === "revocation_pending";
            byId("ff-first-time-enrollment").classList.toggle("d-none", result.enrolled || revocationPending);
            byId("ff-enrollment-consent-wrap").classList.toggle("d-none", !result.can_register);
            byId("ff-pilot-enroll").classList.toggle("d-none", !result.can_register);
            byId("ff-hr-enrollment-hint").classList.toggle("d-none", result.can_register || revocationPending);
            byId("ff-revocation-pending").classList.toggle("d-none", !revocationPending);
            byId("ff-enrolled-hint").classList.toggle("d-none", !result.enrolled);
            byId("ff-reenroll-controls").classList.toggle("d-none", !(result.enrolled && result.can_enroll));
            if (!stream) byId("ff-camera-start").click();
            setAttendanceReady();
            say(revocationPending ? "Face-data deletion is pending. Use Badge/PIN meanwhile." : result.checked_in ? "You are already checked in. Check in is disabled; use Check out when your shift ends." : result.enrolled ? "Face registered. You can check in." : result.can_register ? "Your face is not registered yet. HR can register it below." : result.can_enroll ? "Face enrollment is not available for this employee yet." : "Your face is not registered yet. Ask HR to register it before using face attendance.", revocationPending ? "warning" : result.checked_in ? "success" : "info");
        } catch (error) {
            say(error.message === "employee_not_found" ? "Employee not found in this company." : "Could not check employee registration. Try again or contact HR.", "warning");
        }
    };
    byId("ff-employee-continue").addEventListener("click", async () => {
        if (!selectedEmployeeId) return say("Search for and select your name first.", "warning");
        await loadEmployeeStatus(selectedEmployeeId);
    });
    byId("ff-change-employee")?.addEventListener("click", () => {
        clearEmployeeSelection();
        employeeSearch.value = "";
        employeeSearch.focus();
    });

    const pairKiosk = async (local = false) => {
        try {
            say(local ? "Connecting this local kiosk…" : "Securing this kiosk…", "info");
            const options = {
                method: "POST", credentials: "same-origin",
                headers: local ? {} : { Authorization: `Bearer ${byId("ff-device-credential").value.trim()}` },
            };
            if (!local && !byId("ff-device-credential").value.trim()) {
                return say("Enter the one-time credential provided by your HR manager.", "warning");
            }
            const response = await fetch(local ? "/ff_face_attendance/device/local_pair" : "/ff_face_attendance/device/enroll", options);
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "pairing_failed");
            if (!local) byId("ff-device-credential").closest(".ff-kiosk-manual-setup").remove();
            paired = true;
            setKioskLocked(false);
            setAttendanceReady();
            if (requestedEmployeeId) {
                await loadEmployeeStatus(requestedEmployeeId);
            } else {
                employeeSearch.dispatchEvent(new Event("input"));
                say(local ? "Local kiosk connected. Search and select your employee name to continue." : "Kiosk connected. Search and select your employee name to continue.", "success");
            }
        } catch (error) {
            say(local ? "Could not connect the local kiosk. Check that one active kiosk is configured for this company." : "Kiosk setup failed. Check the one-time credential.", "danger");
        }
    };
    const pairButton = byId("ff-kiosk-pair");
    if (localDemo) {
        pairKiosk(true);
    } else {
        pairButton?.addEventListener("click", () => pairKiosk(false));
        fetch("/ff_face_attendance/device/status", { credentials: "same-origin" })
            .then((response) => response.json())
            .then((result) => {
                if (enrollmentOnly) {
                    setKioskLocked(false);
                } else if (result.pin_required) {
                    setKioskLocked(true, "Enter the PIN configured by HR to unlock this kiosk.");
                    return;
                } else if (!result.paired) {
                    return;
                } else {
                    setKioskLocked(false);
                }
                paired = Boolean(result.paired);
                byId("ff-device-credential")?.closest(".ff-kiosk-manual-setup")?.remove();
                setAttendanceReady();
                if (requestedEmployeeId) return loadEmployeeStatus(requestedEmployeeId);
                say("Kiosk is already connected. Search and select your employee name to continue.", "success");
            })
            .catch(() => say("Could not check the kiosk connection. Ask HR to provision this kiosk.", "warning"));
    }

    byId("ff-camera-start").addEventListener("click", async () => {
        if (!navigator.mediaDevices?.getUserMedia) return say("This browser does not provide camera access.", "warning");
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
            const video = byId("ff-kiosk-camera");
            video.srcObject = stream;
            video.classList.remove("d-none");
            byId("ff-landmarks-toggle").disabled = !byId("ff-landmark-consent").checked;
            byId("ff-face-guide").classList.add("is-live");
            setAttendanceReady();
            say("Camera preview is local to this browser. Choose Register face, Check in, or Check out to send the prompted samples.", "info");
        } catch (error) {
            say(error.name === "NotAllowedError" ? "Camera permission was denied." : "The camera could not be opened.", "warning");
        }
    });

    const clearLandmarks = () => {
        const canvas = byId("ff-landmark-overlay");
        canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
        canvas.classList.add("d-none");
    };
    const pauseLandmarkGuide = () => {
        clearInterval(landmarkTimer);
        landmarkTimer = null;
    };
    const makeLandmarkFrame = (video) => {
        const scale = Math.min(1, 640 / video.videoWidth);
        const frame = document.createElement("canvas");
        frame.width = Math.max(1, Math.round(video.videoWidth * scale));
        frame.height = Math.max(1, Math.round(video.videoHeight * scale));
        frame.getContext("2d", { willReadFrequently: true }).drawImage(video, 0, 0, frame.width, frame.height);
        return frame.toDataURL("image/jpeg", 0.62).split(",", 2)[1];
    };
    const drawLandmarks = (result, video) => {
        const canvas = byId("ff-landmark-overlay");
        if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
        }
        const context = canvas.getContext("2d");
        const width = canvas.width;
        const height = canvas.height;
        context.clearRect(0, 0, width, height);
        const points = result.points;
        const point = (name) => [points[name].x * width, points[name].y * height];
        const eyePair = [point("left_eye"), point("right_eye")];
        const mouthPair = [point("mouth_left"), point("mouth_right")];
        const color = result.confidence >= 0.85 ? "#16e0a2" : "#ffc247";
        context.strokeStyle = color;
        context.lineWidth = Math.max(2, width / 320);
        for (const pair of [eyePair, mouthPair]) {
            context.beginPath();
            context.moveTo(...pair[0]);
            context.lineTo(...pair[1]);
            context.stroke();
        }
        const radius = Math.max(4, width / 110);
        for (const name of ["left_eye", "right_eye", "nose", "mouth_left", "mouth_right"]) {
            const [x, y] = point(name);
            context.beginPath();
            context.arc(x, y, radius, 0, Math.PI * 2);
            context.fillStyle = color;
            context.fill();
            context.lineWidth = Math.max(2, width / 320);
            context.strokeStyle = "#101820";
            context.stroke();
        }
        canvas.classList.remove("d-none");
    };
    const updateLandmarks = async () => {
        const video = byId("ff-kiosk-camera");
        if (!landmarkGuideActive || landmarkRequestInFlight || !stream || !video.videoWidth) return;
        landmarkRequestInFlight = true;
        try {
            const response = await fetch("/ff_face_attendance/landmarks", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ capture: makeLandmarkFrame(video) }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "landmark_detection_failed");
            if (!landmarkGuideActive) return;
            drawLandmarks(result, video);
            byId("ff-landmark-status").textContent = tr("Five face points detected (%s%% detector confidence). Frames are not stored.").replace("%s", Math.round(result.confidence * 100));
        } catch (error) {
            if (!landmarkGuideActive) return;
            clearLandmarks();
            byId("ff-landmark-status").textContent = tr(error.message === "one_face_required"
                ? "Show exactly one face, centered and well lit."
                : error.message === "landmark_rate_limited"
                    ? "Adjusting the face guide…"
                    : "Face points unavailable; check the camera or private face service.");
        } finally {
            landmarkRequestInFlight = false;
        }
    };
    const landmarkConsent = byId("ff-landmark-consent");
    const landmarkToggle = byId("ff-landmarks-toggle");
    landmarkConsent.addEventListener("change", () => {
        landmarkToggle.disabled = !landmarkConsent.checked || !stream;
        if (!landmarkConsent.checked && landmarkGuideActive) {
            landmarkGuideActive = false;
            pauseLandmarkGuide();
            clearLandmarks();
            landmarkToggle.textContent = tr("Show face points");
            byId("ff-landmark-status").textContent = tr("Points are off; no camera frames are being sent for alignment.");
        }
    });
    landmarkToggle.addEventListener("click", () => {
        if (!stream || !landmarkConsent.checked) return;
        landmarkGuideActive = !landmarkGuideActive;
        if (landmarkGuideActive) {
            landmarkToggle.textContent = tr("Hide face points");
            byId("ff-landmark-status").textContent = tr("Starting the private face-point guide…");
            updateLandmarks();
            landmarkTimer = setInterval(updateLandmarks, 1200);
        } else {
            pauseLandmarkGuide();
            clearLandmarks();
            landmarkToggle.textContent = tr("Show face points");
            byId("ff-landmark-status").textContent = tr("Points are off; no camera frames are being sent for alignment.");
        }
    });

    const captureFrames = async (video, challenge, guided = false) => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        const frames = [];
        const prompt = byId("ff-motion-prompt");
        // Directions are always from the employee's own left/right, independent
        // of how the selfie preview is mirrored on screen.
        const direction = challenge === "turn_left" ? tr("left") : tr("right");
        if (guided) {
            prompt.textContent = tr("Look straight at the camera");
            prompt.classList.remove("d-none");
            beep(660);
            await new Promise((resolve) => setTimeout(resolve, 800));
            context.drawImage(video, 0, 0);
            frames.push(canvas.toDataURL("image/jpeg", 0.82).split(",", 2)[1]);
        }
        prompt.textContent = tr("Turn your own %s and hold").replace("%s", direction);
        prompt.classList.remove("d-none");
        beep(740);
        await new Promise((resolve) => setTimeout(resolve, guided ? 1400 : 1200));
        const targetFrames = guided ? 4 : 5;
        for (let index = 0; index < targetFrames; index += 1) {
            context.drawImage(video, 0, 0);
            frames.push(canvas.toDataURL("image/jpeg", 0.82).split(",", 2)[1]);
            await new Promise((resolve) => setTimeout(resolve, guided ? 300 : 250));
        }
        prompt.classList.add("d-none");
        return frames;
    };

    // Enrollment must cover the neutral pose and both head-turn directions.
    // A single random side leaves the opposite profile under-represented and
    // makes the later liveness challenge unnecessarily sensitive to direction.
    const captureEnrollmentFrames = async (video) => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        const frames = [];
        const prompt = byId("ff-motion-prompt");
        const capture = () => {
            context.drawImage(video, 0, 0);
            frames.push(canvas.toDataURL("image/jpeg", 0.82).split(",", 2)[1]);
        };
        try {
            prompt.textContent = tr("Look straight at the camera");
            prompt.classList.remove("d-none");
            beep(660);
            await new Promise((resolve) => setTimeout(resolve, 800));
            capture();

            for (const challenge of ["turn_left", "turn_right"]) {
                const direction = challenge === "turn_left" ? tr("left") : tr("right");
                prompt.textContent = tr("Turn your own %s and hold").replace("%s", direction);
                beep(740);
                await new Promise((resolve) => setTimeout(resolve, 1400));
                for (let index = 0; index < 4; index += 1) {
                    capture();
                    await new Promise((resolve) => setTimeout(resolve, 300));
                }
            }
            return frames;
        } finally {
            prompt.classList.add("d-none");
        }
    };

    const registerFace = async () => {
        primeAudio();
        const video = byId("ff-kiosk-camera");
        const employeeId = currentEmployee?.employee_id;
        if (!stream || !video.videoWidth || !hasEmployeeAccess()) return say("Connect the kiosk and start the camera before registration.", "warning");
        if (!employeeId || !currentEmployee?.can_register) return say("Only an HR manager can register or replace face samples; a pending deletion must finish first.", "warning");
        const consentBox = byId(currentEmployee.enrolled ? "ff-reenroll-consent" : "ff-enrollment-consent");
        if (!consentBox.checked) return say("Ask the employee to review the notice and confirm before capturing any samples.", "warning");
        say("Keep one face centered. Look straight first, then turn left and right when prompted to replace the local pilot samples.", "info");
        beep(660);
        pauseLandmarkGuide();
        try {
            const response = await fetch(localDemo ? "/ff_face_attendance/pilot/enroll_public" : "/ff_face_attendance/pilot/enroll", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ employee_id: employeeId, samples: await captureEnrollmentFrames(video), consent_acknowledged: true, consent_version: "2026-11-02-v1" }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "enrollment_failed");
            currentEmployee = { ...currentEmployee, enrolled: true };
            byId("ff-enrollment-consent").checked = false;
            byId("ff-reenroll-consent").checked = false;
            byId("ff-first-time-enrollment").classList.add("d-none");
            byId("ff-enrolled-hint").classList.remove("d-none");
            byId("ff-enrolled-hint-text").textContent = tr("Face samples saved for this employee. Choose Check in or Check out below.");
            byId("ff-reenroll-controls").classList.toggle("d-none", !currentEmployee?.can_enroll);
            setAttendanceReady();
            say(tr("Face samples saved for employee %s.").replace("%s", employeeId), "success");
            beep(880);
        } catch (error) {
            const messages = {
                employee_not_available: "رقم الموظف غير متاح لهذا الكشك",
                exactly_one_face_required: "لم أستطع تحديد وجه واحد. قرّب وجهك وضعه كاملًا داخل الإطار",
                invalid_image: "تعذر قراءة صورة الكاميرا. افحص الكاميرا وحاول مرة أخرى",
                invalid_face_crop: "الوجه لم يظهر كاملًا. اجلس مقابل الكاميرا وفي إضاءة جيدة",
                pilot_enrollment_rejected: "خدمة تسجيل الوجه رفضت العينات. أعد التسجيل في إضاءة جيدة",
                pilot_enrollment_unavailable: "خدمة تسجيل الوجه غير متاحة الآن",
                invalid_pilot_response: "خدمة التسجيل أعادت نتيجة غير مفهومة. تواصل مع الموارد البشرية",
            };
            say(messages[error.message] || "Face registration failed. Keep one face centered and retry.", "warning");
            beep(330);
        } finally {
            byId("ff-motion-prompt").classList.add("d-none");
            if (landmarkGuideActive) landmarkTimer = setInterval(updateLandmarks, 1200);
        }
    };
    byId("ff-pilot-enroll").addEventListener("click", registerFace);
    byId("ff-pilot-reenroll").addEventListener("click", registerFace);

    const verifyAttendance = async (action) => {
        primeAudio();
        const video = byId("ff-kiosk-camera");
        if (!paired || !stream || !video.videoWidth) return say("Connect the kiosk and start the camera first.", "warning");
        byId("ff-check-in").disabled = true;
        byId("ff-check-out").disabled = true;
        pauseLandmarkGuide();
        say(tr("Preparing to %s…").replace("%s", tr(action === "check_in" ? "check in" : "check out")), "info");
        try {
            const sessionResponse = await fetch("/ff_face_attendance/session", { method: "POST", credentials: "same-origin" });
            const session = await sessionResponse.json();
            if (!sessionResponse.ok) throw new Error(session.error || "session_unavailable");
            const challenge = session.challenge;
            if (!["turn_left", "turn_right"].includes(challenge)) throw new Error("invalid_challenge");
            const frames = await captureFrames(video, challenge, true);
            const response = await fetch("/ff_face_attendance/verify", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ session_id: session.session_id, nonce: session.nonce, frames, challenge, action, expected_employee_id: currentEmployee?.employee_id }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "verification_failed");
            currentEmployee.checked_in = result.action === "check_in";
            setAttendanceReady();
            say(result.action === "check_out" ? "Check-out recorded successfully." : "Check-in recorded successfully.", "success");
            beep(880);
        } catch (error) {
            if (error.message === "already_checked_in") currentEmployee.checked_in = true;
            if (error.message === "not_checked_in") currentEmployee.checked_in = false;
            setAttendanceReady();
            const messages = {
                already_checked_in: "You are already checked in. Check in is disabled; use Check out when your shift ends.",
                employee_acknowledgment_required: "Employee acknowledgment is required before enrollment.",
                same_origin_required: "Reload this kiosk page and try again.",
                not_checked_in: "There is no open check-in to check out from. Use Check in first.",
                face_identity_mismatch: "The detected face matched a different employee. No attendance was recorded. Ask HR to re-register your face, then try again.",
                duplicate_event_suppressed: "Attendance was already recorded. Please wait before trying again.",
                attendance_requires_hr_review: "You are already checked in. Check in was blocked; use Check out when your shift ends or ask HR to review your attendance.",
                motion_challenge_failed: "The camera saw your face, but not enough head movement. Keep your face centered and turn your head clearly when prompted.",
                face_match_failed: "Your face was detected, but it did not match the enrolled face. Re-register in even lighting or ask HR to check your enrollment.",
                exactly_one_face_required: "Show only your face in the camera and keep it inside the oval.",
                invalid_image: "The camera frame could not be read. Check the camera and try again.",
                face_service_unavailable: "Face verification service is temporarily unavailable. No attendance was recorded.",
                verification_unavailable: "Odoo could not finish attendance verification because of a system error. No attendance was recorded; contact HR before trying again.",
                challenge_mismatch: "The movement prompt expired or changed. Start the attendance check again and follow the new direction.",
            };
            const kind = error.message === "duplicate_event_suppressed" ? "success" : ["verification_unavailable", "face_service_unavailable"].includes(error.message) ? "danger" : "warning";
            say(messages[error.message] || "Attendance verification failed. Please retry or use Badge/PIN.", kind);
            beep(330);
        } finally {
            byId("ff-motion-prompt").classList.add("d-none");
            setAttendanceReady();
            if (landmarkGuideActive) landmarkTimer = setInterval(updateLandmarks, 1200);
        }
    };
    byId("ff-check-in").addEventListener("click", () => verifyAttendance("check_in"));
    byId("ff-check-out").addEventListener("click", () => verifyAttendance("check_out"));
    return true;
};

const bootFaceKiosk = () => {
    if (initializeFaceKiosk()) return;
    const observer = new MutationObserver(() => {
        if (initializeFaceKiosk()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFaceKiosk, { once: true });
} else {
    bootFaceKiosk();
}
