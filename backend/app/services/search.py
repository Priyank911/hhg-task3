from __future__ import annotations

import abc
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel, Field


class SearchCandidate(BaseModel):
    position: int
    title: str
    link: str
    source: Optional[str] = None
    thumbnail: Optional[str] = None
    image: Optional[str] = None
    platform: str = "web"
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    match_type: str = "visual_matches"


class SearchResultBundle(BaseModel):
    execution_mode: str  # "live" or "mock"
    provider: str
    search_type: str  # "exact_matches" or "visual_matches"
    executed_at: str
    raw_response_bytes: bytes
    raw_response_sha256: str
    candidates: List[SearchCandidate]

    @property
    def social_links(self) -> List[str]:
        social_candidates = [
            candidate
            for candidate in self.candidates
            if candidate.platform != "web" and is_direct_social_url(candidate.link, candidate.platform)
        ]
        social_candidates.sort(key=_social_candidate_sort_key)
        return [candidate.link for candidate in social_candidates[:5]]


class SearchError(Exception):
    pass


class SearchQuotaError(SearchError):
    pass


class SearchAuthError(SearchError):
    pass


def classify_social_platform(url: str) -> str:
    """Classifies a URL into a social media platform or web."""
    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower()
        if any(d in domain for d in ["reddit.com", "redd.it"]):
            return "reddit"
        if any(d in domain for d in ["instagram.com", "instagr.am"]):
            return "instagram"
        if any(d in domain for d in ["twitter.com", "x.com", "t.co"]):
            return "x"
        if any(d in domain for d in ["facebook.com", "fb.com", "fb.watch"]):
            return "facebook"
        if any(d in domain for d in ["linkedin.com", "licdn.com"]):
            return "linkedin"
        if any(d in domain for d in ["tiktok.com"]):
            return "tiktok"
        if any(d in domain for d in ["youtube.com", "youtu.be"]):
            return "youtube"
        if any(d in domain for d in ["pinterest.com", "pin.it"]):
            return "pinterest"
        if any(d in domain for d in ["github.com"]):
            return "github"
    except Exception:
        pass
    return "web"


def is_direct_social_url(url: str, platform: str) -> bool:
    """Return whether a URL points to a post/profile rather than a discovery page."""
    path = urlparse(url).path.rstrip("/").lower()
    excluded_prefixes = {
        "instagram": ("/popular", "/explore", "/accounts", "/about", "/direct"),
        "facebook": ("/watch", "/marketplace", "/groups"),
        "youtube": ("/results", "/feed", "/channel"),
        "linkedin": ("/pulse", "/jobs", "/search"),
    }
    if any(path.startswith(prefix) for prefix in excluded_prefixes.get(platform, ())):
        return False
    if platform == "reddit":
        return "/comments/" in path
    if platform == "x":
        return "/status/" in path

    direct_prefixes = {
        "instagram": ("/p/", "/reel/", "/tv/"),
        "facebook": ("/posts/", "/permalink/", "/videos/"),
        "linkedin": ("/feed/update/",),
        "tiktok": ("/@",),
        "youtube": ("/watch", "/shorts/"),
        "pinterest": ("/pin/",),
    }
    return any(path.startswith(prefix) for prefix in direct_prefixes.get(platform, ()))


def _social_candidate_sort_key(candidate: SearchCandidate) -> tuple[int, int, int]:
    return (
        0 if candidate.match_type == "exact_matches" else 1,
        0 if is_direct_social_url(candidate.link, candidate.platform) else 1,
        candidate.position,
    )


class SearchAdapter(abc.ABC):
    @abc.abstractmethod
    def search(self, search_image_bytes: bytes) -> SearchResultBundle:
        raise NotImplementedError


class SerpApiLensAdapter(SearchAdapter):
    SERPAPI_IMAGE_URL = "https://serpapi.com/image"
    SERPAPI_SEARCH_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str):
        if not api_key:
            raise SearchAuthError("SerpApi API key is missing. Set SERPAPI_API_KEY environment variable.")
        self.api_key = api_key

    def search(self, search_image_bytes: bytes) -> SearchResultBundle:
        executed_at = datetime.now(timezone.utc).isoformat()
        
        # 1. Upload search image to SerpApi Image API
        try:
            with httpx.Client(timeout=30.0) as client:
                files = {"image": ("search_image.jpg", search_image_bytes, "image/jpeg")}
                data = {"api_key": self.api_key}
                upload_resp = client.post(self.SERPAPI_IMAGE_URL, files=files, data=data)
        except Exception as e:
            raise SearchError(f"Failed to connect to SerpApi image upload endpoint: {e}") from e

        if upload_resp.status_code == 401 or upload_resp.status_code == 403:
            raise SearchAuthError(f"SerpApi authentication error: {upload_resp.text}")
        if upload_resp.status_code == 429:
            raise SearchQuotaError("SerpApi rate limit or quota exceeded.")
        if upload_resp.status_code != 200:
            raise SearchError(f"SerpApi image upload failed with status {upload_resp.status_code}: {upload_resp.text}")

        upload_json = upload_resp.json()
        image_id = upload_json.get("image_id")
        if not image_id:
            raise SearchError(f"No image_id returned from SerpApi: {upload_json}")

        # 2. Search exact_matches first
        raw_bytes, candidates, search_type = self._execute_search_type(image_id, "exact_matches")
        
        # 3. Also collect visual matches so an exact repost does not hide other sources.
        try:
            vm_raw_bytes, vm_candidates, vm_type = self._execute_search_type(image_id, "visual_matches")
            if len(vm_candidates) > 0:
                candidates = self._merge_candidates(candidates, vm_candidates)
                raw_bytes, search_type = vm_raw_bytes, vm_type
        except Exception:
            pass  # Keep exact matches if visual search encounters an error

        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        return SearchResultBundle(
            execution_mode="live",
            provider="serpapi-google-lens",
            search_type=search_type,
            executed_at=executed_at,
            raw_response_bytes=raw_bytes,
            raw_response_sha256=raw_sha256,
            candidates=candidates,
        )

    @staticmethod
    def _merge_candidates(
        primary: List[SearchCandidate], secondary: List[SearchCandidate]
    ) -> List[SearchCandidate]:
        seen_links = {candidate.link for candidate in primary}
        merged = list(primary)
        for candidate in secondary:
            if candidate.link not in seen_links:
                merged.append(candidate)
                seen_links.add(candidate.link)
        return merged

    def _execute_search_type(self, image_id: str, search_type: str) -> tuple[bytes, List[SearchCandidate], str]:
        params = {
            "engine": "google_lens",
            "image_id": image_id,
            "api_key": self.api_key,
            "type": search_type,
            "no_cache": "true",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(self.SERPAPI_SEARCH_URL, params=params)

        if resp.status_code == 401 or resp.status_code == 403:
            raise SearchAuthError(f"SerpApi authentication error: {resp.text}")
        if resp.status_code == 429:
            raise SearchQuotaError("SerpApi rate limit or quota exceeded.")
        if resp.status_code != 200:
            raise SearchError(f"SerpApi search request failed ({resp.status_code}): {resp.text}")

        raw_bytes = resp.content
        data = resp.json()

        candidates = self._parse_lens_response(data, search_type=search_type)
        return raw_bytes, candidates, search_type

    def _parse_lens_response(
        self, data: dict[str, Any], search_type: Optional[str] = None
    ) -> List[SearchCandidate]:
        candidates: List[SearchCandidate] = []
        
        # Check exact_matches or visual_matches keys
        raw_items = data.get("exact_matches") or data.get("visual_matches") or []
        for idx, item in enumerate(raw_items):
            link = item.get("link")
            if not link:
                continue

            title = item.get("title") or item.get("source") or f"Search result #{idx + 1}"
            source = item.get("source")
            thumbnail = item.get("thumbnail")
            image = item.get("original") or item.get("image") or thumbnail
            
            platform = classify_social_platform(link)

            candidates.append(
                SearchCandidate(
                    position=idx + 1,
                    title=title,
                    link=link,
                    source=source,
                    thumbnail=thumbnail,
                    image=image,
                    platform=platform,
                    image_width=item.get("image_width"),
                    image_height=item.get("image_height"),
                    match_type=search_type or ("exact_matches" if data.get("exact_matches") else "visual_matches"),
                )
            )

        return candidates


class MockSearchAdapter(SearchAdapter):
    def __init__(self, canned_response_bytes: Optional[bytes] = None, mock_candidates: Optional[List[SearchCandidate]] = None):
        self.canned_response_bytes = canned_response_bytes
        self.mock_candidates = mock_candidates

    def search(self, search_image_bytes: bytes) -> SearchResultBundle:
        executed_at = datetime.now(timezone.utc).isoformat()
        
        if self.mock_candidates is not None:
            candidates = self.mock_candidates
            raw_bytes = self.canned_response_bytes or json.dumps(
                {"mock": True, "results": [c.model_dump() for c in candidates]},
                indent=2,
            ).encode("utf-8")
        else:
            # Default deterministic mock response
            candidates = [
                SearchCandidate(
                    position=1,
                    title="Mock Verified Subject Profile Post",
                    link="https://www.reddit.com/r/developer/comments/mockpost/profile_update/",
                    source="Reddit",
                    thumbnail="https://example-mock.invalid/thumbnail.jpg",
                    image="https://example-mock.invalid/image.jpg",
                    platform="reddit",
                ),
                SearchCandidate(
                    position=2,
                    title="Visual Match Secondary Source",
                    link="https://www.instagram.com/p/MockPost123/",
                    source="Instagram",
                    thumbnail="https://example-mock.invalid/insta_thumb.jpg",
                    image="https://example-mock.invalid/insta_image.jpg",
                    platform="instagram",
                ),
            ]
            raw_bytes = json.dumps(
                {
                    "mock": True,
                    "search_metadata": {"status": "Success", "mode": "mock"},
                    "visual_matches": [
                        {
                            "position": c.position,
                            "title": c.title,
                            "link": c.link,
                            "source": c.source,
                            "thumbnail": c.thumbnail,
                        }
                        for c in candidates
                    ],
                },
                indent=2,
            ).encode("utf-8")

        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        return SearchResultBundle(
            execution_mode="mock",
            provider="mock",
            search_type="visual_matches",
            executed_at=executed_at,
            raw_response_bytes=raw_bytes,
            raw_response_sha256=raw_sha256,
            candidates=candidates,
        )
