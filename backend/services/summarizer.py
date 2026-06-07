"""AI 视频总结模块：字幕提取 + LLM 总结 + Mock + 缓存。"""

import os
import re
import tempfile
from typing import Optional

import httpx
from yt_dlp import YoutubeDL


def _is_bilibili_url(url: str) -> bool:
    return "bilibili.com" in url or "b23.tv" in url


def _time_to_seconds(time_str: str) -> float:
    """HH:MM:SS.mmm → 秒数。"""
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def _parse_vtt(filepath: str) -> list[dict]:
    """Parse a VTT file into [{start, end, text}, ...]. Strips HTML tags; dedups duplicates globally."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    segments: list[dict] = []
    blocks = re.split(r"\n\n+", content)
    time_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
    )

    seen_texts: set[str] = set()
    for block in blocks:
        lines = block.strip().split("\n")
        time_match = None
        text_lines: list[str] = []
        for line in lines:
            m = time_pattern.search(line)
            if m:
                time_match = m
            elif time_match and line.strip() and not line.strip().isdigit():
                clean = re.sub(r"<[^>]+>", "", line.strip())
                if clean:
                    text_lines.append(clean)

        if time_match and text_lines:
            text = " ".join(text_lines)
            if text in seen_texts:
                continue
            seen_texts.add(text)
            segments.append({
                "start": round(_time_to_seconds(time_match.group(1)), 2),
                "end": round(_time_to_seconds(time_match.group(2)), 2),
                "text": text,
            })

    return segments


PREFERRED_LANGS = ["zh-Hans", "zh", "zh-CN"]


def _pick_best_subtitle(
    manual_subs: dict, auto_subs: dict, target_lang: str = "zh"
) -> tuple[str, Optional[str], str, bool]:
    """Pick the best subtitle for `target_lang` with language fallback.

    Returns (lang, url, type, is_target_language). `is_target_language` is False
    when the chosen subtitle is not in the target language.
    """
    target_prefix = target_lang.split("-")[0]  # "zh" or "en"
    preferred_for_target = [target_lang] + PREFERRED_LANGS if target_lang.startswith("zh") else [target_lang]

    for lang in preferred_for_target:
        if lang in manual_subs:
            url = _first_format_url(manual_subs[lang])
            if url:
                return lang, url, "manual", True

    for lang in preferred_for_target:
        if lang in auto_subs:
            url = _first_format_url(auto_subs[lang])
            if url:
                return lang, url, "auto", True

    # Language fallback: any other language
    if manual_subs:
        first_lang = next(iter(manual_subs))
        url = _first_format_url(manual_subs[first_lang])
        if url:
            return first_lang, url, "manual", first_lang.split("-")[0] == target_prefix

    if auto_subs:
        first_lang = next(iter(auto_subs))
        url = _first_format_url(auto_subs[first_lang])
        if url:
            return first_lang, url, "auto", first_lang.split("-")[0] == target_prefix

    return "", None, "none", False


def _first_format_url(formats: list) -> Optional[str]:
    """Pick the best format URL from a yt-dlp subtitle list (json3 > srv3 > vtt > ttml)."""
    preferred = ["json3", "srv3", "vtt", "ttml"]
    for pref in preferred:
        for fmt in formats:
            if fmt.get("ext") == pref:
                return fmt.get("url")
    return formats[0].get("url") if formats else None


def _extract_bilibili(url: str) -> dict:
    """Extract CC / AI subtitles from a Bilibili video via the dm/view API.

    Returns the same shape as `_pick_best_subtitle`: {has_subtitle, language, ...}.
    """
    empty = {
        "has_subtitle": False, "language": "", "subtitle_type": "none",
        "is_target_language": True, "fallback_mode": None, "segments": [], "full_text": "",
    }
    try:
        m = re.search(r"(BV[a-zA-Z0-9]+)", url)
        if not m:
            return empty
        bvid = m.group(1)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }
        view = httpx.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=headers, timeout=15,
        ).json().get("data", {})
        cid, aid = view.get("cid"), view.get("aid")
        if not cid or not aid:
            return empty
        dm = httpx.get(
            f"https://api.bilibili.com/x/v2/dm/view?aid={aid}&oid={cid}&type=1",
            headers=headers, timeout=15,
        ).json().get("data", {})
        subtitle_list = dm.get("subtitle", {}).get("subtitles", [])
        if not subtitle_list:
            return empty
        # Pick first zh/manual
        best = subtitle_list[0]
        for s in subtitle_list:
            if s.get("lan", "") in ("zh", "zh-Hans"):
                best = s
                break
        sub_url = best.get("subtitle_url", "")
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url
        if sub_url.startswith("http://"):
            sub_url = "https://" + sub_url[7:]
        if not sub_url:
            return empty
        sub_json = httpx.get(sub_url, headers=headers, timeout=15).json()
        body = sub_json.get("body", [])
        segments = [
            {
                "start": round(item.get("from", 0), 2),
                "end": round(item.get("to", 0), 2),
                "text": item.get("content", "").strip(),
            }
            for item in body
            if item.get("content", "").strip()
        ]
        full_text = " ".join(s["text"] for s in segments)
        return {
            "has_subtitle": True,
            "language": best.get("lan", "zh"),
            "subtitle_type": "auto" if best.get("lan", "").startswith("ai-") else "manual",
            "is_target_language": True,
            "fallback_mode": None,
            "segments": segments,
            "full_text": full_text,
        }
    except Exception:
        return empty


MAX_SUBTITLE_CHARS = 15000


class SubtitleExtractor:
    """Public entry point: extract subtitles from any supported video URL."""

    def extract(self, url: str, language: str = "zh") -> dict:
        if _is_bilibili_url(url):
            result = _extract_bilibili(url)
            if result["has_subtitle"]:
                if len(result["full_text"]) > MAX_SUBTITLE_CHARS:
                    result["full_text"] = result["full_text"][:MAX_SUBTITLE_CHARS]
                return result

        info = _get_video_info(url)
        manual = (info.get("subtitles") or {})
        auto = (info.get("automatic_captions") or {})
        manual = {k: v for k, v in manual.items() if k != "danmaku"}

        lang, sub_url, sub_type, is_target = _pick_best_subtitle(manual, auto, language)
        if not sub_url:
            return {
                "has_subtitle": False, "language": "", "subtitle_type": "none",
                "is_target_language": False, "fallback_mode": None,
                "segments": [], "full_text": "",
            }

        segments = _download_and_parse(url, lang, sub_type)
        full_text = " ".join(s["text"] for s in segments)
        if len(full_text) > MAX_SUBTITLE_CHARS:
            full_text = full_text[:MAX_SUBTITLE_CHARS]

        return {
            "has_subtitle": True,
            "language": lang,
            "subtitle_type": sub_type,
            "is_target_language": is_target,
            "fallback_mode": None,
            "segments": segments,
            "full_text": full_text,
        }


def _get_video_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "extract_flat": False, "writesubtitles": True, "writeautomaticsub": True,
        "skip_download": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("无法解析该视频链接")
    return info


def _download_and_parse(url: str, lang: str, sub_type: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ydl_opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True,
            "writesubtitles": sub_type == "manual",
            "writeautomaticsub": sub_type == "auto",
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": os.path.join(tmp_dir, "subtitle"),
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        vtt_files = [f for f in os.listdir(tmp_dir) if f.endswith(".vtt")]
        if not vtt_files:
            return []
        return _parse_vtt(os.path.join(tmp_dir, vtt_files[0]))


def build_summarizer():
    """Return a real VideoSummarizer or a MockSummarizer based on env."""
    if os.getenv("SUMMARY_MOCK", "false").lower() == "true":
        return MockSummarizer()
    return VideoSummarizer()


class VideoSummarizer:
    def __init__(self):
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set (or set SUMMARY_MOCK=true)")
        base_url = os.getenv("SUMMARY_BASE_URL") or None
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
        self.timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))


class MockSummarizer:
    """Canned summary emitter for offline dev and tests."""

    DELAY_MS = int(os.getenv("SUMMARY_MOCK_DELAY_MS", "50"))

    BODY = (
        "## 视频概述\n"
        "这是一个 mock 视频总结，用于离线开发调试。\n\n"
        "## 内容大纲\n"
        "本视频包含若干章节，mock 模式下不会调用真实 LLM。\n\n"
        "## 核心知识要点\n"
        "1. Mock 模式不消耗 token\n"
        "2. 默认每个 token 间隔 50ms\n"
        "3. 总结时间可由 SUMMARY_MOCK_DELAY_MS 调整\n\n"
        "## 总结\n"
        "Mock 总结由 SUMMARY_MOCK=true 启用，便于无 API key 时调试前端。\n\n"
        "```json\n"
        '{"chapters": [{"time": 0, "title": "开场"}, {"time": 90, "title": "主题展开"}, {"time": 300, "title": "总结回顾"}]}\n'
        "```\n"
    )
    CHAPTERS = [
        {"time": 0, "title": "开场"},
        {"time": 90, "title": "主题展开"},
        {"time": 300, "title": "总结回顾"},
    ]

