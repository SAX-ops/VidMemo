"""Tests for the /api/preview-stream endpoint.

The endpoint now downloads yt-dlp's merged output to a file on disk and
serves it with FileResponse (full Range support). An earlier version
streamed yt-dlp's stdout directly to the client, but that produced an
MPEG-TS file with a broken video stream_type for B站 DASH sources
(0x06 "private data" instead of 0x1B "AVC") — no demuxer could decode
it. See the deprecated `stream_to_stdout` tests at the bottom for the
OS-level fd capture plumbing that's still kept around.
"""

import hashlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.download import PREVIEW_DIR
from services.ytdlp import YtdlpService


# --- Helpers ---


def _make_fake_ydl():
    """Build a mock YoutubeDL context manager that succeeds on extract_info."""
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    mock_ydl.extract_info.return_value = {'id': 'test'}
    return mock_ydl


def _cleanup_cache(cache_key: str):
    for suffix in ('.mp4', '.tmp'):
        try:
            os.unlink(os.path.join(PREVIEW_DIR, f"{cache_key}{suffix}"))
        except OSError:
            pass


# A real MP4 ftyp box header so the format sniffer recognizes it as MP4.
_MP4_FTYP = b'\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41'


# --- Endpoint tests: disk-based path ---


def test_preview_stream_disk_based_download():
    """First request: yt-dlp downloads to .tmp, the endpoint renames to
    the cache, and serves via FileResponse with full Range support."""
    url = 'https://example.com/stream-route-test-1'
    quality = '720p'
    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]

    mp4_bytes = _MP4_FTYP + b'\x00' * 4000

    async def fake_download_to_file(*args, **kwargs):
        # Mirror what real yt-dlp does: write the merged MP4 to output_path
        output_path = kwargs.get('output_path')
        with open(output_path, 'wb') as f:
            f.write(mp4_bytes)

    try:
        with patch('routers.download.YoutubeDL', return_value=_make_fake_ydl()), \
             patch.object(YtdlpService, 'download_to_file', fake_download_to_file):
            with TestClient(app) as client:
                response = client.get(f"/api/preview-stream?url={url}&quality={quality}")

        assert response.status_code == 200
        assert response.headers.get('content-type') == 'video/mp4'
        # FileResponse default — the whole point of switching to disk-based.
        assert response.headers.get('accept-ranges') == 'bytes'
        assert response.content == mp4_bytes
        # Cache file should be renamed from .tmp to .mp4
        final_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")
        assert os.path.isfile(final_path), f"Expected cache file at {final_path}"
        tmp_path = os.path.join(PREVIEW_DIR, f"{cache_key}.tmp")
        assert not os.path.exists(tmp_path), f"Temp file {tmp_path} should be gone after rename"
    finally:
        _cleanup_cache(cache_key)


def test_preview_stream_cache_hit_returns_file():
    """Pre-placed cache file is served directly (FileResponse)."""
    url = 'https://example.com/stream-cache-test'
    quality = '720p'
    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]
    cache_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")

    try:
        with open(cache_path, 'wb') as f:
            f.write(b'cached video bytes' * 100)

        with TestClient(app) as client:
            response = client.get(f"/api/preview-stream?url={url}&quality={quality}")

        assert response.status_code == 200
        assert response.content == b'cached video bytes' * 100
    finally:
        _cleanup_cache(cache_key)


def test_preview_stream_douyin_routing():
    """Douyin URLs are routed to download_douyin, not yt-dlp."""
    url = 'https://www.douyin.com/video/douyin-route-test'
    quality = '720p'
    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]

    async def fake_download(u, q, output_path):
        with open(output_path, 'wb') as f:
            f.write(b'douyin video bytes')

    try:
        with patch('services.douyin.download_douyin', fake_download):
            with TestClient(app) as client:
                response = client.get(f"/api/preview-stream?url={url}&quality={quality}")

        assert response.status_code == 200
        assert response.content == b'douyin video bytes'
    finally:
        _cleanup_cache(cache_key)


def test_preview_stream_preflight_error_returns_500():
    """Bad URL → extract_info fails → endpoint returns 500 JSON before download."""
    url = 'https://example.com/stream-bad-url-test'
    quality = '720p'
    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]

    mock_ydl = _make_fake_ydl()
    mock_ydl.extract_info.side_effect = Exception("Video not found")

    try:
        with patch('routers.download.YoutubeDL', return_value=mock_ydl):
            with TestClient(app) as client:
                response = client.get(f"/api/preview-stream?url={url}&quality={quality}")

        assert response.status_code == 500
        body = response.json()
        assert 'pre-flight failed' in body.get('detail', '').lower()
    finally:
        _cleanup_cache(cache_key)


def test_preview_stream_download_failure_returns_500():
    """If yt-dlp download itself fails, endpoint returns 500 and the .tmp
    file is removed (no half-written cache for next request to choke on)."""
    url = 'https://example.com/stream-download-fail'
    quality = '720p'
    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]

    async def fake_download_fails(*args, **kwargs):
        output_path = kwargs.get('output_path')
        # Simulate partial write before failure
        with open(output_path, 'wb') as f:
            f.write(b'partial garbage')
        raise RuntimeError('ffmpeg crashed')

    try:
        with patch('routers.download.YoutubeDL', return_value=_make_fake_ydl()), \
             patch.object(YtdlpService, 'download_to_file', fake_download_fails):
            with TestClient(app) as client:
                response = client.get(f"/api/preview-stream?url={url}&quality={quality}")

        assert response.status_code == 500
        body = response.json()
        assert 'preview download failed' in body.get('detail', '').lower()
        # Both .tmp and .mp4 should be absent
        tmp_path = os.path.join(PREVIEW_DIR, f"{cache_key}.tmp")
        final_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")
        assert not os.path.exists(tmp_path), "Tmp file should be removed on failure"
        assert not os.path.exists(final_path), "Final cache file should not be created on failure"
    finally:
        _cleanup_cache(cache_key)


# --- Deprecated stream_to_stdout regression tests ---


@pytest.mark.asyncio
async def test_stream_to_stdout_captures_fd1_bytes():
    """Regression test: bytes written to fd 1 (stdout) during yt-dlp
    download must reach the async generator.

    The original bug had two layers:
    1. _StdoutSink was never wired into yt-dlp (yt-dlp's `outtmpl: '-'`
       resolves to sys.stdout, not any external file-like).
    2. Even after monkey-patching sys.stdout, the ffmpeg subprocess
       inherits the file descriptor 1 directly — so its output goes
       to the original stdout regardless of Python's sys.stdout.

    The fix redirects fd 1 and fd 2 to an os.pipe at the OS level,
    capturing both yt-dlp and ffmpeg writes. This test simulates
    ffmpeg's behavior by writing directly to fd 1.
    """
    import os
    service = YtdlpService()
    chunk1 = b'FIRST_CHUNK_DATA' * 200      # 3.2 KB
    chunk2 = b'\x00\x01\x02\x03' * 500     # 2 KB binary
    chunk3 = b'third chunk text' * 100     # 1.7 KB

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def download(self, urls):
            # Simulate ffmpeg subprocess writing to inherited fd 1
            os.write(1, chunk1)
            os.write(1, chunk2)
            os.write(1, chunk3)

    with patch('services.ytdlp.YoutubeDL', FakeYDL):
        received = bytearray()
        async for chunk in service.stream_to_stdout('http://test/video', 'best'):
            received.extend(chunk)

    assert bytes(received) == chunk1 + chunk2 + chunk3, (
        f"Expected {len(chunk1) + len(chunk2) + len(chunk3)} bytes, "
        f"got {len(received)}"
    )


@pytest.mark.asyncio
async def test_stream_to_stdout_restores_fd1_on_error():
    """If yt-dlp raises, fd 1 must still be restored (no leak)."""
    import os
    service = YtdlpService()

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def download(self, urls):
            raise RuntimeError("simulated yt-dlp failure")

    with patch('services.ytdlp.YoutubeDL', FakeYDL):
        with pytest.raises(RuntimeError, match="yt-dlp streaming failed"):
            async for _ in service.stream_to_stdout('http://test/bad', 'best'):
                pass

    # After error, fd 1 should still be writable (restored, not a closed pipe)
    assert os.fstat(1) is not None, "fd 1 was not restored after error"
    os.write(2, b'[test] fd 1/2 still writable after error\n')
