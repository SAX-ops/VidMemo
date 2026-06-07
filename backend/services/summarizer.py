"""AI 视频总结模块：字幕提取 + LLM 总结 + Mock + 缓存。"""

import re
from typing import Optional

import httpx


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
