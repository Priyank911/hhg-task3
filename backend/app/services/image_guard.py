from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Tuple
import numpy as np
from PIL import Image, ImageOps

MAX_ENCODED_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PIXELS = 12 * 1024 * 1024         # 12 Megapixels
MAX_SEARCH_COPY_BYTES = 480 * 1024     # 480 KB (under SerpApi 500KB limit)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(Exception):
    pass


class ImageGuard:
    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def load_and_validate(cls, image_path: Path | str) -> Tuple[np.ndarray, bytes, str]:
        """
        Loads an image from disk, validates limits, applies EXIF orientation,
        and returns (opencv_bgr_array, raw_bytes, sha256_hex).
        """
        path = Path(image_path)
        if not path.exists():
            raise ImageValidationError(f"Image file does not exist: {path}")

        file_size = path.stat().st_size
        if file_size > MAX_ENCODED_BYTES:
            raise ImageValidationError(
                f"Image size {file_size} bytes exceeds maximum limit of {MAX_ENCODED_BYTES} bytes."
            )
        if file_size == 0:
            raise ImageValidationError("Image file is empty (0 bytes).")

        with open(path, "rb") as f:
            raw_bytes = f.read()

        return cls.validate_and_decode_bytes(raw_bytes)

    @classmethod
    def validate_and_decode_bytes(cls, raw_bytes: bytes) -> Tuple[np.ndarray, bytes, str]:
        """
        Validates raw image bytes and decodes safely.
        """
        if len(raw_bytes) > MAX_ENCODED_BYTES:
            raise ImageValidationError(
                f"Image byte size {len(raw_bytes)} exceeds maximum limit of {MAX_ENCODED_BYTES} bytes."
            )

        sha256_hex = cls.calculate_sha256(raw_bytes)

        try:
            pil_img = Image.open(io.BytesIO(raw_bytes))
        except Exception as e:
            raise ImageValidationError(f"Malformed or unsupported image file: {e}") from e

        if pil_img.format not in ALLOWED_FORMATS:
            raise ImageValidationError(
                f"Unsupported image format: {pil_img.format}. Allowed: {ALLOWED_FORMATS}"
            )

        width, height = pil_img.size
        total_pixels = width * height
        if total_pixels > MAX_PIXELS:
            raise ImageValidationError(
                f"Image resolution {width}x{height} ({total_pixels} pixels) exceeds limit of {MAX_PIXELS} pixels."
            )

        # Apply EXIF orientation safely
        try:
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception:
            pass  # If EXIF transposition fails, proceed with original orientation

        # Convert to RGB mode
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        # Convert to OpenCV BGR numpy array
        rgb_array = np.array(pil_img)
        bgr_array = rgb_array[:, :, ::-1].copy()

        return bgr_array, raw_bytes, sha256_hex

    @classmethod
    def create_search_copy(cls, bgr_image: np.ndarray) -> Tuple[bytes, str]:
        """
        Creates a compressed search copy (JPEG) bounded under 500 KB for SerpApi upload.
        Returns (search_bytes, search_sha256_hex).
        """
        # Convert BGR back to RGB PIL
        rgb_image = bgr_image[:, :, ::-1]
        pil_img = Image.fromarray(rgb_image)

        # Downscale if image dimensions are very large
        max_dim = 1600
        if max(pil_img.size) > max_dim:
            pil_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        quality = 90
        buf = io.BytesIO()
        while quality >= 30:
            buf.seek(0)
            buf.truncate(0)
            pil_img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= MAX_SEARCH_COPY_BYTES:
                break
            quality -= 10

        search_bytes = buf.getvalue()
        search_sha256 = cls.calculate_sha256(search_bytes)
        return search_bytes, search_sha256
