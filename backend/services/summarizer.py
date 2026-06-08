"""AI 视频总结模块：字幕提取 + LLM 总结 + Mock + 缓存。"""

import json
import logging
import os
import re
import tempfile
from typing import Optional

import httpx
from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


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

    def summarize_stream(
        self,
        subtitle_text: str,
        language: str = "zh",
        has_subtitle: bool = True,
        video_meta: Optional[dict] = None,
    ):
        """Stream summary tokens from the LLM."""
        if has_subtitle:
            prompt = _build_standard_prompt(subtitle_text, language, (video_meta or {}).get("duration", 0))
        else:
            meta = video_meta or {}
            prompt = _build_fallback_prompt(
                title=meta.get("title", ""),
                platform=meta.get("platform", ""),
                duration=meta.get("duration", 0),
                language=language,
            )
        system = "你是一个专业的视频内容分析助手，擅长提取关键信息并生成结构化的总结。"
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            temperature=0.7,
            max_tokens=4096,
            timeout=self.timeout,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


class MockSummarizer:
    """Canned summary emitter for offline dev and tests."""

    DELAY_MS = int(os.getenv("SUMMARY_MOCK_DELAY_MS", "50"))

    BODY = (
        "## 视频概述\n"
        "这是一个 mock 视频总结，用于离线开发调试。\n\n"
        "## 总结\n"
        "Mock 总结由 SUMMARY_MOCK=true 启用，便于无 API key 时调试前端。\n\n"
        "## 视频大纲\n"
        "```json\n"
        '{"outline": [\n'
        '  {"title": "开场", "timestamp": 0, "part_outline": [\n'
        '    {"timestamp": 0, "content": "项目背景介绍"},\n'
        '    {"timestamp": 30, "content": "目标受众说明"}\n'
        '  ]},\n'
        '  {"title": "主题展开", "timestamp": 90, "part_outline": [\n'
        '    {"timestamp": 95, "content": "核心功能演示"},\n'
        '    {"timestamp": 180, "content": "技术细节讲解"}\n'
        '  ]},\n'
        '  {"title": "总结回顾", "timestamp": 300, "part_outline": [\n'
        '    {"timestamp": 305, "content": "关键要点回顾"},\n'
        '    {"timestamp": 330, "content": "扩展资源推荐"}\n'
        '  ]}\n'
        ']}\n'
        "```\n"
    )
    OUTLINE = [
        {"title": "开场", "timestamp": 0, "part_outline": [
            {"timestamp": 0, "content": "项目背景介绍"},
            {"timestamp": 30, "content": "目标受众说明"},
        ]},
        {"title": "主题展开", "timestamp": 90, "part_outline": [
            {"timestamp": 95, "content": "核心功能演示"},
            {"timestamp": 180, "content": "技术细节讲解"},
        ]},
        {"title": "总结回顾", "timestamp": 300, "part_outline": [
            {"timestamp": 305, "content": "关键要点回顾"},
            {"timestamp": 330, "content": "扩展资源推荐"},
        ]},
    ]

    def summarize_stream(self, subtitle_text: str, language: str = "zh", **kwargs):
        """Yield the canned body character by character with a small inter-token delay."""
        import time
        body = self.BODY
        i = 0
        while i < len(body):
            # Yield 1-3 chars at a time to simulate tokenization
            chunk = body[i:i+2]
            yield chunk
            i += 2
            if self.DELAY_MS > 0:
                time.sleep(self.DELAY_MS / 1000.0)


SUMMARY_PROMPT_STANDARD = """你是视频内容分析专家。请对以下视频字幕进行结构化深度总结，使用 {language} 输出。

视频时长：{duration} 秒。

## 严格遵守的输出格式

使用 markdown 二级标题 `##` 划分主章节。每个主章节按下面的固定顺序输出，不要增删。

```
## 视频概述
（2-3 句话概括视频主题和核心内容）

## 总结
（1-2 句话整体评价）

## 视频大纲
（在 markdown 结束后另起一行，输出 JSON 代码块 —— **这是视频的核心结构化数据**。
  顶层 key 是 `"outline"`，对应一个数组，元素是"章节"，每个章节又内嵌一个
  `part_outline` 数组列出该章节下的关键要点，**每个要点都有自己的时间戳**，用户
  可以点击直接跳到该时间点。）

```json
{{"outline": [
  {{
    "title": "章节一标题",
    "timestamp": 0,
    "part_outline": [
      {{"timestamp": 5, "content": "要点 1 的内容"}},
      {{"timestamp": 30, "content": "要点 2 的内容"}}
    ]
  }},
  {{
    "title": "章节二标题",
    "timestamp": 90,
    "part_outline": [
      {{"timestamp": 95, "content": "要点 3 的内容"}}
    ]
  }}
]}}
```
```

## 硬性要求

- 主章节必须用 `## ` 二级标题，**不要**写成编号列表（不要写 `1. 视频概述`）
- 视频大纲的 JSON 必须能被 `json.loads` 解析：
  - 外层必须是完整 `{{"outline": [...]}}`，**不要**漏写开头的 `{{`
  - 顶层 key 必须是 `"outline"`，**不是** `"chapters"`
  - 每个章节必须有 `title`（字符串）、`timestamp`（整数，秒）、`part_outline`（数组）
  - `timestamp` 是整数（不加引号），`title`/`content` 是字符串（加双引号）
  - 无尾逗号、无注释
- 每个章节必须至少有 1 个 `part_outline` 要点（空 `part_outline` 会被丢弃）
- 每个要点的 `timestamp` 必须在视频时长内（`0 ≤ timestamp ≤ {duration}`）
- 章节数量按视频时长动态调整：
  - 时长 < 600 秒（< 10 分钟）：2-4 个章节
  - 时长 600-1800 秒（10-30 分钟）：4-6 个章节
  - 时长 > 1800 秒（> 30 分钟）：6-8 个章节
- 要点数量：每章 2-5 个 `part_outline` 条目

## 常见错误（请避免）

- ❌ `1. 视频概述` → ✅ `## 视频概述`
- ❌ `"chapters": [...]` → ✅ `"outline": [...]`
- ❌ `outline": [...]` （缺外层 `{{`）→ ✅ `{{"outline": [...]}}`
- ❌ `"time": 0`（章节用 `time`）→ ✅ `"timestamp": 0`
- ❌ 把视频大纲直接接到标题文字后面 → ✅ 用 ```json ``` 代码块包裹

---
视频字幕内容：
{subtitle}
"""


SUMMARY_PROMPT_FALLBACK = """请基于以下视频的元数据生成一个**简短的**总结（不超过 200 字），使用 {language} 输出。

⚠️ 该视频没有可用的字幕，以下总结**仅基于标题和元数据推测**，精度有限。建议用户观看原视频获取准确信息。

视频标题：{title}
视频平台：{platform}
视频时长：{duration} 秒（{duration_min} 分钟）

## 输出结构

### 1. 视频概述
（基于标题推测视频主题，1-2 句话，**显式声明这是基于标题的猜测**）

### 2. 内容大纲
（**直接说明无法获取字幕内容，请用户观看视频**）

### 3. 总结
（提醒用户此总结基于元数据，强烈建议观看原视频）

### 4. 视频大纲
输出一个**空数组**：
```json
{{"outline": []}}
```
"""


def _lang_hint(language: str) -> str:
    return "中文" if language.startswith("zh") else "与原文相同的语言"


def _build_standard_prompt(subtitle_text: str, language: str, duration: int) -> str:
    truncated = subtitle_text[:15000]
    return SUMMARY_PROMPT_STANDARD.format(
        language=_lang_hint(language),
        duration=duration or 0,
        subtitle=truncated,
    )


def _build_fallback_prompt(title: str, platform: str, duration: int, language: str) -> str:
    return SUMMARY_PROMPT_FALLBACK.format(
        language=_lang_hint(language),
        title=title or "（未知）",
        platform=platform or "（未知）",
        duration=duration or 0,
        duration_min=(duration or 0) // 60,
    )


def parse_outline_json(full_body: str) -> tuple[str, list[dict]]:
    """Split an LLM response into (markdown_body, outline).

    The outline is a 2-level structure extracted from the first ```json ... ```
    block in the body, matching biliscope/B站's `conclusion` API shape:

        outline: [
          {
            "title": str,
            "timestamp": int,         # seconds
            "part_outline": [
              {"timestamp": int, "content": str},
              ...
            ]
          },
          ...
        ]

    Behavior:
    - No JSON fence → return (full_body, [])
    - Malformed JSON / wrong top-level shape → WARNING + (full_body, [])
    - Section with empty/missing `part_outline` is dropped (avoids empty
      chapter rows in the UI)
    - Field types are coerced (string `timestamp` → int) so a sloppy LLM
      output still parses
    - Never raises — a 90-second LLM call should not be wasted on a trailing
      comma
    """
    pattern = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
    match = pattern.search(full_body)
    if not match:
        return full_body, []

    md = (full_body[:match.start()] + full_body[match.end():]).strip()
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
        outline_raw = parsed.get("outline", [])
        if not isinstance(outline_raw, list):
            raise ValueError("outline is not a list")
        clean: list[dict] = []
        for sec in outline_raw:
            if not isinstance(sec, dict):
                continue
            try:
                title = str(sec["title"])
                timestamp = int(sec["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            parts_raw = sec.get("part_outline", [])
            if not isinstance(parts_raw, list) or not parts_raw:
                # Drop sections with no parts (avoids empty chapter rows)
                continue
            parts: list[dict] = []
            for p in parts_raw:
                if not isinstance(p, dict):
                    continue
                try:
                    p_ts = int(p["timestamp"])
                    p_content = str(p["content"]).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if not p_content:
                    continue
                parts.append({"timestamp": p_ts, "content": p_content})
            if not parts:
                continue
            clean.append({"title": title, "timestamp": timestamp, "part_outline": parts})
        return md, clean
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("parse_outline_json: invalid JSON in LLM response, returning empty outline: %s", e)
        return full_body, []

