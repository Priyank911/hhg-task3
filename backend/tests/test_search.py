from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.services.search import (
    MockSearchAdapter,
    SearchCandidate,
    SerpApiLensAdapter,
    classify_social_platform,
)


def test_classify_social_platform():
    assert classify_social_platform("https://www.reddit.com/r/python/comments/123") == "reddit"
    assert classify_social_platform("https://instagram.com/p/abcdef") == "instagram"
    assert classify_social_platform("https://x.com/user/status/123456") == "x"
    assert classify_social_platform("https://twitter.com/user/status/123456") == "x"
    assert classify_social_platform("https://www.facebook.com/posts/123456") == "facebook"
    assert classify_social_platform("https://www.linkedin.com/feed/update/urn:li:activity:123") == "linkedin"
    assert classify_social_platform("https://tiktok.com/@user/video/123") == "tiktok"
    assert classify_social_platform("https://youtube.com/watch?v=123") == "youtube"
    assert classify_social_platform("https://example.com/blog/article") == "web"


def test_mock_search_adapter():
    adapter = MockSearchAdapter()
    dummy_bytes = b"fake_search_image_bytes"
    bundle = adapter.search(dummy_bytes)

    assert bundle.execution_mode == "mock"
    assert bundle.provider == "mock"
    assert len(bundle.raw_response_sha256) == 64
    assert len(bundle.candidates) >= 1
    assert any(c.platform == "reddit" for c in bundle.candidates)


def test_parse_lens_response():
    fixture_path = Path(__file__).parent / "fixtures" / "mock_search_response.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    adapter = SerpApiLensAdapter(api_key="test_key")
    candidates = adapter._parse_lens_response(data)

    assert len(candidates) == 1
    assert candidates[0].platform == "reddit"
    assert candidates[0].position == 1
    assert "reddit.com" in candidates[0].link
