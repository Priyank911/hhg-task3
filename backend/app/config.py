from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Search provider configuration
    search_provider: str = Field(default="mock", alias="SEARCH_PROVIDER")
    serpapi_api_key: str | None = Field(default=None, alias="SERPAPI_API_KEY")

    # Local face models
    yunet_model_path: str = Field(
        default="models/face_detection_yunet_2023mar.onnx",
        alias="YUNET_MODEL_PATH",
    )
    sface_model_path: str = Field(
        default="models/face_recognition_sface_2021dec.onnx",
        alias="SFACE_MODEL_PATH",
    )
    face_match_metric: str = Field(default="cosine", alias="FACE_MATCH_METRIC")
    face_match_threshold: float = Field(default=0.363, alias="FACE_MATCH_THRESHOLD")

    # Blockchain EVM configuration
    rpc_url: str = Field(default="http://127.0.0.1:8545", alias="RPC_URL")
    chain_id: int = Field(default=31337, alias="CHAIN_ID")
    registry_address: str | None = Field(default=None, alias="REGISTRY_ADDRESS")
    attester_private_key: str | None = Field(default=None, alias="ATTESTER_PRIVATE_KEY")

    # Operational settings
    runs_dir: str = Field(default="runs", alias="RUNS_DIR")
    max_candidates: int = Field(default=20, alias="MAX_CANDIDATES")
    retention_hours: int = Field(default=24, alias="RETENTION_HOURS")

    def resolve_path(self, rel_or_abs_path: str) -> Path:
        """Resolve a path relative to repository root if not absolute."""
        p = Path(rel_or_abs_path)
        if p.is_absolute():
            return p
        # Assuming execution from repo root or backend dir
        cwd = Path.cwd()
        if (cwd / p).exists() or (cwd / "models").exists():
            return cwd / p
        if (cwd.parent / p).exists():
            return cwd.parent / p
        return cwd / p


def get_settings() -> Settings:
    return Settings()
