from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.config import Settings
from app.pipeline import EvidencePipeline, PipelineErrorCode, PipelineExecutionError
from app.services.manifest import ManifestBuilder


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        search_provider="mock",
        yunet_model_path="models/face_detection_yunet_2023mar.onnx",
        sface_model_path="models/face_recognition_sface_2021dec.onnx",
        face_match_metric="cosine",
        face_match_threshold=0.363,
        rpc_url="http://127.0.0.1:8545",
        chain_id=31337,
        registry_address=None,
        attester_private_key=None,
        runs_dir=str(tmp_path / "runs"),
        max_candidates=5,
        retention_hours=24,
    )


def test_pipeline_consent_gate(test_settings: Settings, sample_temp_image: Path):
    pipeline = EvidencePipeline(test_settings)
    with pytest.raises(PipelineExecutionError) as exc_info:
        pipeline.run(
            input_image_path=sample_temp_image,
            consent_confirmed=False,
        )
    assert exc_info.value.code == PipelineErrorCode.FAILED_NO_CONSENT


def test_pipeline_no_face_fails(test_settings: Settings, tmp_path: Path):
    blank_img = tmp_path / "blank.jpg"
    import cv2
    import numpy as np
    cv2.imwrite(str(blank_img), np.zeros((200, 200, 3), dtype=np.uint8))

    pipeline = EvidencePipeline(test_settings)
    with pytest.raises(PipelineExecutionError) as exc_info:
        pipeline.run(
            input_image_path=blank_img,
            consent_confirmed=True,
        )
    assert exc_info.value.code == PipelineErrorCode.FAILED_NO_FACE


def test_mock_e2e_pipeline(test_settings: Settings):
    query_fixture = Path(__file__).parent / "fixtures" / "query.jpg"
    candidate_fixture = Path(__file__).parent / "fixtures" / "candidate.jpg"
    
    if not query_fixture.exists():
        pytest.skip("Test query face fixture not downloaded yet.")

    pipeline = EvidencePipeline(test_settings)
    cand_bytes = candidate_fixture.read_bytes()

    result = pipeline.run(
        input_image_path=query_fixture,
        face_index=0,
        consent_confirmed=True,
        search_provider_override="mock",
        mock_candidate_image_bytes=cand_bytes,
        custom_run_id="test-e2e-run",
    )

    assert result["run_id"] == "test-e2e-run"
    assert result["search_mode"] == "mock"
    assert result["evidence_hash"].startswith("0x")
    assert len(result["evidence_hash"]) == 66
    assert result["accepted"] is True
    assert result["score"] >= 0.363

    run_dir = Path(result["run_dir"])
    assert (run_dir / "consent.json").exists()
    assert (run_dir / "query-annotated.jpg").exists()
    assert (run_dir / "search-request.json").exists()
    assert (run_dir / "search-response.raw.json").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "manifest.jcs").exists()
    assert (run_dir / "manifest.sha256").exists()

    # Verify manifest integrity independently
    is_valid, computed_hash, _, _ = ManifestBuilder.verify_manifest_integrity(run_dir / "manifest.json")
    assert is_valid is True
    assert computed_hash == result["evidence_hash"]
