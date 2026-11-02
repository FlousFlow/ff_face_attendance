from concurrent.futures import ThreadPoolExecutor
from threading import RLock

import numpy as np
import pytest
from cryptography.fernet import Fernet, MultiFernet
import json

from ff_face_ai_service.free_pilot import FreeFacePilot


class _Recognizer:
    def train(self, images, labels):
        self.trained_count = len(images)


class _Face:
    @staticmethod
    def LBPHFaceRecognizer_create(**kwargs):
        return _Recognizer()


class _CV2:
    face = _Face()


def _gallery(tmp_path, keys):
    pilot = FreeFacePilot.__new__(FreeFacePilot)
    pilot.np = np
    pilot.cv2 = _CV2()
    pilot.gallery_dir = tmp_path
    pilot._gallery_cipher = MultiFernet([Fernet(key) for key in keys])
    pilot._gallery_primary = Fernet(keys[0])
    pilot._lock = RLock()
    pilot._labels = {}
    pilot._recognizer = None
    pilot.threshold = 70.0
    return pilot


def _face_with_nose_x(nose_x):
    # YuNet layout: left-eye x/y, right-eye x/y, nose x/y, followed by landmarks.
    return [0, 0, 100, 100, 40, 20, 60, 20, nose_x, 30]


def test_random_direction_challenge_requires_the_requested_turn():
    pilot = FreeFacePilot.__new__(FreeFacePilot)
    left_turn = [_face_with_nose_x(value) for value in (50, 52, 54)]
    right_turn = [_face_with_nose_x(value) for value in (50, 48, 46)]

    assert pilot._challenge_passed(left_turn, "turn_left")
    assert not pilot._challenge_passed(left_turn, "turn_right")
    assert pilot._challenge_passed(right_turn, "turn_right")
    assert not pilot._challenge_passed(right_turn, "turn_left")


def test_yunet_alignment_points_are_normalized_and_not_saved():
    pilot = FreeFacePilot.__new__(FreeFacePilot)
    pilot._lock = RLock()
    pilot._decode = lambda _encoded: np.zeros((200, 100, 3), dtype=np.uint8)

    class _Detector:
        def setInputSize(self, _size):
            pass

        def detect(self, _image):
            face = np.asarray([[10, 20, 50, 60, 25, 35, 45, 35, 35, 48, 28, 60, 42, 60, 0.95]], dtype=np.float32)
            return 1, face

    pilot.detector = _Detector()
    result = pilot.landmarks("fake-frame")

    assert result["width"] == 100
    assert result["height"] == 200
    assert result["points"]["nose"] == {"x": 0.35, "y": 0.24}
    assert result["confidence"] == 0.95


def test_gallery_is_encrypted_at_rest_and_can_be_loaded_after_restart(tmp_path):
    key = Fernet.generate_key()
    pilot = _gallery(tmp_path, [key])
    crop = np.full((160, 160), 17, dtype=np.uint8)
    pilot._write_gallery([crop], [1], {1: "odoo-private-template"})

    encrypted_path = tmp_path / "gallery.enc"
    encrypted = encrypted_path.read_bytes()
    assert encrypted
    assert b"odoo-private-template" not in encrypted
    assert bytes([17]) * 32 not in encrypted
    assert encrypted_path.stat().st_mode & 0o777 == 0o600

    restarted = _gallery(tmp_path, [key])
    images, labels, refs = restarted._read_gallery()
    assert np.array_equal(images[0], crop)
    assert labels == [1]
    assert refs == {1: "odoo-private-template"}


def test_key_rotation_reencrypts_gallery_with_primary_key(tmp_path):
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    original = _gallery(tmp_path, [old_key])
    original._write_gallery([np.full((160, 160), 31, dtype=np.uint8)], [1], {1: "template-one"})
    encrypted_path = tmp_path / "gallery.enc"
    previous_token = encrypted_path.read_bytes()

    rotated = _gallery(tmp_path, [new_key, old_key])
    rotated._read_gallery()
    current_token = encrypted_path.read_bytes()
    assert current_token != previous_token
    assert Fernet(new_key).decrypt(current_token)
    with pytest.raises(Exception):
        Fernet(old_key).decrypt(current_token)


def test_loading_with_current_primary_key_does_not_rewrite_gallery(tmp_path):
    key = Fernet.generate_key()
    pilot = _gallery(tmp_path, [key])
    pilot._write_gallery([np.full((160, 160), 41, dtype=np.uint8)], [1], {1: "template-one"})
    encrypted_path = tmp_path / "gallery.enc"
    previous_token = encrypted_path.read_bytes()

    _gallery(tmp_path, [key])._read_gallery()

    assert encrypted_path.read_bytes() == previous_token


def test_legacy_cleartext_gallery_is_encrypted_and_removed(tmp_path):
    pilot = _gallery(tmp_path, [Fernet.generate_key()])
    crop = np.full((160, 160), 53, dtype=np.uint8)
    np.savez_compressed(tmp_path / "samples.npz", images=np.asarray([crop]), labels=np.asarray([4]))
    (tmp_path / "gallery.json").write_text(json.dumps({"4": "legacy-template"}))

    images, labels, refs = pilot._read_gallery()

    assert len(images) == 1 and np.array_equal(images[0], crop)
    assert labels == [4]
    assert refs == {4: "legacy-template"}
    assert (tmp_path / "gallery.enc").exists()
    assert not (tmp_path / "samples.npz").exists()
    assert not (tmp_path / "gallery.json").exists()


def test_revoke_deletes_only_matching_template_and_is_idempotent(tmp_path):
    key = Fernet.generate_key()
    pilot = _gallery(tmp_path, [key])
    first = np.full((160, 160), 11, dtype=np.uint8)
    second = np.full((160, 160), 29, dtype=np.uint8)
    pilot._write_gallery([first, second], [1, 2], {1: "template-one", 2: "template-two"})

    assert pilot.revoke("template-one") == {"result": "revoked", "deleted": True}
    images, labels, refs = pilot._read_gallery()
    assert len(images) == 1
    assert np.array_equal(images[0], second)
    assert labels == [2]
    assert refs == {2: "template-two"}
    assert pilot.revoke("template-one") == {"result": "revoked", "deleted": False}
