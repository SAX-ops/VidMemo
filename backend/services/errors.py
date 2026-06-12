"""
Friendly error handling for video URL parsing.

yt-dlp raises raw, technical errors like:
    "ERROR: [BiliBili] 1mAAmzqEf: Unable to download webpage:
     HTTP Error 404: Not Found (caused by <HTTPError 404: Not Found>)"

That text confuses end users. This module classifies those errors into
human-readable Chinese messages with stable error codes the frontend can
key on for styling / analytics.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """A user-facing parse error.

    Attributes:
        code: stable machine-readable identifier (e.g. ``video_not_found``)
        message: Chinese, end-user-safe description of the problem
        http_status: HTTP status code to return to the client
    """

    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# --- regex patterns for extracting hints from yt-dlp's raw error string ---

# HTTP status code anywhere in the message, e.g. "HTTP Error 404"
_HTTP_CODE_RE = re.compile(r"HTTP\s+Error\s+(\d{3})", re.IGNORECASE)

# yt-dlp tags the failing extractor in square brackets, e.g. "[BiliBili] 1mAAmzqEf:"
_EXTRACTOR_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_]+)\]")

# Network / connectivity keywords (case-insensitive substring match)
_NETWORK_KEYWORDS = (
    "connection",
    "timed out",
    "timeout",
    "network is unreachable",
    "name or service not known",
    "temporary failure in name resolution",
    "ssl",
)


# --- mapping of (platform, http_code) → (code, message) -------------------

def _platform_label(platform: Optional[str]) -> str:
    """Map a yt-dlp extractor name to a user-facing Chinese label."""
    if not platform:
        return "该平台"
    table = {
        "BiliBili": "B站",
        "Youtube": "YouTube",
        "TikTok": "TikTok",
        "Instagram": "Instagram",
        "Twitter": "X (Twitter)",
        "Weibo": "微博",
        "Xiaohongshu": "小红书",
        "Douyin": "抖音",
        "Facebook": "Facebook",
        "Vimeo": "Vimeo",
    }
    return table.get(platform, platform)


def _classify_platform_http(platform: Optional[str], http_code: int) -> Optional[ParseError]:
    """Return a ParseError for known (platform, http_code) pairs, else None."""

    if http_code == 404:
        if platform == "BiliBili":
            return ParseError(
                "video_not_found",
                "视频链接无效或视频已被删除。B站链接应为 https://www.bilibili.com/video/BVxxxxxxxxx 这种完整格式。",
            )
        return ParseError(
            "video_not_found",
            "视频链接无效或视频已被删除,请检查链接是否完整、是否过期。",
        )

    if http_code == 403:
        if platform == "BiliBili":
            return ParseError(
                "auth_required",
                "该视频需要登录 B站 才能访问。请在 Firefox 登录 bilibili.com 后重新尝试。",
            )
        return ParseError(
            "auth_required",
            f"该视频需要登录 {_platform_label(platform)} 才能访问。请在浏览器登录后再试。",
        )

    if http_code == 412:
        if platform == "BiliBili":
            return ParseError(
                "anti_scraping",
                "B站启用了反爬限制。请在 Firefox 登录 bilibili.com 后重新尝试。",
            )
        return ParseError(
            "access_denied",
            f"{_platform_label(platform)} 拒绝了访问请求,请检查链接或稍后重试。",
        )

    if http_code in (429, 503):
        return ParseError(
            "rate_limited",
            f"{_platform_label(platform)} 暂时限流,请稍等几秒后重试。",
        )

    if http_code in (401, 407):
        return ParseError(
            "auth_required",
            f"需要登录 {_platform_label(platform)} 才能访问此视频。",
        )

    return None


# --- the public classifier ------------------------------------------------

def classify_parse_error(e: Exception, url: str) -> ParseError:
    """Convert any exception raised during URL parsing into a ParseError.

    The original exception is logged at WARNING level with its full repr
    so operators can still see the underlying cause.
    """

    logger.warning("[parse_error] url=%r raw_error=%r", url, str(e))

    raw = str(e) or ""
    lower = raw.lower()

    # 1. Pre-validation: URL format (the user gave us nothing or garbage)
    stripped = (url or "").strip()
    if not stripped:
        return ParseError("empty_url", "请输入视频链接。")

    if not stripped.lower().startswith(("http://", "https://")):
        return ParseError(
            "invalid_url_format",
            "链接格式不正确,请输入以 http:// 或 https:// 开头的完整网址。",
        )

    # 2. yt-dlp can't even recognize the URL as a supported site
    if "no suitable extractor" in lower or "unsupported url" in lower:
        return ParseError(
            "unsupported_url",
            "暂不支持此链接。请尝试 YouTube、B站、抖音、TikTok 等平台。",
        )

    # 3. Network-level errors (DNS, TCP, TLS, timeouts)
    if any(k in lower for k in _NETWORK_KEYWORDS):
        return ParseError(
            "network_error",
            "网络连接失败,请检查网络后重试。",
        )

    # 4. HTTP error codes — check both the raw error and any chained cause
    http_match = _HTTP_CODE_RE.search(raw)
    if not http_match:
        # yt-dlp sometimes puts the code in the chained "caused by" line,
        # but it's also in the main message. Search again to be safe.
        http_match = _HTTP_CODE_RE.search(repr(e))

    if http_match:
        http_code = int(http_match.group(1))
        extractor_match = _EXTRACTOR_RE.search(raw) or _EXTRACTOR_RE.search(repr(e))
        platform = extractor_match.group(1) if extractor_match else None

        classified = _classify_platform_http(platform, http_code)
        if classified is not None:
            return classified

        # Unknown HTTP code — give a generic but informative message
        return ParseError(
            "http_error",
            f"{_platform_label(platform)} 返回 HTTP {http_code},链接可能无效或暂时无法访问。",
        )

    # 5. yt-dlp "Video unavailable" or similar textual signals
    if "video unavailable" in lower or "video is unavailable" in lower:
        return ParseError(
            "video_unavailable",
            "视频不可用(可能被删除、设为私有或所在地区不可访问)。",
        )
    if "private video" in lower:
        return ParseError(
            "video_private",
            "该视频为私享视频,无法解析。",
        )
    if "sign in" in lower or "login required" in lower:
        return ParseError(
            "auth_required",
            f"需要登录 {_platform_label(None)} 才能访问此视频。",
        )

    # 6. Fallback: keep the message short and human-friendly
    return ParseError(
        "parse_failed",
        "解析失败,请检查链接是否完整、有效,或稍后重试。",
    )
