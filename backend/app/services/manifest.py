from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any, Tuple
import rfc8785

from app.schemas import EvidenceManifest


class ManifestError(Exception):
    pass


class ManifestBuilder:
    @staticmethod
    def generate_nonce() -> str:
        """Generates a cryptographically strong 128-bit random nonce in hex."""
        return secrets.token_hex(16)

    @classmethod
    def canonicalize(cls, manifest_dict: dict[str, Any]) -> bytes:
        """
        Produces deterministic canonical JSON bytes conforming to RFC 8785 (JCS).
        """
        try:
            return rfc8785.dumps(manifest_dict)
        except Exception as e:
            raise ManifestError(f"RFC 8785 canonicalization error: {e}") from e

    @classmethod
    def calculate_evidence_hash(cls, canonical_bytes: bytes) -> str:
        """
        Calculates SHA-256 digest over canonical bytes and returns formatted '0x<64-hex>'.
        """
        raw_hash = hashlib.sha256(canonical_bytes).hexdigest().lower()
        return f"0x{raw_hash}"

    @classmethod
    def build_and_save(
        cls,
        manifest: EvidenceManifest,
        output_dir: Path,
    ) -> Tuple[bytes, str, Path, Path, Path]:
        """
        Saves manifest.json, manifest.jcs, manifest.sha256 in the run directory.
        Returns (canonical_bytes, evidence_hash_0x, json_path, jcs_path, sha_path).
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest_dict = manifest.model_dump(by_alias=True)

        # 1. Save standard formatted manifest.json
        json_path = output_dir / "manifest.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(manifest_dict, f, indent=2)

        # 2. Compute canonical JCS bytes
        canonical_bytes = cls.canonicalize(manifest_dict)
        jcs_path = output_dir / "manifest.jcs"
        with open(jcs_path, "wb") as f:
            f.write(canonical_bytes)

        # 3. Compute SHA-256 evidence hash
        evidence_hash = cls.calculate_evidence_hash(canonical_bytes)
        sha_path = output_dir / "manifest.sha256"
        with open(sha_path, "w", encoding="utf-8") as f:
            f.write(f"{evidence_hash}\n")

        return canonical_bytes, evidence_hash, json_path, jcs_path, sha_path

    @classmethod
    def verify_manifest_integrity(cls, manifest_path: Path) -> Tuple[bool, str, bytes, dict[str, Any]]:
        """
        Loads manifest.json, validates against schema, canonicalizes, and computes hash.
        Returns (is_valid, computed_hash_0x, canonical_bytes, loaded_dict).
        """
        if not manifest_path.exists():
            raise ManifestError(f"Manifest file not found: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                raise ManifestError(f"Invalid JSON in manifest file: {e}") from e

        # Validate schema
        try:
            parsed = EvidenceManifest.model_validate(data)
            validated_dict = parsed.model_dump(by_alias=True)
        except Exception as e:
            raise ManifestError(f"Manifest schema validation failed: {e}") from e

        canonical_bytes = cls.canonicalize(validated_dict)
        computed_hash = cls.calculate_evidence_hash(canonical_bytes)

        return True, computed_hash, canonical_bytes, validated_dict
