from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ConsentService:
    @staticmethod
    def create_consent_record(
        confirmed: bool,
        scope: str = "hh-goa-demo",
        purpose: str = "Demonstration of facial reverse image discovery and cryptographic verification",
        retention_hours: int = 24,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("Explicit consent must be confirmed by the operator before processing biometrics.")

        record = {
            "schema": "org.hhgoa.face-web-evidence.consent/v1",
            "subjectId": f"subject-{uuid.uuid4().hex[:12]}",
            "scope": scope,
            "purpose": purpose,
            "confirmed": True,
            "biometricProcessingPermitted": True,
            "thirdPartySearchPermitted": True,
            "blockchainHashRegistrationPermitted": True,
            "retentionHours": retention_hours,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        return record

    @staticmethod
    def hash_consent_record(record: dict[str, Any]) -> str:
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @classmethod
    def save_consent(cls, record: dict[str, Any], output_path: Path) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return cls.hash_consent_record(record)
