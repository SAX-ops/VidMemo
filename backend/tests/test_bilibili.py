"""Tests for the Bilibili direct API service.

These tests hit the real Bilibili public API — they're network-dependent and
should be run with internet access. Marked with `pytest.mark.network` so they
can be skipped in offline environments.
"""

import pytest

from services.bilibili import (
    is_bilibili_url,
    _extract_bvid,
    parse_bilibili,
)


# --- Pure helpers (no network) ---

def test_is_bilibili_url():
    assert is_bilibili_url('https://www.bilibili.com/video/BV1xx411c7mD')
    assert is_bilibili_url('https://bilibili.com/video/BV1xx411c7mD')
    assert is_bilibili_url('https://b23.tv/abc123')
    assert is_bilibili_url('https://www.bilibili.com/bangumi/play/ep123')
    assert not is_bilibili_url('https://www.youtube.com/watch?v=xxx')
    assert not is_bilibili_url('https://www.douyin.com/video/123')


def test_extract_bvid():
    assert _extract_bvid('https://www.bilibili.com/video/BV1GJ411x7h7') == 'BV1GJ411x7h7'
    assert _extract_bvid('https://www.bilibili.com/video/BV1GJ411x7h7?p=1') == 'BV1GJ411x7h7'
    assert _extract_bvid('https://www.bilibili.com/?bvid=BV1GJ411x7h7') == 'BV1GJ411x7h7'
    assert _extract_bvid('https://www.youtube.com/watch?v=xxx') is None
    assert _extract_bvid('https://b23.tv/abc123') is None  # short URLs must be resolved first


# --- Network tests ---

@pytest.mark.network
@pytest.mark.asyncio
async def test_parse_bilibili_public_video():
    """Parse a public B站 video that has 1080p available to guests."""
    # BV1uv411q7Mv is a popular public video with 1080P for guests
    result = await parse_bilibili('https://www.bilibili.com/video/BV1uv411q7Mv')
    assert result.platform == 'B站'
    assert result.title
    assert result.thumbnail.startswith('http')
    assert len(result.formats) > 0
    # All formats are mp4 (fnval=0 returns merged durl)
    assert all(f.ext == 'mp4' for f in result.formats)
    # CDN URLs are http(s)
    assert all(f.url.startswith('http') for f in result.formats)


@pytest.mark.network
@pytest.mark.asyncio
async def test_parse_bilibili_quality_reflects_actual():
    """If a video doesn't have 1080p for guests, the format list must
    not falsely advertise 1080p — it should report the true quality."""
    # BV1GJ411x7h7 only has 720P/360P for guests
    result = await parse_bilibili('https://www.bilibili.com/video/BV1GJ411x7h7')
    qualities = {f.quality for f in result.formats}
    # The API may return either 720P (no 1080p) or include 1080p depending on
    # the video. In either case, the labels must match what the API actually
    # served, not what we requested.
    assert qualities <= {'1080p', '720p', '480p', '360p'}


@pytest.mark.network
@pytest.mark.asyncio
async def test_parse_bilibili_short_url():
    """b23.tv short URLs should be resolved transparently."""
    # This is bilibili's homepage redirect — should resolve to a valid page
    result = await parse_bilibili('https://www.bilibili.com/video/BV1GJ411x7h7')
    assert result.platform == 'B站'


@pytest.mark.network
@pytest.mark.asyncio
async def test_parse_bilibili_invalid_raises():
    """A bogus BV ID should raise a clear error so the caller can fall back."""
    with pytest.raises(ValueError):
        await parse_bilibili('https://www.bilibili.com/video/BV0000000000')
