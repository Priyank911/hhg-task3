from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from app.schemas import (
    CandidateEvidence,
    ClaimEvidence,
    ComparisonEvidence,
    ConsentInfo,
    DiscoveryEvidence,
    EvidenceManifest,
    ModelArtifactInfo,
    QueryEvidence,
    SoftwareEvidence,
)
from app.services.manifest import ManifestBuilder, ManifestError


@pytest.fixture
def valid_manifest_dict() -> dict:
    manifest = EvidenceManifest(
        schema="org.hhgoa.face-web-evidence/v1",
        evidenceNonce="0123456789abcdef0123456789abcdef",
        createdAt="2026-09-04T07:00:00Z",
        claim=ClaimEvidence(),
        consent=ConsentInfo(confirmed=True, scope="hh-goa-demo", recordSha256="a" * 64),
        query=QueryEvidence(
            originalImageSha256="b" * 64,
            searchImageSha256="c" * 64,
            detectedFaceCount=1,
            selectedFaceIndex=0,
            selectedBoundingBoxPx=[10, 10, 100, 100],
            detectionScore="0.995000",
        ),
        discovery=DiscoveryEvidence(
            provider="serpapi-google-lens",
            executionMode="live",
            searchType="exact_matches",
            executedAt="2026-09-04T07:00:01Z",
            rawResponseSha256="d" * 64,
            selectedResultPosition=1,
        ),
        candidate=CandidateEvidence(
            platform="reddit",
            pageUrl="https://reddit.com/r/test/comments/123",
            title="Sample Post Title",
            candidateImageUrl="https://preview.redd.it/test.jpg",
            candidateImageSha256="e" * 64,
            retrievedAt="2026-09-04T07:00:02Z",
            pageReachable=True,
        ),
        comparison=ComparisonEvidence(
            detector=ModelArtifactInfo(name="YuNet", artifact="yunet.onnx", artifactSha256="f" * 64),
            recognizer=ModelArtifactInfo(name="SFace", artifact="sface.onnx", artifactSha256="0" * 64),
            metric="cosine",
            threshold="0.363000",
            thresholdPolicy="opencv-lfw-reference-uncalibrated",
            candidateFaceCount=1,
            bestCandidateFaceIndex=0,
            bestCandidateBoundingBoxPx=[15, 15, 95, 95],
            bestScore="0.825000",
            accepted=True,
        ),
        software=SoftwareEvidence(
            applicationVersion="0.1.0",
            pythonVersion="3.12.4",
            opencvVersion="4.9.0",
        ),
    )
    return manifest.model_dump(by_alias=True)


def test_jcs_canonicalization_order_independence(valid_manifest_dict: dict):
    # Dict 1: normal order
    canonical_1 = ManifestBuilder.canonicalize(valid_manifest_dict)
    hash_1 = ManifestBuilder.calculate_evidence_hash(canonical_1)

    # Dict 2: reversed keys order
    reversed_dict = dict(reversed(list(valid_manifest_dict.items())))
    canonical_2 = ManifestBuilder.canonicalize(reversed_dict)
    hash_2 = ManifestBuilder.calculate_evidence_hash(canonical_2)

    assert canonical_1 == canonical_2
    assert hash_1 == hash_2
    assert hash_1.startswith("0x")
    assert len(hash_1) == 66  # 0x + 64 hex characters


def test_tamper_detection(tmp_path: Path, valid_manifest_dict: dict):
    orig_manifest = EvidenceManifest.model_validate(valid_manifest_dict)
    _, orig_hash, json_path, _, _ = ManifestBuilder.build_and_save(orig_manifest, tmp_path)

    # Load and verify original
    is_valid, computed_hash, _, _ = ManifestBuilder.verify_manifest_integrity(json_path)
    assert is_valid is True
    assert computed_hash == orig_hash

    # Tamper with the score
    tampered_data = copy.deepcopy(valid_manifest_dict)
    tampered_data["comparison"]["bestScore"] = "0.999999"
    
    tampered_path = tmp_path / "tampered_manifest.json"
    with open(tampered_path, "w", encoding="utf-8") as f:
        json.dump(tampered_data, f, indent=2)

    _, tampered_hash, _, _ = ManifestBuilder.verify_manifest_integrity(tampered_path)
    assert tampered_hash != orig_hash
