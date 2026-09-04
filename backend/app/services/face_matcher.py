from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Tuple, List, Optional
import cv2
import numpy as np

from app.schemas import DetectedFace, ModelArtifactInfo


class FaceMatcherError(Exception):
    pass


class FaceMatcher:
    def __init__(
        self,
        yunet_path: Path | str,
        sface_path: Path | str,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
    ):
        self.yunet_path = Path(yunet_path)
        self.sface_path = Path(sface_path)

        if not self.yunet_path.exists():
            raise FaceMatcherError(f"YuNet model ONNX not found at: {self.yunet_path}")
        if not self.sface_path.exists():
            raise FaceMatcherError(f"SFace model ONNX not found at: {self.sface_path}")

        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold

        self.detector = cv2.FaceDetectorYN.create(
            model=str(self.yunet_path),
            config="",
            input_size=(320, 320),
            score_threshold=self.score_threshold,
            nms_threshold=self.nms_threshold,
            top_k=5000,
        )

        self.recognizer = cv2.FaceRecognizerSF.create(
            model=str(self.sface_path),
            config="",
        )

    def get_model_info(self) -> Tuple[ModelArtifactInfo, ModelArtifactInfo]:
        """Returns model artifact metadata and SHA-256 checksums."""
        yunet_sha = self._calculate_file_sha256(self.yunet_path)
        sface_sha = self._calculate_file_sha256(self.sface_path)

        detector_info = ModelArtifactInfo(
            name="YuNet",
            artifact=self.yunet_path.name,
            artifactSha256=yunet_sha,
        )
        recognizer_info = ModelArtifactInfo(
            name="SFace",
            artifact=self.sface_path.name,
            artifactSha256=sface_sha,
        )
        return detector_info, recognizer_info

    @staticmethod
    def _calculate_file_sha256(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    def detect_faces(self, bgr_image: np.ndarray) -> Tuple[List[DetectedFace], Optional[np.ndarray]]:
        """
        Detects faces in a BGR image using YuNet.
        Returns a list of DetectedFace objects and the raw faces array for internal alignment.
        """
        height, width = bgr_image.shape[:2]
        self.detector.setInputSize((width, height))
        _, raw_faces = self.detector.detect(bgr_image)

        if raw_faces is None or len(raw_faces) == 0:
            return [], None

        detected_list: List[DetectedFace] = []
        for idx, row in enumerate(raw_faces):
            x, y, w, h = int(row[0]), int(row[1]), int(row[2]), int(row[3])
            score = float(row[14])
            
            landmarks: List[List[int]] = []
            for lm_idx in range(5):
                lx = int(row[4 + lm_idx * 2])
                ly = int(row[5 + lm_idx * 2])
                landmarks.append([lx, ly])

            warnings: List[str] = []
            if w < 30 or h < 30:
                warnings.append("small_face_size")
            if score < 0.7:
                warnings.append("low_detection_confidence")

            detected_list.append(
                DetectedFace(
                    index=idx,
                    bounding_box_px=[x, y, w, h],
                    landmarks_px=landmarks,
                    detection_score=score,
                    quality_warnings=warnings,
                )
            )

        return detected_list, raw_faces

    def annotate_image(self, bgr_image: np.ndarray, detected_faces: List[DetectedFace]) -> np.ndarray:
        """
        Draws numbered bounding boxes and landmark points on a copy of the image.
        """
        canvas = bgr_image.copy()
        for face in detected_faces:
            x, y, w, h = face.bounding_box_px
            # Draw bounding box (Green)
            cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Label index & score
            label = f"#{face.index} ({face.detection_score:.2f})"
            cv2.putText(
                canvas,
                label,
                (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            # Draw landmarks (Red/Blue/Yellow)
            for lm in face.landmarks_px:
                cv2.circle(canvas, (lm[0], lm[1]), 3, (0, 0, 255), -1)

        return canvas

    def encode_face(self, bgr_image: np.ndarray, raw_face_row: np.ndarray) -> np.ndarray:
        """
        Aligns and extracts the 128-d feature vector using SFace.
        Vector is kept in memory.
        """
        aligned_face = self.recognizer.alignCrop(bgr_image, raw_face_row)
        feature = self.recognizer.feature(aligned_face)
        return feature

    def compare_embeddings(
        self,
        feature1: np.ndarray,
        feature2: np.ndarray,
        metric: str = "cosine",
    ) -> float:
        """
        Compares two SFace feature vectors. Returns cosine similarity score.
        """
        if metric.lower() == "cosine":
            match_mode = cv2.FaceRecognizerSF_FR_COSINE
        else:
            match_mode = cv2.FaceRecognizerSF_FR_NORM_L2

        score = self.recognizer.match(feature1, feature2, match_mode)
        return float(score)
