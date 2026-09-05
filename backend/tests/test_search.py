from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.services.search import (
    MockSearchAdapter,
    SearchCandidate,
    SerpApiLensAdapter,
    classify_social_platform,
    is_direct_social_url,
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


def test_search_result_bundle_exposes_social_links():
    bundle = MockSearchAdapter(
        mock_candidates=[
            SearchCandidate(position=1, title="News match", link="https://news.example/article"),
            SearchCandidate(
                position=2,
                title="Social match",
                link="https://www.instagram.com/p/example/",
                platform="instagram",
            ),
        ]
    ).search(b"image")

    assert bundle.social_links == ["https://www.instagram.com/p/example/"]


def test_exact_social_link_is_preferred_over_visual_repost():
    bundle = MockSearchAdapter(
        mock_candidates=[
            SearchCandidate(
                position=1,
                title="Visual repost",
                link="https://www.instagram.com/p/repost/",
                platform="instagram",
                match_type="visual_matches",
            ),
            SearchCandidate(
                position=2,
                title="Exact post",
                link="https://www.instagram.com/p/original/",
                platform="instagram",
                match_type="exact_matches",
            ),
        ]
    ).search(b"image")

    assert bundle.social_links[0] == "https://www.instagram.com/p/original/"


def test_social_links_exclude_discovery_pages_and_limit_results():
    candidates = [
        SearchCandidate(
            position=index,
            title="Result",
            link=f"https://www.instagram.com/{path}",
            platform="instagram",
        )
        for index, path in enumerate(
            ["popular/topic/", "p/one/", "p/two/", "p/three/", "p/four/", "p/five/", "p/six/"],
            start=1,
        )
    ]
    bundle = MockSearchAdapter(mock_candidates=candidates).search(b"image")

    assert is_direct_social_url("https://www.instagram.com/p/one/", "instagram") is True
    assert is_direct_social_url("https://www.instagram.com/popular/topic/", "instagram") is False
    assert len(bundle.social_links) == 5
    assert all("/popular/" not in link for link in bundle.social_links)
    assert is_direct_social_url("https://x.com/user/status/123", "x") is True
    assert is_direct_social_url("https://x.com/user", "x") is False
