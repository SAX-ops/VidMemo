"""
Bilibili (B站) direct API service — fetches video info and download URLs
using Bilibili's public web APIs. No cookies required for public videos.

Public streams are accessible via `try_look=1` (guest mode).
Uses `fnval=0` to get merged MP4 (durl format) instead of DASH to avoid
audio/video sync issues — this also gives 1080P for guest users.
"""

import re
from typing import Optional

import httpx

from models import VideoInfo, FormatInfo

API_BASE = "https://api.bilibili.com"
VIEW_API = f"{API_BASE}/x/web-interface/view"
PLAYURL_API = f"{API_BASE}/x/player/playurl"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
REFERER = "https://www.bilibili.com/"

# Bilibili's qn codes (1080P, 720P, 480P, 360P).
# The actual quality returned may be lower than requested if the requested
# tier isn't available — the API's `accept_quality` field tells us what's
# actually accessible. The `quality` field in the response is the true
# quality of the returned URL.
QN_TO_LABEL = {
    80: "1080p",
    64: "720p",
    32: "480p",
    16: "360p",
}


def is_bilibili_url(url: str) -> bool:
    return 'bilibili.com' in url or 'b23.tv' in url


def _extract_bvid(url: str) -> Optional[str]:
    """Extract BV ID from a bilibili.com URL."""
    m = re.search(r'/video/(BV[a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]bvid=(BV[a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    return None


async def _resolve_short_url(url: str) -> Optional[str]:
    """Resolve a b23.tv short URL via redirect to the full bilibili.com URL."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        resp = await client.get(url, headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        })
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp.headers.get("location")
    return None


def _request_headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
    }


async def _fetch_view(bvid: str) -> dict:
    """Fetch video metadata from /x/web-interface/view."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(
            VIEW_API,
            params={"bvid": bvid},
            headers=_request_headers(),
        )
        data = resp.json()
    if data.get("code") != 0:
        raise ValueError(
            f"Bilibili view API error: code={data.get('code')} message={data.get('message')}"
        )
    return data["data"]


async def _fetch_playurl(bvid: str, cid: int, qn: int) -> Optional[dict]:
    """Fetch play URL for a specific quality (qn). Returns None on failure.

    `try_look=1` enables guest access (no cookies needed).
    `fnval=0` requests the legacy `durl` format (single merged MP4) so we
    don't have to deal with DASH A/V merge.
    """
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": qn,
        "fnval": 0,
        "fnver": 0,
        "try_look": 1,
        "platform": "html5",
        "otype": "json",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(PLAYURL_API, params=params, headers=_request_headers())
        data = resp.json()
    if data.get("code") != 0:
        return None
    return data.get("data")


async def parse_bilibili(url: str) -> VideoInfo:
    """Parse a Bilibili video URL and return VideoInfo.

    Tries the public web API with guest mode (try_look=1) first. Throws
    on failure so the caller can fall back to yt-dlp.
    """
    # 1. Resolve b23.tv short links
    if 'b23.tv' in url:
        resolved = await _resolve_short_url(url)
        if not resolved:
            raise ValueError(f"Failed to resolve short URL: {url}")
        url = resolved

    # 2. Extract BV ID
    bvid = _extract_bvid(url)
    if not bvid:
        raise ValueError(f"Cannot extract BV ID from URL: {url}")

    # 3. Fetch metadata
    view = await _fetch_view(bvid)
    title = view.get("title", "Unknown")
    duration = view.get("duration", 0)
    thumbnail = view.get("pic", "")

    pages = view.get("pages", [])
    if not pages:
        raise ValueError("Bilibili video has no pages")
    cid = pages[0].get("cid")
    if not cid:
        raise ValueError("Bilibili video has no cid")

    # 4. Discover available quality tiers (highest first).
    # Bilibili returns a fresh CDN URL per request — we collect one URL
    # per quality that's actually available to the guest session. The API's
    # `accept_quality` field lists all qualities the guest can access, but
    # the `quality` field on the actual response is the true quality of
    # the returned URL (which may be lower than requested).
    formats = []
    seen_urls = set()
    # Iterate from highest qn to lowest so the first one with a result wins
    for qn in sorted(QN_TO_LABEL.keys(), reverse=True):
        try:
            data = await _fetch_playurl(bvid, cid, qn)
        except Exception as e:
            print(f'[bilibili] playurl qn={qn} failed: {e}')
            continue
        if not data:
            continue

        durl = data.get("durl", [])
        if not durl:
            continue

        url_info = durl[0]
        play_url = url_info.get("url")
        size = url_info.get("size")
        if not play_url or play_url in seen_urls:
            continue

        # The returned `quality` is the true quality of this URL
        actual_qn = data.get("quality", qn)
        quality_label = QN_TO_LABEL.get(actual_qn, f"{actual_qn}p")

        if any(f.quality == quality_label for f in formats):
            continue

        seen_urls.add(play_url)
        formats.append(FormatInfo(
            quality=quality_label,
            ext="mp4",
            size=size,
            url=play_url,
        ))

    if not formats:
        raise ValueError("No available video formats found via direct API")

    max_q = formats[0].quality

    return VideoInfo(
        title=title,
        thumbnail=thumbnail,
        duration=duration or None,
        platform="B站",
        url=url,
        max_quality=max_q,
        formats=formats,
    )


async def download_bilibili(
    url: str,
    quality: str,
    output_path: str,
    on_progress: Optional[callable] = None,
) -> None:
    """Download a Bilibili video at the specified quality.

    Fetches a fresh play URL (CDN URLs expire quickly), then streams the
    video to disk. The Referer header is required by Bilibili's CDN.

    on_progress(downloaded_bytes, total_bytes) is called after each chunk
    so the caller can update the task dict with progress/speed/eta.
    """
    info = await parse_bilibili(url)

    target = None
    for f in info.formats:
        if f.quality == quality:
            target = f
            break
    if not target and info.formats:
        target = info.formats[0]

    if not target or not target.url:
        raise ValueError("No downloadable video URL found")

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        async with client.stream("GET", target.url, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or (target.size or 0)
            downloaded = 0
            import time as _time
            start_time = _time.monotonic()
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(256 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)
