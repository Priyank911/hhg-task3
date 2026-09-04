from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np
import pytest

from app.config import get_settings
from app.services.face_matcher import FaceMatcher, FaceMatcherError


@pytest.fixture
def face_matcher() -> FaceMatcher:
    settings = get_settings()
    yunet = settings.resolve_path(settings.yunet_model_path)
    sface = settings.resolve_path(settings.sface_model_path)
    return FaceMatcher(yunet_path=yunet, sface_path=sface)


def test_model_info_and_checksums(face_matcher: FaceMatcher):
    det_info, rec_info = face_matcher.get_model_info()
    assert det_info.name == "YuNet"
    assert len(det_info.artifactSha256) == 64
    assert rec_info.name == "SFace"
    assert len(rec_info.artifactSha256) == 64


def test_detect_faces_on_blank_image(face_matcher: FaceMatcher):
    blank_img = np.zeros((300, 300, 3), dtype=np.uint8)
    faces, raw_faces = face_matcher.detect_faces(blank_img)
    assert len(faces) == 0
    assert raw_faces is None


def test_missing_model_raises_error(tmp_path: Path):
    non_existent = tmp_path / "missing.onnx"
    with pytest.raises(FaceMatcherError):
        FaceMatcher(yunet_path=non_existent, sface_path=non_existent)
