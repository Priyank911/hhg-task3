from __future__ import annotations

import io
from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from app.services.image_guard import ImageGuard, ImageValidationError, MAX_SEARCH_COPY_BYTES


def test_valid_image_decode(sample_temp_image: Path):
    bgr, raw_bytes, sha = ImageGuard.load_and_validate(sample_temp_image)
    assert isinstance(bgr, np.ndarray)
    assert bgr.shape[0] == 240
    assert bgr.shape[1] == 320
    assert len(sha) == 64


def test_empty_image_fails(tmp_path: Path):
    empty_file = tmp_path / "empty.jpg"
    empty_file.write_bytes(b"")
    with pytest.raises(ImageValidationError, match="empty"):
        ImageGuard.load_and_validate(empty_file)


def test_corrupt_image_fails():
    corrupt_bytes = b"NOT_AN_IMAGE_HEADER_123456"
    with pytest.raises(ImageValidationError, match="Malformed"):
        ImageGuard.validate_and_decode_bytes(corrupt_bytes)


def test_unsupported_format():
    buf = io.BytesIO()
    img = Image.new("RGB", (50, 50), color=(255, 0, 0))
    img.save(buf, format="GIF")
    with pytest.raises(ImageValidationError, match="Unsupported image format"):
        ImageGuard.validate_and_decode_bytes(buf.getvalue())


def test_search_copy_compression(sample_pil_image: Image.Image):
    rgb = np.array(sample_pil_image)
    bgr = rgb[:, :, ::-1]
    search_bytes, sha = ImageGuard.create_search_copy(bgr)
    assert len(search_bytes) <= MAX_SEARCH_COPY_BYTES
    assert len(sha) == 64
    assert search_bytes.startswith(b"\xff\xd8")  # JPEG SOI marker
