from __future__ import annotations

import io
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def sample_pil_image() -> Image.Image:
    """Creates a basic valid RGB test image."""
    img = Image.new("RGB", (320, 240), color=(120, 180, 240))
    draw = ImageDraw.Draw(img)
    # Draw simple shapes
    draw.rectangle([50, 50, 150, 150], fill=(220, 180, 140))
    draw.ellipse([80, 80, 100, 100], fill=(0, 0, 0))
    draw.ellipse([120, 80, 140, 100], fill=(0, 0, 0))
    return img


@pytest.fixture
def sample_jpeg_bytes(sample_pil_image: Image.Image) -> bytes:
    buf = io.BytesIO()
    sample_pil_image.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture
def sample_temp_image(tmp_path: Path, sample_jpeg_bytes: bytes) -> Path:
    img_path = tmp_path / "test_query.jpg"
    img_path.write_bytes(sample_jpeg_bytes)
    return img_path
