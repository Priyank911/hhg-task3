from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class PipelineState(str, Enum):
    CREATED = "CREATED"
    CONSENTED = "CONSENTED"
    QUERY_VALIDATED = "QUERY_VALIDATED"
    FACES_DETECTED = "FACES_DETECTED"
    FACE_SELECTED = "FACE_SELECTED"
    QUERY_ENCODED = "QUERY_ENCODED"
    SEARCH_UPLOADED = "SEARCH_UPLOADED"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"
    CANDIDATES_RETRIEVED = "CANDIDATES_RETRIEVED"
    CANDIDATES_COMPARED = "CANDIDATES_COMPARED"
    CANDIDATE_ACCEPTED = "CANDIDATE_ACCEPTED"
    EVIDENCE_BUILT = "EVIDENCE_BUILT"
    EVIDENCE_HASHED = "EVIDENCE_HASHED"
    ANCHORED = "ANCHORED"
    VERIFIED = "VERIFIED"


class PipelineErrorCode(str, Enum):
    FAILED_NO_CONSENT = "FAILED_NO_CONSENT"
    FAILED_INVALID_IMAGE = "FAILED_INVALID_IMAGE"
    FAILED_NO_FACE = "FAILED_NO_FACE"
    FAILED_FACE_SELECTION_REQUIRED = "FAILED_FACE_SELECTION_REQUIRED"
    FAILED_SEARCH_AUTH = "FAILED_SEARCH_AUTH"
    FAILED_SEARCH_QUOTA = "FAILED_SEARCH_QUOTA"
    FAILED_NO_SOCIAL_RESULT = "FAILED_NO_SOCIAL_RESULT"
    FAILED_NO_ACCEPTED_CANDIDATE = "FAILED_NO_ACCEPTED_CANDIDATE"
    FAILED_CHAIN_WRITE = "FAILED_CHAIN_WRITE"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"


class DetectedFace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    bounding_box_px: list[int] = Field(description="[x, y, width, height]")
    landmarks_px: list[list[int]] = Field(description="5 facial landmarks [[x, y], ...]")
    detection_score: float
    quality_warnings: list[str] = Field(default_factory=list)


class ConsentInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = True
    scope: str = "hh-goa-demo"
    recordSha256: str


class QueryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    originalImageSha256: str
    searchImageSha256: str
    detectedFaceCount: int
    selectedFaceIndex: int
    selectedBoundingBoxPx: list[int]
    detectionScore: str


class DiscoveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    executionMode: str = Field(description="'live' or 'mock'")
    searchType: str = Field(description="'exact_matches' or 'visual_matches'")
    executedAt: str
    rawResponseSha256: str
    selectedResultPosition: int


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    pageUrl: str
    socialUrl: str | None = None
    title: str
    candidateImageUrl: str
    candidateImageSha256: str
    retrievedAt: str
    pageReachable: bool


class ModelArtifactInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    artifact: str
    artifactSha256: str


class ComparisonEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector: ModelArtifactInfo
    recognizer: ModelArtifactInfo
    metric: str = "cosine"
    threshold: str
    thresholdPolicy: str
    candidateFaceCount: int
    bestCandidateFaceIndex: int
    bestCandidateBoundingBoxPx: list[int]
    bestScore: str
    accepted: bool


class SoftwareEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicationVersion: str
    pythonVersion: str
    opencvVersion: str


class ClaimEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "candidate-face-similarity"
    description: str = "A selected face was compared locally with faces in a live-search candidate."


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="org.hhgoa.face-web-evidence/v1", alias="schema")
    evidenceNonce: str
    createdAt: str
    claim: ClaimEvidence = Field(default_factory=ClaimEvidence)
    consent: ConsentInfo
    query: QueryEvidence
    discovery: DiscoveryEvidence
    candidate: CandidateEvidence
    comparison: ComparisonEvidence
    software: SoftwareEvidence


class AttestationSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidenceHash: str
    chainId: str
    contractAddress: str
    transactionHash: str
    blockNumber: str
    registrant: str
    receiptStatus: str


class VerificationReport(BaseModel):
    manifestSchema: str
    manifestIntegrity: str
    artifactIntegrity: str
    onChainRegistration: str
    attesterValid: bool
    receiptValid: bool
    evidenceIntegrity: str
    identityProven: bool = False
    details: list[str] = Field(default_factory=list)
