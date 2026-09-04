from __future__ import annotations

import pytest

from app.services.downloader import CandidateDownloader, DownloadSecurityError


def test_ip_filtering():
    # Public IPs allowed
    assert CandidateDownloader.is_ip_allowed("8.8.8.8") is True
    assert CandidateDownloader.is_ip_allowed("1.1.1.1") is True

    # Private / Localhost / Link-local / Cloud metadata rejected
    assert CandidateDownloader.is_ip_allowed("127.0.0.1") is False
    assert CandidateDownloader.is_ip_allowed("10.0.0.5") is False
    assert CandidateDownloader.is_ip_allowed("192.168.1.100") is False
    assert CandidateDownloader.is_ip_allowed("172.16.0.50") is False
    assert CandidateDownloader.is_ip_allowed("169.254.169.254") is False
    assert CandidateDownloader.is_ip_allowed("::1") is False


def test_disallowed_schemes():
    with pytest.raises(DownloadSecurityError, match="Disallowed URL scheme"):
        CandidateDownloader.validate_url("file:///etc/passwd")

    with pytest.raises(DownloadSecurityError, match="Disallowed URL scheme"):
        CandidateDownloader.validate_url("ftp://server.example/image.png")

    with pytest.raises(DownloadSecurityError, match="credentials"):
        CandidateDownloader.validate_url("https://admin:secret@site.com/image.jpg")


def test_mock_download_override(sample_jpeg_bytes: bytes):
    data, sha = CandidateDownloader.download_image(
        "https://example-mock.invalid/image.jpg",
        mock_override_bytes=sample_jpeg_bytes,
    )
    assert data == sample_jpeg_bytes
    assert len(sha) == 64
