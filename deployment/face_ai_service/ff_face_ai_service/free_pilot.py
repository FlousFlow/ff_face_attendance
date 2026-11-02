"""Free pilot face matcher.

This module deliberately uses only employee-provided samples and OpenCV's
LBPH recognizer. It is suitable for the user's supervised pilot, not a claim
of strong spoof resistance. Enrollment crops are encrypted at rest with
Fernet keys supplied by the deployment operator.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import logging
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class PilotError(ValueError):
    pass


class FreeFacePilot:
    MODEL_VERSION = "free-opencv-lbph-yunet-pilot-1"
    _logger = logging.getLogger("ff_face_ai_service.pilot")

    def __init__(self, gallery_dir: str, detector_path: str, gallery_keys: str, threshold: float = 70.0):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:  # pragma: no cover - exercised in minimal installs
            raise PilotError("opencv_contrib_and_numpy_required") from exc
        if not hasattr(cv2, "face"):
            raise PilotError("opencv_contrib_required")
        self.cv2 = cv2
        self.np = np
        self.gallery_dir = Path(gallery_dir)
        self.gallery_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.gallery_dir.chmod(0o700)
        keys = [value.strip().encode() for value in gallery_keys.split(",") if value.strip()]
        if not keys:
            raise PilotError("gallery_encryption_key_required")
        try:
            fernets = [Fernet(key) for key in keys]
            self._gallery_cipher = MultiFernet(fernets)
            self._gallery_primary = fernets[0]
        except (TypeError, ValueError) as exc:
            raise PilotError("gallery_encryption_key_invalid") from exc
        self.detector_path = Path(detector_path)
        self.threshold = float(threshold)
        self._lock = threading.RLock()
        self._labels: dict[int, str] = {}
        self._recognizer = None
        if self.detector_path.exists():
            self.detector = cv2.FaceDetectorYN.create(str(self.detector_path), "", (320, 320), 0.75, 0.3, 5000)
            self._load_gallery()
        else:
            raise PilotError("yunet_model_missing")

    def _metadata_path(self):
        return self.gallery_dir / "gallery.json"

    def _samples_path(self):
        return self.gallery_dir / "samples.npz"

    def _encrypted_gallery_path(self):
        return self.gallery_dir / "gallery.enc"

    def _write_gallery(self, images, labels, label_refs):
        buffer = io.BytesIO()
        metadata = json.dumps({str(key): value for key, value in label_refs.items()}, sort_keys=True)
        self.np.savez_compressed(
            buffer,
            images=self.np.asarray(images, dtype=self.np.uint8),
            labels=self.np.asarray(labels, dtype=self.np.int32),
            metadata=self.np.asarray(metadata),
        )
        self._write_encrypted_token(self._gallery_cipher.encrypt(buffer.getvalue()))

    def _read_gallery(self):
        path = self._encrypted_gallery_path()
        if path.exists():
            token = path.read_bytes()
            try:
                cleartext = self._gallery_cipher.decrypt(token)
            except InvalidToken as exc:
                raise PilotError("gallery_decryption_failed") from exc
            try:
                with self.np.load(io.BytesIO(cleartext), allow_pickle=False) as archive:
                    images = list(archive["images"])
                    labels = [int(value) for value in archive["labels"]]
                    refs = {int(key): value for key, value in json.loads(archive["metadata"].item()).items()}
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise PilotError("gallery_data_invalid") from exc
            try:
                self._gallery_primary.decrypt(token)
            except InvalidToken:
                rotated = self._gallery_cipher.rotate(token)
                self._write_encrypted_token(rotated)
            self._metadata_path().unlink(missing_ok=True)
            self._samples_path().unlink(missing_ok=True)
            return images, labels, refs

        # Migrate the previous unencrypted pilot format once, then remove its cleartext files.
        if self._metadata_path().exists() or self._samples_path().exists():
            try:
                metadata = json.loads(self._metadata_path().read_text())
                with self.np.load(self._samples_path(), allow_pickle=False) as archive:
                    images = list(archive["images"])
                    labels = [int(value) for value in archive["labels"]]
                refs = {int(key): value for key, value in metadata.items()}
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise PilotError("legacy_gallery_invalid") from exc
            self._write_gallery(images, labels, refs)
            self._metadata_path().unlink(missing_ok=True)
            self._samples_path().unlink(missing_ok=True)
            return images, labels, refs
        return [], [], {}

    def _write_encrypted_token(self, encrypted):
        target = self._encrypted_gallery_path()
        temporary = self.gallery_dir / f".gallery-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_gallery(self):
        images, labels, self._labels = self._read_gallery()
        if images and labels:
            self._train(images, labels)

    def _decode(self, encoded: str):
        try:
            raw = base64.b64decode(encoded, validate=True)
            image = self.cv2.imdecode(self.np.frombuffer(raw, dtype=self.np.uint8), self.cv2.IMREAD_COLOR)
        except (ValueError, TypeError):
            image = None
        if image is None:
            raise PilotError("invalid_image")
        return image

    def _face_crop(self, image):
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) != 1:
            raise PilotError("exactly_one_face_required")
        x, y, w, h = [int(round(value)) for value in faces[0][:4]]
        margin = int(max(w, h) * 0.18)
        x1, y1 = max(0, x - margin), max(0, y - margin)
        x2, y2 = min(width, x + w + margin), min(height, y + h + margin)
        crop = self.cv2.cvtColor(image[y1:y2, x1:x2], self.cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            raise PilotError("invalid_face_crop")
        return self.cv2.resize(crop, (160, 160), interpolation=self.cv2.INTER_AREA), faces[0]

    def landmarks(self, encoded: str):
        """Return YuNet's five alignment landmarks without persisting the frame."""
        with self._lock:
            image = self._decode(encoded)
            height, width = image.shape[:2]
            self.detector.setInputSize((width, height))
            _, faces = self.detector.detect(image)
            if faces is None or len(faces) != 1:
                raise PilotError("exactly_one_face_required")
            face = faces[0]
            names = ("left_eye", "right_eye", "nose", "mouth_left", "mouth_right")
            points = {
                name: {
                    "x": round(float(face[4 + index * 2]) / width, 6),
                    "y": round(float(face[5 + index * 2]) / height, 6),
                }
                for index, name in enumerate(names)
            }
            x, y, box_width, box_height = (float(value) for value in face[:4])
            return {
                "width": width,
                "height": height,
                "face_box": {
                    "x": round(x / width, 6),
                    "y": round(y / height, 6),
                    "width": round(box_width / width, 6),
                    "height": round(box_height / height, 6),
                },
                "points": points,
                "confidence": round(float(face[14]), 6),
            }

    def _train(self, images, labels):
        if not images:
            self._recognizer = None
            return
        recognizer = self.cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
        recognizer.train(images, self.np.asarray(labels, dtype=self.np.int32))
        self._recognizer = recognizer

    def enroll(self, template_ref: str, samples: list[str]):
        if not template_ref or not samples or len(samples) < 3 or len(samples) > 10:
            raise PilotError("enrollment_requires_3_to_10_samples")
        with self._lock:
            images, labels, label_refs = self._read_gallery()
            label = next((key for key, value in label_refs.items() if value == template_ref), None)
            if label is None:
                label = max(label_refs.keys(), default=0) + 1
            images = [image for image, old_label in zip(images, labels) if int(old_label) != label]
            labels = [old_label for old_label in labels if int(old_label) != label]
            for encoded in samples:
                crop, _ = self._face_crop(self._decode(encoded))
                images.append(crop)
                labels.append(label)
            label_refs[label] = template_ref
            self._write_gallery(images, labels, label_refs)
            self._labels = label_refs
            self._train(images, labels)
            return {"template_ref": template_ref, "sample_count": len(samples), "model_version": self.MODEL_VERSION}

    def revoke(self, template_ref: str):
        if not template_ref:
            raise PilotError("invalid_template_ref")
        with self._lock:
            images, labels, label_refs = self._read_gallery()
            label = next((key for key, value in label_refs.items() if value == template_ref), None)
            if label is None:
                return {"result": "revoked", "deleted": False}
            retained = [(image, old_label) for image, old_label in zip(images, labels) if old_label != label]
            new_images = [image for image, _ in retained]
            new_labels = [old_label for _, old_label in retained]
            new_refs = {key: value for key, value in label_refs.items() if key != label}
            self._write_gallery(new_images, new_labels, new_refs)
            self._labels = new_refs
            self._train(new_images, new_labels)
            return {"result": "revoked", "deleted": True}

    def _challenge_passed(self, faces, challenge: str):
        if len(faces) < 3:
            self._logger.warning("liveness_rejected reason=insufficient_faces detected=%s", len(faces))
            return False
        yaw = []
        for face in faces:
            left_eye_x, right_eye_x, nose_x = face[4], face[6], face[8]
            eye_mid = (left_eye_x + right_eye_x) / 2.0
            eye_span = max(abs(right_eye_x - left_eye_x), 1.0)
            yaw.append((nose_x - eye_mid) / eye_span)
        delta = yaw[-1] - yaw[0]
        # The kiosk canvas captures raw camera pixels (not its mirrored CSS
        # preview): the employee's own left maps to a positive nose displacement.
        # Enforce the requested sign so a previously recorded opposite turn fails.
        passed = delta >= 0.05 if challenge == "turn_left" else delta <= -0.05
        self._logger.info("liveness_check challenge=%s yaw_delta=%.4f threshold=0.05 passed=%s", challenge, delta, passed)
        return passed

    def verify(self, frames: list[str], challenge: str):
        if not self._recognizer or len(frames) < 3 or len(frames) > 5:
            raise PilotError("pilot_not_enrolled_or_insufficient_frames")
        with self._lock:
            crops, faces = [], []
            for encoded in frames:
                crop, face = self._face_crop(self._decode(encoded))
                crops.append(crop)
                faces.append(face)
            if not self._challenge_passed(faces, challenge):
                raise PilotError("motion_challenge_failed")
            predictions = [self._recognizer.predict(crop) for crop in crops]
            label = max(set(prediction[0] for prediction in predictions), key=lambda value: sum(prediction[0] == value for prediction in predictions))
            distances = [distance for predicted_label, distance in predictions if predicted_label == label]
            max_distance = max(distances) if distances else None
            self._logger.warning("face_match label=%s distances=%s threshold=%.2f", label, [round(float(value), 2) for value in distances], self.threshold)
            if not distances or max_distance > self.threshold:
                raise PilotError("face_match_failed")
            return {"template_ref": self._labels[label], "score": round(float(sum(distances) / len(distances)), 3), "model_version": self.MODEL_VERSION}
