from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple
import cv2
import numpy as np

from app.config import Settings
from app.schemas import (
    AttestationSidecar,
    CandidateEvidence,
    ClaimEvidence,
    ComparisonEvidence,
    ConsentInfo,
    DiscoveryEvidence,
    EvidenceManifest,
    ModelArtifactInfo,
    PipelineErrorCode,
    PipelineState,
    QueryEvidence,
    SoftwareEvidence,
)
from app.services.blockchain import BlockchainService
from app.services.consent import ConsentService
from app.services.downloader import CandidateDownloader
from app.services.face_matcher import FaceMatcher
from app.services.image_guard import ImageGuard
from app.services.manifest import ManifestBuilder
from app.services.search import (
    MockSearchAdapter,
    SearchAdapter,
    SearchCandidate,
    SearchResultBundle,
    SerpApiLensAdapter,
)


class PipelineExecutionError(Exception):
    def __init__(self, code: PipelineErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EvidencePipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        
        # Initialize face matcher models
        yunet_path = settings.resolve_path(settings.yunet_model_path)
        sface_path = settings.resolve_path(settings.sface_model_path)
        self.face_matcher = FaceMatcher(
            yunet_path=yunet_path,
            sface_path=sface_path,
        )

        # Initialize search adapter
        if settings.search_provider.lower() == "serpapi":
            if not settings.serpapi_api_key:
                raise PipelineExecutionError(
                    PipelineErrorCode.FAILED_SEARCH_AUTH,
                    "SERPAPI_API_KEY is required for live search provider.",
                )
            self.search_adapter: SearchAdapter = SerpApiLensAdapter(api_key=settings.serpapi_api_key)
        else:
            self.search_adapter = MockSearchAdapter()

        # Blockchain service
        self.blockchain_service = BlockchainService(
            rpc_url=settings.rpc_url,
            chain_id=settings.chain_id,
            contract_address=settings.registry_address,
            private_key=settings.attester_private_key,
        )

    def run(
        self,
        input_image_path: Path | str,
        face_index: Optional[int] = None,
        consent_confirmed: bool = False,
        search_provider_override: Optional[str] = None,
        mock_candidate_image_bytes: Optional[bytes] = None,
        custom_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Executes the full pipeline:
        Face Scan -> Live/Mock Web Search -> Local Candidate Comparison -> Manifest Generation -> Blockchain Anchor.
        """
        run_id = custom_run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        run_dir = self.settings.resolve_path(self.settings.runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        candidates_dir = run_dir / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)

        # Stage 1: Consent Verification
        if not consent_confirmed:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_NO_CONSENT,
                "Biometric consent was not confirmed. Explicit consent is mandatory.",
            )
        consent_record = ConsentService.create_consent_record(
            confirmed=True,
            scope="hh-goa-demo",
            retention_hours=self.settings.retention_hours,
        )
        consent_path = run_dir / "consent.json"
        consent_record_sha256 = ConsentService.save_consent(consent_record, consent_path)

        # Stage 2: Query Image Validation
        try:
            bgr_image, orig_bytes, orig_sha256 = ImageGuard.load_and_validate(input_image_path)
        except Exception as e:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_INVALID_IMAGE,
                f"Query image validation failed: {e}",
            ) from e

        # Stage 3: Query Face Detection
        detected_faces, raw_faces = self.face_matcher.detect_faces(bgr_image)
        if len(detected_faces) == 0 or raw_faces is None:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_NO_FACE,
                "No face detected in the query image.",
            )

        # Save annotated image for operator reference
        annotated_img = self.face_matcher.annotate_image(bgr_image, detected_faces)
        annotated_path = run_dir / "query-annotated.jpg"
        cv2.imwrite(str(annotated_path), annotated_img)

        # Require deliberate face selection if multiple faces present
        if len(detected_faces) > 1:
            if face_index is None:
                raise PipelineExecutionError(
                    PipelineErrorCode.FAILED_FACE_SELECTION_REQUIRED,
                    f"Multiple faces detected ({len(detected_faces)}). Please inspect {annotated_path} and specify --face-index.",
                )
            if face_index < 0 or face_index >= len(detected_faces):
                raise PipelineExecutionError(
                    PipelineErrorCode.FAILED_FACE_SELECTION_REQUIRED,
                    f"Invalid face index {face_index}. Allowed: 0 to {len(detected_faces) - 1}.",
                )
            selected_idx = face_index
        else:
            selected_idx = face_index if face_index is not None else 0

        selected_face = detected_faces[selected_idx]
        selected_raw_face = raw_faces[selected_idx]

        # Stage 4: Query Face Embedding (Kept in-memory only)
        query_embedding = self.face_matcher.encode_face(bgr_image, selected_raw_face)

        # Stage 5: Search Copy Preparation (<500 KB compressed JPEG)
        search_bytes, search_sha256 = ImageGuard.create_search_copy(bgr_image)

        # Stage 6: Search Execution (Live or Mock)
        adapter = self.search_adapter
        if search_provider_override:
            if search_provider_override.lower() == "serpapi":
                if not self.settings.serpapi_api_key:
                    raise PipelineExecutionError(
                        PipelineErrorCode.FAILED_SEARCH_AUTH,
                        "SERPAPI_API_KEY required for live search override.",
                    )
                adapter = SerpApiLensAdapter(self.settings.serpapi_api_key)
            elif search_provider_override.lower() == "mock":
                adapter = MockSearchAdapter()

        # Save search request metadata
        with open(run_dir / "search-request.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "provider": getattr(adapter, "SERPAPI_SEARCH_URL", "mock"),
                    "searchCopySha256": search_sha256,
                    "searchCopyBytes": len(search_bytes),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                f,
                indent=2,
            )

        try:
            search_bundle: SearchResultBundle = adapter.search(search_bytes)
        except Exception as e:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_SEARCH_QUOTA if "quota" in str(e).lower() else PipelineErrorCode.FAILED_SEARCH_AUTH,
                f"Search execution failed: {e}",
            ) from e

        # Save raw search response
        with open(run_dir / "search-response.raw.json", "wb") as f:
            f.write(search_bundle.raw_response_bytes)

        if len(search_bundle.candidates) == 0:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_NO_SOCIAL_RESULT,
                "No candidate results returned by search provider.",
            )

        # Stage 7 & 8: Candidate Retrieval and Local Face Comparison
        accepted_candidate_data = None
        best_overall_score = -1.0
        best_candidate_info = None

        candidate_list = search_bundle.candidates[: self.settings.max_candidates]

        for cand in candidate_list:
            cand_img_url = cand.image or cand.thumbnail
            if not cand_img_url:
                continue

            cand_id = f"cand-{cand.position}"
            try:
                # Retrieve candidate image bytes
                cand_bytes, cand_sha256 = CandidateDownloader.download_image(
                    cand_img_url,
                    mock_override_bytes=mock_candidate_image_bytes,
                )
                
                # Save candidate image and metadata to run bundle
                cand_img_path = candidates_dir / f"{cand_id}.image"
                with open(cand_img_path, "wb") as f:
                    f.write(cand_bytes)

                with open(candidates_dir / f"{cand_id}.metadata.json", "w", encoding="utf-8") as f:
                    json.dump(cand.model_dump(), f, indent=2)

                # Decode candidate image safely
                cand_bgr, _, _ = ImageGuard.validate_and_decode_bytes(cand_bytes)
                cand_faces, cand_raw_faces = self.face_matcher.detect_faces(cand_bgr)

                if len(cand_faces) == 0 or cand_raw_faces is None:
                    continue

                # Compare all faces in candidate image with query face
                for f_idx, c_raw_face in enumerate(cand_raw_faces):
                    c_emb = self.face_matcher.encode_face(cand_bgr, c_raw_face)
                    similarity = self.face_matcher.compare_embeddings(
                        query_embedding,
                        c_emb,
                        metric=self.settings.face_match_metric,
                    )
                    
                    if similarity > best_overall_score:
                        best_overall_score = similarity
                        best_candidate_info = {
                            "candidate": cand,
                            "candidateId": cand_id,
                            "candidateImageSha256": cand_sha256,
                            "candidateImageUrl": cand_img_url,
                            "candidateFaceCount": len(cand_faces),
                            "bestCandidateFaceIndex": f_idx,
                            "bestCandidateBoundingBoxPx": cand_faces[f_idx].bounding_box_px,
                            "score": similarity,
                            "retrievedAt": datetime.now(timezone.utc).isoformat(),
                        }

                    # Check acceptance against frozen threshold policy
                    if similarity >= self.settings.face_match_threshold and accepted_candidate_data is None:
                        accepted_candidate_data = {
                            "candidate": cand,
                            "candidateId": cand_id,
                            "candidateImageSha256": cand_sha256,
                            "candidateImageUrl": cand_img_url,
                            "candidateFaceCount": len(cand_faces),
                            "bestCandidateFaceIndex": f_idx,
                            "bestCandidateBoundingBoxPx": cand_faces[f_idx].bounding_box_px,
                            "score": similarity,
                            "retrievedAt": datetime.now(timezone.utc).isoformat(),
                        }
            except Exception as e:
                # Log or tolerate candidate retrieval errors (e.g., 403 or blocked CDN)
                continue

        # If no single candidate crossed threshold, use best candidate info marked as unaccepted
        candidate_eval = accepted_candidate_data or best_candidate_info
        if not candidate_eval:
            raise PipelineExecutionError(
                PipelineErrorCode.FAILED_NO_ACCEPTED_CANDIDATE,
                "No faces could be retrieved or evaluated from the discovered search results.",
            )

        is_accepted = candidate_eval["score"] >= self.settings.face_match_threshold

        # Stage 9: Construct Evidence Manifest
        detector_info, recognizer_info = self.face_matcher.get_model_info()

        cand_obj: SearchCandidate = candidate_eval["candidate"]

        manifest = EvidenceManifest(
            schema="org.hhgoa.face-web-evidence/v1",
            evidenceNonce=ManifestBuilder.generate_nonce(),
            createdAt=datetime.now(timezone.utc).isoformat(),
            claim=ClaimEvidence(),
            consent=ConsentInfo(
                confirmed=True,
                scope="hh-goa-demo",
                recordSha256=consent_record_sha256,
            ),
            query=QueryEvidence(
                originalImageSha256=orig_sha256,
                searchImageSha256=search_sha256,
                detectedFaceCount=len(detected_faces),
                selectedFaceIndex=selected_idx,
                selectedBoundingBoxPx=selected_face.bounding_box_px,
                detectionScore=f"{selected_face.detection_score:.6f}",
            ),
            discovery=DiscoveryEvidence(
                provider=search_bundle.provider,
                executionMode=search_bundle.execution_mode,
                searchType=search_bundle.search_type,
                executedAt=search_bundle.executed_at,
                rawResponseSha256=search_bundle.raw_response_sha256,
                selectedResultPosition=cand_obj.position,
            ),
            candidate=CandidateEvidence(
                platform=cand_obj.platform,
                pageUrl=cand_obj.link,
                title=cand_obj.title,
                candidateImageUrl=candidate_eval["candidateImageUrl"],
                candidateImageSha256=candidate_eval["candidateImageSha256"],
                retrievedAt=candidate_eval["retrievedAt"],
                pageReachable=True,
            ),
            comparison=ComparisonEvidence(
                detector=detector_info,
                recognizer=recognizer_info,
                metric=self.settings.face_match_metric,
                threshold=f"{self.settings.face_match_threshold:.6f}",
                thresholdPolicy="opencv-lfw-reference-uncalibrated",
                candidateFaceCount=candidate_eval["candidateFaceCount"],
                bestCandidateFaceIndex=candidate_eval["bestCandidateFaceIndex"],
                bestCandidateBoundingBoxPx=candidate_eval["bestCandidateBoundingBoxPx"],
                bestScore=f"{candidate_eval['score']:.6f}",
                accepted=is_accepted,
            ),
            software=SoftwareEvidence(
                applicationVersion="0.1.0",
                pythonVersion=platform.python_version(),
                opencvVersion=cv2.__version__,
            ),
        )

        # Stage 10: Canonicalize and Digest with RFC 8785 (JCS)
        canonical_bytes, evidence_hash, json_path, jcs_path, sha_path = ManifestBuilder.build_and_save(
            manifest, run_dir
        )

        # Stage 11: Blockchain Registration (if configured)
        attestation: Optional[AttestationSidecar] = None
        if self.blockchain_service.contract_address and self.blockchain_service.private_key:
            try:
                attestation = self.blockchain_service.register_evidence_hash(evidence_hash)
                BlockchainService.save_attestation(attestation, run_dir / "attestation.json")
            except Exception as e:
                # Record error but preserve evidence bundle
                print(f"[Warning] Blockchain registration skipped/failed: {e}")

        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "evidence_hash": evidence_hash,
            "accepted": is_accepted,
            "score": candidate_eval["score"],
            "threshold": self.settings.face_match_threshold,
            "page_url": cand_obj.link,
            "platform": cand_obj.platform,
            "search_mode": search_bundle.execution_mode,
            "attestation": attestation.model_dump() if attestation else None,
        }
