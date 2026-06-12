"""
Douyin (抖音) video service — bypasses yt-dlp by calling Douyin's Web API directly.

yt-dlp's Douyin extractor is broken since 2024-04 (missing a_bogus parameter).
This module generates the required anti-scraping parameters programmatically.
"""

import re
import asyncio
from typing import Optional
from urllib.parse import urlencode

import httpx

from .abogus import ABogus
from models import VideoInfo, FormatInfo

DOUYIN_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _extract_aweme_id(url: str) -> Optional[str]:
    """Extract the numeric video ID from a Douyin URL."""
    # https://www.douyin.com/video/7530216968151715129
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    # https://www.douyin.com/note/7530216968151715129 (图文)
    m = re.search(r'/note/(\d+)', url)
    if m:
        return m.group(1)
    # Short URL: https://v.douyin.com/xxxxx/ — need to resolve redirect
    return None


async def _resolve_short_url(url: str) -> Optional[str]:
    """Resolve a v.douyin.com short URL to get the aweme_id."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        location = resp.headers.get("location", "")
        return _extract_aweme_id(location)


async def _get_ttwid() -> str:
    """Get a ttwid session cookie from Douyin's ttwid service."""
    body = {
        "region": "cn",
        "aid": 6383,
        "needFid": True,
        "service": "www.douyin.com",
        "migrate_info": {"ticket": "", "source": "node"},
        "cb_url_protocol": "https",
        "union": True,
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        resp = await client.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
            json=body,
        )
        # ttwid is in Set-Cookie header
        for name, value in resp.headers.multi_items():
            if name.lower() == "set-cookie" and "ttwid=" in value:
                # Extract ttwid value from cookie string
                import re
                m = re.search(r'ttwid=([^;]+)', value)
                if m:
                    return m.group(1)
    raise ValueError("Failed to get ttwid from Douyin service")


def _build_api_params(aweme_id: str) -> dict:
    return {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "pc_client_type": "1",
        "version_code": "190500",
        "version_name": "19.5.0",
        "cookie_enabled": "true",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_online": "true",
        "engine_name": "Blink",
        "os_name": "Windows",
        "os_version": "10",
        "platform": "PC",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_version": "125.0.0.0",
        "engine_version": "125.0.0.0",
        "cpu_core_num": "12",
        "device_memory": "8",
        "aweme_id": aweme_id,
    }


async def parse_douyin(url: str) -> VideoInfo:
    """Parse a Douyin video URL and return VideoInfo."""
    aweme_id = _extract_aweme_id(url)
    if not aweme_id:
        aweme_id = await _resolve_short_url(url)
    if not aweme_id:
        raise ValueError(f"Cannot extract video ID from URL: {url}")

    # Get ttwid and generate a_bogus in parallel
    ttwid = await _get_ttwid()
    if not ttwid:
        raise ValueError("Failed to get Douyin session cookie (ttwid)")

    params = _build_api_params(aweme_id)
    a_bogus = ABogus().get_value(params)
    params["a_bogus"] = a_bogus

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.douyin.com/",
        "Cookie": f"ttwid={ttwid}",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(DOUYIN_API, params=params, headers=headers)
        if not resp.content:
            # Empty body means anti-scraping blocked us — retry with fresh session
            ttwid = await _get_ttwid()
            params = _build_api_params(aweme_id)
            params["a_bogus"] = ABogus().get_value(params)
            headers["Cookie"] = f"ttwid={ttwid}"
            resp = await client.get(DOUYIN_API, params=params, headers=headers)
        if not resp.content:
            raise ValueError("Douyin API returned empty response (anti-scraping blocked)")
        data = resp.json()

    detail = data.get("aweme_detail")
    if not detail:
        raise ValueError("Douyin API returned no video data (aweme_detail is null)")

    # Extract video info
    title = detail.get("desc", "Douyin Video")
    duration = detail.get("duration", 0)  # milliseconds
    if duration:
        duration = duration // 1000  # convert to seconds

    # Thumbnail
    cover = detail.get("video", {}).get("cover", {})
    thumbnail = ""
    if cover.get("url_list"):
        thumbnail = cover["url_list"][0]

    # Video formats
    video_info = detail.get("video", {})
    play_addr = video_info.get("play_addr", {})
    play_url_list = play_addr.get("url_list", [])

    formats = []
    if play_url_list:
        # Douyin provides a single combined video+audio stream
        # Try different quality URLs
        width = play_addr.get("width", 0)
        height = play_addr.get("height", 0)

        # Add the default play URL
        formats.append(FormatInfo(
            quality=f"{height}p" if height else "720p",
            ext="mp4",
            url=play_url_list[0],
        ))

        # Check for bit_rate alternatives (different qualities)
        bit_rate = video_info.get("bit_rate", [])
        seen_qualities = {f"{height}p" if height else "720p"}
        for br in bit_rate:
            br_height = br.get("play_addr", {}).get("height", 0)
            br_urls = br.get("play_addr", {}).get("url_list", [])
            quality = f"{br_height}p"
            if br_urls and quality not in seen_qualities:
                seen_qualities.add(quality)
                formats.append(FormatInfo(
                    quality=quality,
                    ext="mp4",
                    url=br_urls[0],
                ))

    # Sort by quality (highest first)
    def _quality_num(f: FormatInfo) -> int:
        return int(f.quality.replace("p", "")) if f.quality.endswith("p") else 0

    formats.sort(key=_quality_num, reverse=True)

    # Remove duplicates
    seen = set()
    unique_formats = []
    for f in formats:
        if f.quality not in seen:
            seen.add(f.quality)
            unique_formats.append(f)

    max_q = unique_formats[0].quality if unique_formats else "Unknown"

    return VideoInfo(
        title=title,
        thumbnail=thumbnail,
        duration=duration,
        platform="抖音",
        url=url,
        max_quality=max_q,
        formats=unique_formats[:10],
    )


async def download_douyin(
    url: str,
    quality: str,
    output_path: str,
    on_progress: Optional[callable] = None,
) -> None:
    """Download a Douyin video to a file.

    on_progress(downloaded_bytes, total_bytes) is called after each chunk
    so the caller can update the task dict with progress/speed/eta.
    """
    info = await parse_douyin(url)

    # Find the requested quality or closest match
    target = None
    for f in info.formats:
        if f.quality == quality:
            target = f
            break
    if not target and info.formats:
        target = info.formats[0]  # fallback to highest quality

    if not target or not target.url:
        raise ValueError("No downloadable video URL found")

    # Download the video
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.douyin.com/",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        async with client.stream("GET", target.url, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or (target.size or 0)
            downloaded = 0
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)
