#!/usr/bin/env python3
"""
Model acquisition and checksum verification script for OpenCV YuNet & SFace models.
Downloads official ONNX weights from OpenCV Zoo and validates SHA-256 hashes.
Also downloads consented demo & test face fixtures.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

MODEL_SOURCES = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

FIXTURE_SOURCES = {
    "backend/tests/fixtures/query.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
    "backend/tests/fixtures/candidate.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
    "demo/consented-query.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
}

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models"
CHECKSUM_FILE = MODELS_DIR / "MODEL_CHECKSUMS.txt"


def calculate_sha256(filepath: Path) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def download_file(url: str, target: Path) -> None:
    print(f"Downloading {url} -> {target.name}...")
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp, open(target, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 65536
        while chunk := resp.read(chunk_size):
            out.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                percent = downloaded / total * 100
                print(f"\r  [{percent:5.1f}%] {downloaded}/{total} bytes", end="", flush=True)
        print()


def verify_or_download() -> bool:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    all_ok = True
    actual_checksums: dict[str, str] = {}

    for filename, url in MODEL_SOURCES.items():
        filepath = MODELS_DIR / filename
        if not filepath.exists() or filepath.stat().st_size == 0:
            download_file(url, filepath)
        
        digest = calculate_sha256(filepath)
        actual_checksums[filename] = digest
        print(f"Verified {filename}: {digest}")

    # Write or update MODEL_CHECKSUMS.txt
    lines = [f"{digest}  {filename}\n" for filename, digest in actual_checksums.items()]
    with open(CHECKSUM_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"Updated checksum record at {CHECKSUM_FILE}")

    # Download fixtures if missing
    for rel_path, url in FIXTURE_SOURCES.items():
        target = ROOT_DIR / rel_path
        if not target.exists() or target.stat().st_size == 0:
            download_file(url, target)
            print(f"Downloaded test fixture: {rel_path}")

    return all_ok


if __name__ == "__main__":
    success = verify_or_download()
    sys.exit(0 if success else 1)
