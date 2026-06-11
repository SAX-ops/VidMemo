"""AI 视频总结模块：字幕提取 + LLM 总结 + Mock + 缓存。"""

import json
import logging
import os
import re
import tempfile
from collections.abc import Generator
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
        segments: Optional[list[dict]] = None,
        chapters: Optional[list[dict]] = None,
    ):
        """Stream summary tokens from the LLM.

        When *chapters* is provided (new architecture), the LLM only
        generates titles and summaries — timestamps come from the
        chapter dicts (sourced from subtitle segments, never from LLM).
        """
        if has_subtitle and chapters:
            # New architecture: LLM only generates titles + summaries
            prompt = _build_chapters_prompt(chapters, language)
        elif has_subtitle:
            prompt = _build_standard_prompt(
                subtitle_text, language,
                (video_meta or {}).get("duration", 0),
                segments=segments,
            )
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

你的输出必须严格按以下顺序，包含且仅包含三个 markdown 二级标题段落：

## 视频概述
（2-3 句话概括视频主题和核心内容）

## 总结
（1-2 句话整体评价）

## 视频大纲
```json
{{"outline": [{{"title": "章节一标题", "timestamp": 30, "part_outline": [{{"timestamp": 35, "content": "要点内容"}}]}}, {{"title": "章节二标题", "timestamp": 120, "part_outline": [{{"timestamp": 125, "content": "要点内容"}}]}}]}}
```

## 时间戳选取规则（最重要）

字幕内容按**话题窗口**组织，每个窗口格式为 `[MM:SS-MM:SS] 文本内容`，表示该时间段内的连续字幕。你必须**直接从窗口时间范围中选取**时间戳。

### 选取原则

1. **先通读所有窗口，识别话题分界线** — 在哪个窗口时间点话题发生了明显转变？那里就是章节边界
2. **章节时间戳 = 话题转变发生的窗口起始时间** — 不是话题首次提及的时间
3. **绝对不要自己编造时间戳** — 所有 timestamp 都必须来自字幕窗口的 `[MM:SS]` 部分
4. 章节和要点的时间戳必须**严格递增**，不能重叠或倒退

## 章节和要点数量

- 时长 < 600 秒：2-4 个章节，每章 2-4 个要点
- 时长 600-1800 秒：4-6 个章节，每章 2-5 个要点
- 时长 > 1800 秒：6-8 个章节，每章 2-5 个要点

## ⚠️ 章节必须均匀覆盖整个视频（最重要）

这是最容易犯的错误：**把多个章节堆在视频的开头或结尾，中间大片空白**。

规则：
1. **先看字幕窗口的总时间范围**，然后把整个时间范围等分为 N 段（N = 章节数）
2. **每个章节必须落在对应的时间段内** — 第1章在前 1/N，第2章在 1/N~2/N，依此类推
3. 第一个章节的时间戳应接近 0，最后一个章节的时间戳应接近 {duration} 秒
4. 相邻章节间隔至少 30 秒。如果同一时间段内有多个话题，合并为一个章节
5. **章节是从字幕中按时间段均匀选取的话题，不是把所有话题都堆在一起**

## JSON 大纲格式规则（必须严格遵守）

你的视频大纲 JSON 必须满足以下所有规则，否则解析会失败：

1. 必须用 ` ```json ` 和 ` ``` ` 代码块包裹整个 JSON
2. JSON 外层必须是 `{{"outline": [ ... ]}}`，不要漏掉任何括号
3. 每个章节对象必须恰好包含 3 个 key：`"title"`（字符串）、`"timestamp"`（整数）、`"part_outline"`（数组）
4. 每个要点对象必须恰好包含 2 个 key：`"timestamp"`（整数）、`"content"`（字符串）
5. `"timestamp"` 的值必须是整数（不加引号），且 `0 ≤ timestamp ≤ {duration}`
6. `"title"` 和 `"content"` 的值必须是字符串（加双引号）
7. 章节之间用逗号分隔，最后一个章节后面**不要**加逗号
8. 要点之间用逗号分隔，最后一个要点后面**不要**加逗号
9. **时间戳必须来自字幕中的 [MM:SS]**：章节按内容顺序递增，要点在其所属章节之后。绝对不要全部写 0

## 绝对禁止的错误

- ❌ `"chapters"` → 必须用 `"outline"`
- ❌ `"time"` → 必须用 `"timestamp"`
- ❌ 所有 timestamp 写 0 → 必须按视频内容分配真实时间
- ❌ 缺少 `{{` 或 `}}` → JSON 必须完整闭合
- ❌ 最后一个元素后加逗号 → 会产生无效 JSON
- ❌ 把 JSON 直接写在标题后面 → 必须用代码块包裹

---
视频字幕内容（每行格式为 [起始时间-结束时间] 该时段内的连续字幕文本）：
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


SUMMARY_PROMPT_CHAPTERS = """你是视频内容分析专家。请对以下视频章节生成标题和摘要要点，使用 {language} 输出。

视频时长：{duration} 秒。

## 你的任务

视频已经被自动切分为 {n_chapters} 个章节，每个章节都有**精确的时间戳**（来自字幕时间轴）。

你**不需要也不应该**输出时间戳。你只需要为每个章节生成：
1. **标题**（5-15 个字，概括该章节主题）
2. **摘要要点**（2-4 个要点，每个要点一句话，用数组列出）

## 输出格式

严格输出以下 JSON，用 ```json 代码块包裹：

```json
{{"chapters": [{{"title": "章节标题", "summary": ["要点一", "要点二", "要点三"]}}, {{"title": "章节标题", "summary": ["要点一", "要点二"]}}]}}
```

## 规则

1. **不要输出时间戳** — 时间戳已经由系统提供，你只输出标题和摘要要点
2. **不要遗漏章节** — 必须为所有 {n_chapters} 个章节都生成标题和摘要要点
3. **标题不要重复** — 每个章节的标题必须不同
4. **摘要要点必须是数组** — 每个章节的 summary 是字符串数组，不是单个字符串
5. **JSON 外层必须是 `{{"chapters": [ ... ]}}`**
6. **章节之间用逗号分隔，最后一个不要加逗号**

## 视频概述

在 JSON 之前，先用 2-3 句话概括视频主题和核心内容（不要加标题，直接写）。

---

以下是各章节的字幕内容：

{chapters_text}
"""


def _lang_hint(language: str) -> str:
    return "中文" if language.startswith("zh") else "与原文相同的语言"


# ---------------------------------------------------------------------------
# Executive Summary (Stage 2)
# ---------------------------------------------------------------------------

EXECUTIVE_SUMMARY_PROMPT = """基于以下视频章节信息，用{language}输出一个JSON对象，只输出JSON不要输出其他内容。

{chapters_text}

输出格式：
{{"core_topic":"视频核心主题(10-30字)","key_insights":["提炼的观点1(15-50字)","提炼的观点2","提炼的观点3"],"author_conclusion":"根据所有章节推导出的作者核心结论，必须是非空的完整句子(20-200字)","controversies":[]}}

要求：
- core_topic：概括视频最关键的主题，不要用"本视频介绍了"开头
- key_insights：3-5条，提炼观点而非复述章节标题
- author_conclusion：必须输出，即使视频没有明确结论也要推导出最合理的总结
- controversies：可为空数组
- 所有字段都必须输出，禁止省略，禁止输出空值"""


MINDMAP_PROMPT = """基于以下视频章节信息，用{language}输出一个层级化思维导图的 JSON 对象，只输出 JSON，不要输出任何其他内容。

{chapters_text}

输出格式（严格 JSON，禁止 Markdown / 代码块 / Mermaid）：
{{"root":"视频核心主题(10-30字)","children":[{{"title":"章节标题(5-15字)","timestamp":0,"children":[{{"title":"要点内容(5-40字)","timestamp":0,"children":[]}}]}}]}}

要求：
- root：概括视频最关键的主题
- children：必须恰好包含 {n_chapters} 个章节节点，与上面输入的章节一一对应（顺序也保持一致）
- 每个章节节点的 children：包含 2-4 个要点节点
- 每个要点节点的 children：必须是空数组 []
- timestamp 字段必须存在，可以填 0（系统会自动用真实时间戳覆盖）
- 字段名严格使用 root / children / title / timestamp，禁止使用其它字段名（例如 topic / nodes / time）
- 不要输出 Mermaid 语法
- 不要输出 markdown 或代码块包裹
- 不要输出 JSON 以外的解释文字
- 不要添加任何额外字段"""


def _format_ts(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _build_executive_summary_input(outline: list[dict]) -> str:
    """Convert outline to compressed text with timestamps for executive summary."""
    lines: list[str] = []
    for i, ch in enumerate(outline, 1):
        title = ch.get("title", f"章节 {i}")
        ts = _format_ts(ch.get("timestamp", 0))
        lines.append(f"[{ts}] {title}")
        for bullet in ch.get("summary", []):
            lines.append(f"• {bullet}")
        lines.append("")
    return "\n".join(lines)


def _exec_summary_fallback(outline: list[dict]) -> dict | None:
    """Return None when LLM2 fails — no fallback to chapter titles."""
    return None


def generate_executive_summary(outline: list[dict], language: str = "zh") -> dict | None:
    """Stage 2: Generate executive summary from structured outline.

    Returns a dict with {core_topic, key_insights, author_conclusion, controversies}.
    Returns None when LLM fails quality validation.
    """
    if not outline:
        return _exec_summary_fallback([])

    import time
    t0 = time.monotonic()

    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("[EXEC_SUMMARY] no OPENAI_API_KEY, using fallback")
            return _exec_summary_fallback(outline)

        base_url = os.getenv("SUMMARY_BASE_URL") or None
        model = os.getenv("EXECUTIVE_SUMMARY_MODEL") or os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
        timeout = int(os.getenv("EXECUTIVE_SUMMARY_TIMEOUT", "30"))

        client = OpenAI(api_key=api_key, base_url=base_url)
        chapters_text = _build_executive_summary_input(outline)
        prompt = EXECUTIVE_SUMMARY_PROMPT.format(
            language=_lang_hint(language),
            chapters_text=chapters_text,
        )

        logger.warning("[EXEC_SUMMARY] input_chapters=%d input_chars=%d model=%s",
                       len(outline), len(chapters_text), model)

        messages = [
            {"role": "system", "content": "你是一个专业的视频内容分析助手。"},
            {"role": "user", "content": prompt},
        ]

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=1024,
                timeout=timeout,
            )
            raw = response.choices[0].message.content or ""
            latency_ms = int((time.monotonic() - t0) * 1000)

            logger.warning("[EXEC_SUMMARY] attempt=%d/%d output_chars=%d latency_ms=%d raw=%s",
                           attempt, max_retries, len(raw), latency_ms, raw[:200])

            result = parse_executive_summary(raw)
            if result is not None:
                logger.warning("[EXEC_SUMMARY] attempt=%d parse SUCCESS", attempt)
                return result

            logger.warning("[EXEC_SUMMARY] attempt=%d parse FAILED, retrying...", attempt)

        logger.warning("[EXEC_SUMMARY] all %d attempts failed, using fallback", max_retries)
        return _exec_summary_fallback(outline)

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("[EXEC_SUMMARY] failed (%dms): %s, using fallback", latency_ms, e)
        return _exec_summary_fallback(outline)


# Template sentences that provide no real information
_EXEC_SUMMARY_BANNED_TOPIC_PATTERNS = [
    "本视频介绍", "本视频主要", "该视频介绍", "该视频主要",
    "这个视频介绍", "这个视频主要", "视频介绍了", "视频主要讲",
]
_EXEC_SUMMARY_BANNED_CONCLUSION_PATTERNS = [
    "视频围绕", "以上主题", "总结了以上", "介绍了以上",
    "讲述了以上", "围绕以上", "以上内容", "以上章节",
]


def parse_executive_summary(text: str) -> dict | None:
    """Parse executive summary JSON from LLM response with quality validation."""
    import json as _json

    raw = None

    logger.warning("[EXEC_SUMMARY] parse input len=%d first_50=%r", len(text), text[:50])

    # Strategy 1: code fence
    match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        raw = match.group(1).strip()
        logger.warning("[EXEC_SUMMARY] code fence matched, raw_len=%d", len(raw))

    # Strategy 2: find JSON object with "core_topic" key
    if raw is None:
        idx = text.find('"core_topic"')
        if idx == -1:
            idx = text.find("'core_topic'")
        if idx != -1:
            for j in range(idx - 1, -1, -1):
                if text[j] == '{':
                    candidate = _find_balanced_json(text, j)
                    if candidate:
                        raw = candidate
                        break
                    # Truncated JSON: try to repair
                    candidate = text[j:]
                    # Close any open strings and brackets
                    if candidate.count('"') % 2 != 0:
                        candidate += '"'
                    open_brackets = candidate.count('[') - candidate.count(']')
                    for _ in range(max(0, open_brackets)):
                        candidate += ']'
                    open_braces = candidate.count('{') - candidate.count('}')
                    for _ in range(max(0, open_braces)):
                        candidate += '}'
                    try:
                        _json.loads(candidate)
                        raw = candidate
                        logger.warning("[EXEC_SUMMARY] repaired truncated JSON")
                        break
                    except _json.JSONDecodeError:
                        pass
                if text[j] == '#' and j > 0:
                    break

    if raw is None:
        logger.warning("[EXEC_SUMMARY] no JSON found in response")
        return None

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as e:
        logger.warning("[EXEC_SUMMARY] JSON parse error: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    core_topic = str(data.get("core_topic", "")).strip()
    key_insights = data.get("key_insights") or data.get("key_takeaways") or []
    author_conclusion = str(data.get("author_conclusion", "")).strip()
    controversies = data.get("controversies", [])

    logger.warning("[EXEC_SUMMARY] parsed fields: topic_len=%d topic='%s' insights=%d conclusion_len=%d conclusion='%s' controversies=%d",
                   len(core_topic), core_topic[:50], len(key_insights) if isinstance(key_insights, list) else -1,
                   len(author_conclusion), author_conclusion[:50],
                   len(controversies) if isinstance(controversies, list) else -1)

    # Quality validation — strict thresholds
    if len(core_topic) < 20:
        logger.warning("[EXEC_SUMMARY] core_topic too short (%d chars): '%s'", len(core_topic), core_topic)
        return None

    # Ban template sentences
    if any(core_topic.startswith(p) for p in _EXEC_SUMMARY_BANNED_TOPIC_PATTERNS):
        logger.warning("[EXEC_SUMMARY] core_topic is template: '%s'", core_topic)
        return None

    if not author_conclusion:
        logger.warning("[EXEC_SUMMARY] author_conclusion is empty")
        return None

    if any(p in author_conclusion for p in _EXEC_SUMMARY_BANNED_CONCLUSION_PATTERNS):
        logger.warning("[EXEC_SUMMARY] author_conclusion is template: '%s'", author_conclusion)
        return None

    if not isinstance(key_insights, list) or len(key_insights) < 3:
        logger.warning("[EXEC_SUMMARY] key_insights too few: %s", key_insights)
        return None

    # Filter out too-short insights before validation
    key_insights = [str(s).strip() for s in key_insights if len(str(s).strip()) >= 10]
    if len(key_insights) < 3:
        logger.warning("[EXEC_SUMMARY] key_insights too few after filtering")
        return None

    # Clean up: dedup
    key_insights = list(dict.fromkeys(key_insights))  # dedup preserving order
    controversies = [str(s).strip() for s in controversies if str(s).strip()]

    # Length enforcement
    key_insights = [s[:50] for s in key_insights]
    author_conclusion = author_conclusion[:200]
    controversies = [s[:50] for s in controversies]

    return {
        "core_topic": core_topic,
        "key_insights": key_insights,
        "author_conclusion": author_conclusion,
        "controversies": controversies,
    }


# ---------------------------------------------------------------------------
# Mindmap (Stage 2 — runs in parallel with executive summary)
# ---------------------------------------------------------------------------

_MINDMAP_LEAF_MIN = 1
_MINDMAP_LEAF_MAX = 8


def generate_mindmap(outline: list[dict], language: str = "zh") -> dict | None:
    """Stage 2 sibling of generate_executive_summary: build a hierarchical
    mindmap from the structured outline.

    Returns ``{"root": str, "children": [{"title", "timestamp", "children": [...]}]}``
    or ``None`` on validation failure / API error / missing key. Callers
    (the SSE router) must skip the ``mindmap`` event when ``None`` so the
    outline + executive summary still ship.
    """
    if not outline:
        return None

    import time
    t0 = time.monotonic()

    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("[MINDMAP] no OPENAI_API_KEY, skipping mindmap")
            return None

        base_url = os.getenv("SUMMARY_BASE_URL") or None
        model = (
            os.getenv("MINDMAP_MODEL")
            or os.getenv("EXECUTIVE_SUMMARY_MODEL")
            or os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
        )
        timeout = int(os.getenv("MINDMAP_TIMEOUT", "30"))

        client = OpenAI(api_key=api_key, base_url=base_url)
        chapters_text = _build_executive_summary_input(outline)
        prompt = MINDMAP_PROMPT.format(
            language=_lang_hint(language),
            chapters_text=chapters_text,
            n_chapters=len(outline),
        )

        logger.warning(
            "[MINDMAP] input_chapters=%d input_chars=%d model=%s",
            len(outline), len(chapters_text), model,
        )

        messages = [
            {"role": "system", "content": "你是一个专业的视频内容分析助手，擅长把视频内容组织成层级化的知识结构图。"},
            {"role": "user", "content": prompt},
        ]

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
                timeout=timeout,
            )
            raw = response.choices[0].message.content or ""
            latency_ms = int((time.monotonic() - t0) * 1000)

            logger.warning(
                "[MINDMAP] attempt=%d/%d output_chars=%d latency_ms=%d raw=%s",
                attempt, max_retries, len(raw), latency_ms, raw[:200],
            )

            result = parse_mindmap(raw, outline)
            if result is not None:
                logger.warning("[MINDMAP] attempt=%d parse SUCCESS root=%r children=%d",
                               attempt, result["root"][:30], len(result["children"]))
                return result

            logger.warning("[MINDMAP] attempt=%d parse FAILED, retrying...", attempt)

        logger.warning("[MINDMAP] all %d attempts failed, skipping mindmap event", max_retries)
        return None

    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("[MINDMAP] failed (%dms): %s, skipping mindmap event", latency_ms, e)
        return None


def parse_mindmap(text: str, outline: list[dict]) -> dict | None:
    """Parse mindmap JSON from LLM output and ground its timestamps in *outline*.

    Two extraction strategies (same shape as ``parse_executive_summary``):
      1. ```` ```json ... ``` ```` code fence.
      2. Find a balanced JSON object that contains the ``"root"`` key.

    Validation:
      - ``root`` is a non-empty string (≥ 2 chars after strip).
      - ``children`` is a list whose length equals ``len(outline)``.
      - Each chapter node has a non-empty string ``title``.
      - Each chapter's ``children`` is a (possibly empty) list of leaf nodes
        with non-empty ``title``; non-conforming leaves are skipped. Each
        chapter must end up with ≥ 1 leaf or the whole parse fails (a
        "chapter with no bullets" mindmap node would render as a dead branch).

    Timestamp grafting (the LLM never owns timestamps):
      - chapter ``timestamp`` ← ``outline[i].timestamp``.
      - leaf ``timestamp`` ← parent chapter's timestamp (the outline
        ``summary`` is a ``string[]`` with no per-bullet times — see the
        plan's "Inherit chapter timestamp" decision).

    Returns the cleaned dict or ``None`` on any structural failure.
    """
    import json as _json
    raw: str | None = None

    if not isinstance(text, str) or not text.strip():
        return None

    # Strategy 1: ```json ... ``` code fence (tolerant of "```\n" without "json")
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    # Strategy 2: balanced JSON containing a "root" key
    if raw is None:
        idx = text.find('"root"')
        if idx == -1:
            idx = text.find("'root'")
        if idx != -1:
            for j in range(idx - 1, -1, -1):
                if text[j] == '{':
                    candidate = _find_balanced_json(text, j)
                    if candidate:
                        raw = candidate
                        break
                if text[j] == '#':
                    break

    # Strategy 3: the LLM may have emitted bare JSON (no fence, no prose).
    if raw is None:
        stripped = text.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            raw = stripped

    if raw is None:
        logger.warning("[MINDMAP] no JSON found in response")
        return None

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as e:
        logger.warning("[MINDMAP] JSON parse error: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    root = str(data.get("root", "")).strip()
    children = data.get("children")

    if len(root) < 2:
        logger.warning("[MINDMAP] root too short: %r", root)
        return None

    if not isinstance(children, list):
        logger.warning("[MINDMAP] children is not a list: %s", type(children).__name__)
        return None

    if len(children) != len(outline):
        logger.warning(
            "[MINDMAP] chapter count mismatch: got %d, expected %d",
            len(children), len(outline),
        )
        return None

    out_children: list[dict] = []
    for i, ch_node in enumerate(children):
        if not isinstance(ch_node, dict):
            logger.warning("[MINDMAP] chapter %d is not a dict", i)
            return None
        ch_title = str(ch_node.get("title", "")).strip()
        if not ch_title:
            logger.warning("[MINDMAP] chapter %d title is empty", i)
            return None

        ch_ts = int(outline[i].get("timestamp", 0))
        leaves_raw = ch_node.get("children", [])
        if not isinstance(leaves_raw, list):
            leaves_raw = []

        leaf_out: list[dict] = []
        for leaf in leaves_raw[:_MINDMAP_LEAF_MAX]:
            if not isinstance(leaf, dict):
                continue
            leaf_title = str(leaf.get("title", "")).strip()
            if not leaf_title:
                continue
            leaf_out.append({
                "title": leaf_title[:80],
                "timestamp": ch_ts,
                "children": [],
            })

        if len(leaf_out) < _MINDMAP_LEAF_MIN:
            logger.warning(
                "[MINDMAP] chapter %d has %d valid leaves (need ≥ %d)",
                i, len(leaf_out), _MINDMAP_LEAF_MIN,
            )
            return None

        out_children.append({
            "title": ch_title[:40],
            "timestamp": ch_ts,
            "children": leaf_out,
        })

    return {
        "root": root[:60],
        "children": out_children,
    }


# ---------------------------------------------------------------------------
# Chat with Video (BM25-style retrieval + LLM citation)
# ---------------------------------------------------------------------------

_STOP_WORDS_QA = frozenset(
    "的了是在我有和就不人都一个上也这到说要会着没看好自己"
    "让被把给从对与而已但而且么哪如请问告诉"
)

# Maximum tokens per chapter in the prompt (2 summary lines + 3 segments)
_CHAT_MAX_SUMMARY_PER_CH = 2
_CHAT_MAX_SEG_PER_CH = 3
# Hard cap on prompt body length (chars) — roughly 1500 tokens
_CHAT_PROMPT_MAX_CHARS = 3000


def _build_seg_to_chapter(outline: list[dict]) -> dict[int, int]:
    """Build a reverse index: segment_idx → chapter_idx. O(total_segments)."""
    idx: dict[int, int] = {}
    for i, ch in enumerate(outline):
        for s in ch.get("source_segments", []):
            idx[s] = i
    return idx


def _find_chapter(seg_idx: int, outline: list[dict], _cache: dict | None = None) -> int:
    """Return the chapter index that owns *seg_idx*, or -1.

    Uses a pre-built reverse index when *outline* is large (> 5 chapters)
    to avoid O(S*C*K) linear scan.
    """
    if len(outline) <= 5:
        # Small outline: linear scan is fine
        for i, ch in enumerate(outline):
            if seg_idx in ch.get("source_segments", []):
                return i
        return -1
    # Large outline: use pre-built reverse index
    if _cache is None or id(_cache.get("_outline")) != id(outline):
        _cache = {"_outline": outline, "_seg2ch": _build_seg_to_chapter(outline)}
    return _cache["_seg2ch"].get(seg_idx, -1)


def _retrieve_by_chapter(
    query: str,
    segments: list[dict],
    outline: list[dict],
    top_k_chapters: int = 3,
    max_seg_per_chapter: int = _CHAT_MAX_SEG_PER_CH,
    min_score: float = 0.01,
) -> dict[int, list[dict]]:
    """Character n-gram retrieval with per-chapter diversification.

    Returns ``{chapter_idx: [{"idx", "text", "start", "score"}, ...]}``
    ordered by descending chapter score.  Each chapter contains at most
    *max_seg_per_chapter* entries so a single dominant chapter cannot
    monopolise the results.

    Chapter score formula:
        max(seg_scores) + 0.1 × hit_count
    """
    query_clean = "".join(
        w for w in query if w not in _STOP_WORDS_QA and not w.isspace()
    )
    query_ngrams = set(_char_ngrams(query_clean))
    if not query_ngrams:
        return {}

    # 1. Pre-build reverse index for large outlines
    seg2ch_cache: dict | None = {} if len(outline) > 5 else None

    # 2. Score every segment
    by_chapter_raw: dict[int, list[dict]] = {}
    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        if not text:
            continue
        seg_ngrams = set(_char_ngrams(text))
        if not seg_ngrams:
            continue
        score = len(query_ngrams & seg_ngrams) / max(
            len(query_ngrams | seg_ngrams), 1
        )
        if score < min_score:
            continue
        ch_idx = _find_chapter(i, outline, seg2ch_cache)
        if ch_idx < 0:
            continue
        by_chapter_raw.setdefault(ch_idx, []).append({
            "idx": i,
            "text": text,
            "start": seg["start"],
            "score": score,
        })

    # 2. Per-chapter cap (keep highest-scoring segments)
    by_chapter: dict[int, list[dict]] = {}
    for ch, items in by_chapter_raw.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        by_chapter[ch] = items[:max_seg_per_chapter]

    # 3. Aggregate chapter scores and rank
    chapter_ranked: list[tuple[int, float, list[dict]]] = []
    for ch, items in by_chapter.items():
        max_score = max(it["score"] for it in items)
        chapter_score = max_score + 0.1 * len(items)
        chapter_ranked.append((ch, chapter_score, items))

    chapter_ranked.sort(key=lambda x: x[1], reverse=True)

    return {ch: items for ch, _, items in chapter_ranked[:top_k_chapters]}


CHAT_SYSTEM_PROMPT = """你是「视频问答助手」。根据下方提供的字幕片段回答用户问题。

## 核心规则

1. **只使用字幕信息**：回答中的每个事实必须来自下方「相关字幕片段」或「视频章节」的摘要，禁止使用你的自身知识
2. **引用标注**：回答中的每个事实标注 [[CH_N]]（N 是章节编号，从 0 开始），放在句子末尾
3. **概述类问题要回答**：如果用户问「这个视频讲什么」「主要内容是什么」等概述性问题，直接根据章节摘要和字幕片段概括回答
4. **细节缺失时如实说明**：如果用户问某个具体细节（如「怎么用」「为什么」「优缺点」），但字幕中没有相关信息，回答「视频中没有说明 XXX 的具体细节。」并补充字幕中已有的相关信息
5. **完全无关时拒绝**：字幕中完全没有相关内容时，回答「视频中没有提到这个问题。」
6. **禁止引用未提供的章节**
7. **回答控制在 200 字以内**
8. **不要输出 JSON**

## 示例

用户：这个视频主要讲什么？
回答：这个视频介绍了一个开源文档翻译平台的开发过程。作者使用 Cursor 等 AI 编程工具 [[CH_1]]，通过 Next.js 全栈技术 [[CH_1]] 实现了 GitHub 文档的自动多语言翻译 [[CH_0]]，并部署在 Vercel 上 [[CH_2]]。

用户：项目怎么部署的？
回答：项目通过 Vercel 一键部署上线 [[CH_2]]，免费额度足够个人项目。

用户：Cursor 怎么用的？
回答：视频中没有说明 Cursor 的具体使用方法。视频仅提到作者使用了 Cursor 这款 AI 编程工具 [[CH_1]]，99% 的代码由 AI 生成。

用户：MCP 是什么？
回答：视频中没有说明 MCP 的具体含义。视频仅提到使用了 MCP 扩展 [[CH_1]] 来辅助开发。

用户：量子纠缠怎么实现？
回答：视频中没有提到这个问题。"""


def _build_chat_prompt(
    question: str,
    outline: list[dict],
    chapter_hits: dict[int, list[dict]],
    segments: list[dict],
    exec_summary: dict | None,
) -> str:
    """Assemble the user-facing LLM prompt for chat.

    Token budget: ≤ _CHAT_PROMPT_MAX_CHARS (~1500 tokens).
    Outline: at most _CHAT_MAX_SUMMARY_PER_CH summary lines per chapter.
    Segments: at most _CHAT_MAX_SEG_PER_CH segments per chapter.
    """
    parts: list[str] = []

    # Video topic
    topic = (exec_summary or {}).get("core_topic", "未知主题")
    parts.append(f"## 视频主题\n{topic}\n")

    # Outline (compact)
    parts.append(f"## 视频章节（共 {len(outline)} 章）\n")
    for i, ch in enumerate(outline):
        title = ch.get("title", f"第 {i} 章")
        summary = ch.get("summary", [])[:_CHAT_MAX_SUMMARY_PER_CH]
        lines = "\n".join(f"- {s}" for s in summary)
        parts.append(f"### 第 {i} 章: {title}\n{lines}\n")

    # Retrieved segments
    if chapter_hits:
        parts.append("## 相关字幕片段\n")
        for ch_idx in sorted(chapter_hits.keys()):
            if ch_idx >= len(outline):
                continue
            ch_title = outline[ch_idx]["title"]
            parts.append(f"### 来自「{ch_title}」:")
            for hit in chapter_hits[ch_idx][:_CHAT_MAX_SEG_PER_CH]:
                ts = _format_ts(hit["start"])
                parts.append(f"SEG_{hit['idx']} [{ts}] {hit['text']}")
            parts.append("")

    # Question
    parts.append(f"## 用户问题\n{question}")

    prompt = "\n".join(parts)

    # Smart truncation: if over limit, trim segments section first
    # (most expendable), then outline, never truncate the question.
    if len(prompt) > _CHAT_PROMPT_MAX_CHARS:
        topic_marker = "## 视频主题\n"
        outline_marker = "## 视频章节"
        seg_marker = "## 相关字幕片段\n"
        q_marker = "## 用户问题\n"
        t_idx = prompt.find(topic_marker)
        o_idx = prompt.find(outline_marker)
        s_idx = prompt.find(seg_marker)
        q_idx = prompt.find(q_marker)

        if t_idx >= 0 and q_idx >= 0:
            topic_part = prompt[t_idx:(o_idx if o_idx >= 0 else s_idx if s_idx >= 0 else q_idx)]
            question_part = prompt[q_idx:]
            remaining_budget = _CHAT_PROMPT_MAX_CHARS - len(topic_part) - len(question_part) - 20

            # Allocate budget: 40% outline, 60% segments
            outline_budget = int(remaining_budget * 0.4)
            seg_budget = remaining_budget - outline_budget

            outline_section = prompt[o_idx:s_idx] if o_idx >= 0 and s_idx >= 0 else ""
            seg_section = prompt[s_idx:q_idx] if s_idx >= 0 and q_idx >= 0 else ""

            if len(outline_section) > outline_budget and outline_budget > 100:
                outline_section = outline_section[:outline_budget] + "\n..."
            if len(seg_section) > seg_budget and seg_budget > 100:
                seg_section = seg_section[:seg_budget] + "\n..."

            parts_out = [topic_part.rstrip()]
            if outline_section:
                parts_out.append(outline_section.rstrip())
            if seg_section:
                parts_out.append(seg_section.rstrip())
            parts_out.append(question_part.rstrip())
            prompt = "\n\n".join(parts_out)
        else:
            # Fallback: hard truncate
            prompt = prompt[:_CHAT_PROMPT_MAX_CHARS]

    return prompt


def _parse_chat_citations(
    answer_text: str,
    outline: list[dict],
    valid_chapters: set[int],
) -> tuple[str, list[dict]]:
    """Extract [[CH_N]] references from the LLM answer.

    Only references whose N is in *valid_chapters* are kept.  All
    ``[[CH_N]]`` markers are stripped from the returned clean text.

    Returns ``(clean_answer, citations)`` where each citation is
    ``{"chapter_title": str, "timestamp": int}``.
    """
    refs = re.findall(r"\[\[CH_(\d+)\]\]", answer_text)

    seen: set[int] = set()
    citations: list[dict] = []
    for r in refs:
        idx = int(r)
        if (
            idx in valid_chapters
            and idx not in seen
            and 0 <= idx < len(outline)
        ):
            seen.add(idx)
            ch = outline[idx]
            citations.append({
                "chapter_title": ch.get("title", ""),
                "timestamp": int(ch.get("timestamp", 0)),
            })

    # Strip all [[CH_N]] markers (including invalid ones) from the text
    # Replace with a single space to avoid missing word boundaries
    clean = re.sub(r"\s*\[\[CH_\d+\]\]\s*", " ", answer_text)
    clean = re.sub(r"\s{2,}", " ", clean).strip()

    return clean, citations


def generate_chat_answer(
    question: str,
    outline: list[dict],
    segments: list[dict],
    exec_summary: dict | None,
    language: str = "zh",
) -> Generator[tuple[str, list[dict] | None], None, None]:
    """Main chat entry point.  Yields SSE-style tuples:

    ``("token", str)``        — streaming token from the LLM.
    ``("done", citations)``   — final citations list (or empty list).
    ``("error", str)``        — error message (terminal).

    The caller (SSE router) is responsible for framing these into
    ``chat_token`` / ``chat_done`` / ``chat_error`` events.
    """
    # 1. Retrieve
    chapter_hits = _retrieve_by_chapter(question, segments, outline)
    logger.warning("[CHAT] query=%r retrieved_chapters=%d total_hits=%d",
                   question[:40], len(chapter_hits),
                   sum(len(v) for v in chapter_hits.values()))
    for ch_idx, hits in chapter_hits.items():
        logger.warning("[CHAT]   ch[%d] hits=%d top_score=%.3f",
                       ch_idx, len(hits), hits[0]["score"] if hits else 0)

    # When retrieval finds nothing (e.g. meta-questions like "这个视频讲什么"
    # where keywords like "视频" don't appear in subtitle text), fall back
    # to using ALL chapters so the LLM can answer from outline summaries.
    if not chapter_hits:
        logger.warning("[CHAT] no retrieval hits, falling back to outline-only context")
        chapter_hits = {i: [] for i in range(len(outline))}

    valid_chapters = set(chapter_hits.keys())

    # 2. Build prompt
    prompt = _build_chat_prompt(question, outline, chapter_hits, segments, exec_summary)

    # 3. Call LLM
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            yield ("error", "OPENAI_API_KEY 未配置")
            return

        base_url = os.getenv("SUMMARY_BASE_URL") or None
        model = (
            os.getenv("CHAT_MODEL")
            or os.getenv("EXECUTIVE_SUMMARY_MODEL")
            or os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
        )
        timeout = int(os.getenv("CHAT_TIMEOUT", "30"))

        client = OpenAI(api_key=api_key, base_url=base_url)
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            temperature=0.3,
            max_tokens=1024,
            timeout=timeout,
        )

        accumulated: list[str] = []
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                accumulated.append(delta.content)
                yield ("token", delta.content)

        # 4. Parse citations from the full accumulated text
        full_text = "".join(accumulated)
        _, citations = _parse_chat_citations(full_text, outline, valid_chapters)
        logger.warning("[CHAT] answer_len=%d citations=%d valid_chapters=%s",
                       len(full_text), len(citations), valid_chapters)
        yield ("done", citations)

    except Exception as e:
        logger.warning("[CHAT] failed: %s", e)
        yield ("error", f"AI 服务暂时不可用：{e}")


def _format_segments_with_timestamps(
    segments: list[dict],
    max_chars: int = 25000,
    window_secs: float = 60.0,
) -> str:
    """Format subtitle segments as topic windows for the LLM.

    Instead of one line per subtitle (too fine-grained — the LLM
    anchors to the first mention instead of the main discussion),
    we merge consecutive segments into windows of roughly
    *window_secs* seconds.  Each window shows its time range and
    the concatenated text, giving the LLM a topic-level view of
    the video.

    A 60-second window produces ~12 windows for a 12-minute video,
    which matches chapter granularity and gives the LLM fewer (but
    more meaningful) timestamp choices — reducing the chance of
    picking a first-mention instead of the main discussion point.
    """
    if not segments:
        return ""

    windows: list[str] = []
    buf_texts: list[str] = []
    buf_start = float(segments[0].get("start", 0))
    buf_end = buf_start
    total = 0

    for seg in segments:
        ts = float(seg.get("start", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue
        # Flush buffer when the window exceeds window_secs
        if buf_texts and ts - buf_start >= window_secs:
            sm, ss = divmod(int(buf_start), 60)
            em, es = divmod(int(buf_end), 60)
            merged = "".join(buf_texts)
            line = f"[{sm:02d}:{ss:02d}-{em:02d}:{es:02d}] {merged}"
            if total + len(line) + 1 > max_chars:
                break
            windows.append(line)
            total += len(line) + 1
            buf_texts = []
            buf_start = ts
        buf_texts.append(text)
        buf_end = float(seg.get("end", ts))

    # Flush remaining
    if buf_texts:
        sm, ss = divmod(int(buf_start), 60)
        em, es = divmod(int(buf_end), 60)
        merged = "".join(buf_texts)
        line = f"[{sm:02d}:{ss:02d}-{em:02d}:{es:02d}] {merged}"
        if total + len(line) + 1 <= max_chars:
            windows.append(line)

    return "\n".join(windows)


def _build_standard_prompt(
    subtitle_text: str,
    language: str,
    duration: int,
    segments: list[dict] | None = None,
) -> str:
    if segments:
        subtitle = _format_segments_with_timestamps(segments)
    else:
        subtitle = subtitle_text[:15000]
    return SUMMARY_PROMPT_STANDARD.format(
        language=_lang_hint(language),
        duration=duration or 0,
        subtitle=subtitle,
    )


def _build_fallback_prompt(title: str, platform: str, duration: int, language: str) -> str:
    return SUMMARY_PROMPT_FALLBACK.format(
        language=_lang_hint(language),
        title=title or "（未知）",
        platform=platform or "（未知）",
        duration=duration or 0,
        duration_min=(duration or 0) // 60,
    )


def _build_chapters_prompt(chapters: list[dict], language: str) -> str:
    """Build prompt for the new architecture: LLM only generates titles + summaries.

    Each chapter dict has {start, end, text} from the semantic segmentation
    engine.  Timestamps are NOT included in the prompt — the LLM should
    never generate or see timestamps.
    """
    lines: list[str] = []
    for i, ch in enumerate(chapters, 1):
        text = ch.get("text", "")
        if len(text) > 2000:
            text = text[:2000] + "..."
        lines.append(f"### 章节 {i}\n{text}")
    chapters_text = "\n\n".join(lines)
    return SUMMARY_PROMPT_CHAPTERS.format(
        language=_lang_hint(language),
        duration=int(chapters[-1].get("end", 0)) if chapters else 0,
        n_chapters=len(chapters),
        chapters_text=chapters_text,
    )


# ---------------------------------------------------------------------------
# Semantic Segmentation Engine
# ---------------------------------------------------------------------------
# Core principle: timestamps ALWAYS come from subtitle segments, NEVER from
# the LLM.  The LLM only generates titles and summaries for pre-segmented
# chapters.
# ---------------------------------------------------------------------------

def _chunk_segments(
    segments: list[dict], target_secs: float = 15.0,
) -> list[dict]:
    """Merge VTT segments into ~target_secs-second chunks.

    Each chunk: {start, end, text, segment_indices}.
    Preserves the original segment boundaries (no interpolation).
    """
    if not segments:
        return []
    chunks: list[dict] = []
    buf_texts: list[str] = []
    buf_indices: list[int] = []
    buf_start = float(segments[0].get("start", 0))
    buf_end = buf_start

    for seg_idx, seg in enumerate(segments):
        ts = float(seg.get("start", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue
        if buf_texts and ts - buf_start >= target_secs:
            chunks.append({
                "start": buf_start,
                "end": buf_end,
                "text": "".join(buf_texts),
                "segment_indices": list(buf_indices),
            })
            buf_texts = []
            buf_indices = []
            buf_start = ts
        buf_texts.append(text)
        buf_indices.append(seg_idx)
        buf_end = float(seg.get("end", ts))

    if buf_texts:
        chunks.append({
            "start": buf_start,
            "end": buf_end,
            "text": "".join(buf_texts),
            "segment_indices": list(buf_indices),
        })
    return chunks


def _char_ngrams(text: str, ns: tuple[int, ...] = (2, 3)) -> list[str]:
    """Extract character n-grams from text (for Chinese/CJK, no word segmentation needed)."""
    grams: list[str] = []
    for n in ns:
        for i in range(len(text) - n + 1):
            grams.append(text[i:i + n])
    return grams


def _tfidf_vectors(texts: list[str]) -> list[dict[str, float]]:
    """Build TF-IDF vectors from character n-grams (pure Python, no deps)."""
    from math import log
    # Document frequency
    df: dict[str, int] = {}
    doc_tfs: list[dict[str, int]] = []
    for text in texts:
        grams = _char_ngrams(text)
        tf: dict[str, int] = {}
        for g in grams:
            tf[g] = tf.get(g, 0) + 1
        doc_tfs.append(tf)
        for g in set(grams):
            df[g] = df.get(g, 0) + 1

    n_docs = len(texts)
    vectors: list[dict[str, float]] = []
    for tf in doc_tfs:
        vec: dict[str, float] = {}
        for g, count in tf.items():
            idf = log(n_docs / (1 + df.get(g, 0))) + 1
            vec[g] = count * idf
        vectors.append(vec)
    return vectors


def _cosine_sim_dict(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between sparse vectors (dicts)."""
    dot = sum(a[k] * b[k] for k in a if k in b)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_segment(
    segments: list[dict],
    min_chapters: int = 3,
    max_chapters: int = 8,
    chunk_secs: float = 30.0,
    min_duration: float = 45.0,
    max_duration: float = 120.0,
) -> list[dict]:
    """Find topic boundaries via Embedding cosine similarity + time span constraints.

    Pipeline:
    1. Chunk VTT segments into ~chunk_secs-second windows
    2. Get embeddings for each chunk via OpenAI Embedding API
    3. Compute cosine similarity between adjacent chunks
    4. Find boundaries where similarity drops below dynamic threshold (mean - 0.8*std)
    5. Force-split chapters > max_duration, merge chapters < min_duration

    Returns a list of chapter dicts: {start, end, text}.
    Falls back to uniform distribution if segmentation fails.
    """
    duration = float(segments[-1].get("end", 0)) if segments else 0.0
    chunks = _chunk_segments(segments, target_secs=chunk_secs)

    print(f"[SEG] video_duration={duration:.1f}s segments={len(segments)} chunk_secs={chunk_secs} chunks={len(chunks)}")

    if len(chunks) < 2:
        result = _fallback_chapters(segments, duration, min_chapters)
        print(f"[SEG] <2 chunks → fallback {len(result)} uniform chapters")
        return result

    # Compute TF-IDF vectors for all chunks (local, no API needed)
    try:
        texts = [c["text"] for c in chunks]
        vectors = _tfidf_vectors(texts)
        print(f"[SEG] TF-IDF computed: {len(vectors)} vectors")
    except Exception as e:
        print(f"[SEG] TF-IDF failed: {e}, falling back to uniform")
        return _fallback_chapters(segments, duration, min_chapters)

    # Cosine similarity between adjacent chunks
    sims = [_cosine_sim_dict(vectors[i], vectors[i+1])
            for i in range(len(vectors) - 1)]

    # Dynamic threshold: mean - 0.8 * stddev
    mean_sim = sum(sims) / len(sims)
    var = sum((s - mean_sim)**2 for s in sims) / len(sims)
    std_sim = var ** 0.5
    threshold = mean_sim - 0.8 * std_sim

    print(f"[SEG] sims={[round(s, 3) for s in sims]}")
    print(f"[SEG] mean={mean_sim:.3f} std={std_sim:.3f} threshold={threshold:.3f}")

    # Find boundary indices
    boundaries = [0]
    for i, sim in enumerate(sims):
        if sim < threshold:
            boundaries.append(i + 1)

    print(f"[SEG] boundaries={len(boundaries)} at_chunks={boundaries}")

    # Build raw chapters from boundaries
    raw: list[dict] = []
    for idx, b in enumerate(boundaries):
        end_bound = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(chunks)
        ch_start = chunks[b]["start"]
        ch_end = chunks[end_bound - 1]["end"]
        text = "".join(c["text"] for c in chunks[b:end_bound])
        seg_indices: list[int] = []
        for c in chunks[b:end_bound]:
            seg_indices.extend(c.get("segment_indices", []))
        raw.append({"start": ch_start, "end": ch_end, "text": text, "segment_indices": seg_indices})

    print(f"[SEG] raw_chapters={len(raw)}")
    for i, ch in enumerate(raw):
        print(f"  [{i}] {ch['start']:.1f}-{ch['end']:.1f} ({ch['end']-ch['start']:.1f}s)")

    # --- Time span enforcement ---

    # Pass 1: Force-split chapters > max_duration
    force_split_count = 0
    for _ in range(10):
        split_done = False
        new_raw: list[dict] = []
        for ch in raw:
            ch_dur = ch["end"] - ch["start"]
            if ch_dur > max_duration:
                ch_chunks = [c for c in chunks if c["start"] >= ch["start"] and c["end"] <= ch["end"]]
                if len(ch_chunks) >= 2:
                    # Use TF-IDF to find best split point within this chapter
                    ch_texts = [c["text"] for c in ch_chunks]
                    try:
                        ch_vecs = _tfidf_vectors(ch_texts)
                        ch_sims = [_cosine_sim_dict(ch_vecs[j], ch_vecs[j+1]) for j in range(len(ch_vecs)-1)]
                        best_split = ch_sims.index(min(ch_sims)) + 1
                    except Exception:
                        best_split = len(ch_chunks) // 2
                    split_ts = ch_chunks[best_split]["start"]
                    left_text = "".join(c["text"] for c in ch_chunks[:best_split])
                    right_text = "".join(c["text"] for c in ch_chunks[best_split:])
                    left_indices = [i for c in ch_chunks[:best_split] for i in c.get("segment_indices", [])]
                    right_indices = [i for c in ch_chunks[best_split:] for i in c.get("segment_indices", [])]
                    new_raw.append({"start": ch["start"], "end": split_ts, "text": left_text, "segment_indices": left_indices})
                    new_raw.append({"start": split_ts, "end": ch["end"], "text": right_text, "segment_indices": right_indices})
                    force_split_count += 1
                    split_done = True
                else:
                    mid = ch["start"] + ch_dur / 2
                    left_t, right_t = [], []
                    left_idx, right_idx = [], []
                    existing_indices = ch.get("segment_indices", [])
                    for si in existing_indices:
                        seg = segments[si]
                        s = float(seg.get("start", 0))
                        t = seg.get("text", "").strip()
                        if t and ch["start"] <= s < mid:
                            left_t.append(t)
                            left_idx.append(si)
                        elif t and mid <= s <= ch["end"]:
                            right_t.append(t)
                            right_idx.append(si)
                    new_raw.append({"start": ch["start"], "end": mid, "text": "".join(left_t), "segment_indices": left_idx})
                    new_raw.append({"start": mid, "end": ch["end"], "text": "".join(right_t), "segment_indices": right_idx})
                    force_split_count += 1
                    split_done = True
            else:
                new_raw.append(ch)
        raw = new_raw
        if not split_done:
            break

    # Pass 2: Merge chapters < min_duration
    for _ in range(10):
        merge_done = False
        new_raw: list[dict] = []
        for i, ch in enumerate(raw):
            ch_dur = ch["end"] - ch["start"]
            if ch_dur < min_duration and len(raw) > 1:
                gap_next = (raw[i + 1]["start"] - ch["end"]) if i + 1 < len(raw) else float("inf")
                gap_prev = (ch["start"] - raw[i - 1]["end"]) if i > 0 and new_raw else float("inf")
                if new_raw and gap_prev <= gap_next:
                    new_raw[-1]["end"] = ch["end"]
                    new_raw[-1]["text"] += ch["text"]
                    new_raw[-1]["segment_indices"] = new_raw[-1].get("segment_indices", []) + ch.get("segment_indices", [])
                    merge_done = True
                elif i + 1 < len(raw):
                    raw[i + 1] = {
                        "start": ch["start"],
                        "end": raw[i + 1]["end"],
                        "text": ch["text"] + raw[i + 1]["text"],
                        "segment_indices": ch.get("segment_indices", []) + raw[i + 1].get("segment_indices", []),
                    }
                    merge_done = True
                    continue
                else:
                    new_raw.append(ch)
            else:
                new_raw.append(ch)
        raw = new_raw
        if not merge_done:
            break

    # Pass 3: If still too many, merge smallest-gap pairs
    while len(raw) > max_chapters and len(raw) > 1:
        min_gap = float("inf")
        min_idx = 0
        for i in range(len(raw) - 1):
            gap = raw[i + 1]["start"] - raw[i]["end"]
            if gap < min_gap:
                min_gap = gap
                min_idx = i
        raw[min_idx]["end"] = raw[min_idx + 1]["end"]
        raw[min_idx]["text"] += raw[min_idx + 1]["text"]
        raw[min_idx]["segment_indices"] = raw[min_idx].get("segment_indices", []) + raw[min_idx + 1].get("segment_indices", [])
        raw.pop(min_idx + 1)

    print(f"[SEG] final={len(raw)} chapters")
    for i, ch in enumerate(raw):
        indices = ch.get("segment_indices", [])
        first_seg = indices[0] if indices else -1
        last_seg = indices[-1] if indices else -1
        print(f"  [{i}] {ch['start']:.1f}-{ch['end']:.1f} ({ch['end']-ch['start']:.1f}s) segments={first_seg}-{last_seg} count={len(indices)}")
    print(f"[SEG] summary: semantic_chapters={len(boundaries)} force_splits={force_split_count} final_chapters={len(raw)}")

    return raw


def _fallback_chapters(
    segments: list[dict], duration: float, n: int = 5,
) -> list[dict]:
    """Uniform time distribution — guaranteed to cover the full video."""
    if duration <= 0 or n <= 0:
        return []
    step = duration / n
    chapters: list[dict] = []
    for i in range(n):
        ch_start = i * step
        ch_end = (i + 1) * step if i < n - 1 else duration
        text_parts = []
        seg_indices = []
        for seg_idx, seg in enumerate(segments):
            s = float(seg.get("start", 0))
            e = float(seg.get("end", 0))
            t = seg.get("text", "").strip()
            if t and s >= ch_start and s < ch_end:
                text_parts.append(t)
                seg_indices.append(seg_idx)
        chapters.append({
            "start": ch_start,
            "end": ch_end,
            "text": "".join(text_parts),
            "segment_indices": seg_indices,
        })
    return chapters


def _get_min_chapters(duration: int) -> int:
    """Dynamic minimum chapter count based on video duration."""
    if duration < 300:
        return 3
    elif duration < 900:
        return 5
    elif duration < 1800:
        return 8
    elif duration < 3600:
        return 12
    return 15


def _validate_outline(
    chapters: list[dict],
    duration: float,
) -> list[dict]:
    """Validate and auto-fix chapter coverage.

    Checks:
    1. Coverage: last chapter must be >= 90% of video duration
    2. Gap detection: if gap > 30% of duration between adjacent chapters,
       insert a filler chapter
    3. Deduplicate titles
    4. Minimum chapter count (dynamic based on duration)
    """
    if not chapters:
        return chapters

    min_ch = _get_min_chapters(int(duration))

    # 1. Coverage check: last chapter must reach >= 90% of video
    if chapters and duration > 0:
        last_end = max(ch.get("end", 0) for ch in chapters)
        if last_end < duration * 0.9:
            # Add a filler chapter for the uncovered tail
            gap_start = last_end
            chapters.append({
                "start": gap_start,
                "end": duration,
                "title": "总结与收尾",
                "summary": "",
            })

    # 2. Gap detection: insert filler for gaps > 30% of duration
    gap_threshold = duration * 0.3
    i = 0
    while i < len(chapters) - 1:
        gap = chapters[i + 1].get("start", 0) - chapters[i].get("end", 0)
        if gap > gap_threshold:
            mid = (chapters[i].get("end", 0) + chapters[i + 1].get("start", 0)) / 2
            chapters.insert(i + 1, {
                "start": chapters[i].get("end", mid),
                "end": chapters[i + 1].get("start", mid),
                "title": "内容过渡",
                "summary": "",
            })
        i += 1

    # 3. Deduplicate titles
    seen_titles: dict[str, int] = {}
    for ch in chapters:
        title = ch.get("title", "")
        if title in seen_titles:
            seen_titles[title] += 1
            ch["title"] = f"{title}（{seen_titles[title]}）"
        else:
            seen_titles[title] = 1

    # 4. Minimum chapter count — if still too few, log a warning
    # (don't fabricate chapters; the segmentation should have handled this)
    if len(chapters) < min_ch:
        logger.warning(
            "validate_outline: only %d chapters for %ds video (want >= %d)",
            len(chapters), int(duration), min_ch,
        )

    return chapters


# --- Stop-words for keyword extraction (single chars too common in Chinese) ---
_STOP_WORDS = frozenset(
    "的了是在我有和就不人都一个上也这到说要会着没看好自己"
    "让被把给从对与而已但而且 yet so if or and the a an"
)


def _extract_keywords(text: str, max_kw: int = 8) -> list[str]:
    """Extract topic keywords from *text* used to ground outline timestamps.

    Returns a mix of short (2-char) and long (3-4 char) keywords.
    Short keywords give broad recall (``集群`` matches anywhere the topic
    is mentioned); longer keywords add precision when available.
    """
    cleaned = "".join(c for c in text if c.isalnum() or c in "一-鿿")
    seen: set[str] = set()
    kw: list[str] = []
    for length in (2, 3, 4):  # shorter first for higher hit rate
        for i in range(len(cleaned) - length + 1):
            sub = cleaned[i : i + length]
            if sub in _STOP_WORDS or sub.isdigit() or sub in seen:
                continue
            seen.add(sub)
            kw.append(sub)
            if len(kw) >= max_kw:
                return kw
    return kw


def fix_outline_timestamps(
    outline: list[dict],
    segments: list[dict],
    duration: int,
) -> list[dict]:
    """Ground outline timestamps in the actual subtitle timeline.

    Light LLMs (mimo-v2-flash) routinely produce plausible-looking but
    inaccurate timestamps — even-spaced guesses that don't correspond to
    where the topic is actually discussed. A previous version of this
    function skipped the fix when the LLM gave any non-zero timestamp,
    which let those guesses ship to the user. We now always ground:

    Strategy (in order, per chapter / part):
    1. Keyword search — find the first subtitle segment whose text
       contains any keyword extracted from the title / content. The
       segment's ``start`` time is the most accurate answer because it
       comes from the actual video timeline.
    2. LLM fallback — if no keyword hit, use the LLM's timestamp if it
       is within [0, duration). The LLM's guess is at least a reasonable
       starting point, and sometimes it is right.
    3. Even distribution — remaining zeros are spread evenly so the
       outline is monotonically increasing and stays in bounds.
    """
    if not outline:
        return outline

    total = duration or (int(segments[-1]["end"]) if segments else 600)

    def _find_segment(keywords: list[str], start: float = 0, end: float | None = None) -> float:
        """Return start-time of first segment matching any keyword, or -1."""
        for seg in segments:
            seg_start = float(seg.get("start", 0))
            if seg_start < start:
                continue
            if end is not None and seg_start > end:
                break
            text = seg.get("text", "")
            for kw in keywords:
                if kw in text:
                    return seg_start
        return -1

    def _safe_llm_ts(llm_ts: int, lo: float, hi: float) -> int | None:
        """Return llm_ts if it falls within [lo, hi), else None. Catches
        negative, beyond-duration, and inverted-bound LLM guesses."""
        try:
            t = int(llm_ts)
        except (TypeError, ValueError):
            return None
        if t < lo or t >= hi:
            return None
        return t

    # --- Fix chapter timestamps ---
    # Search forward: each chapter starts searching from after the previous
    # chapter's timestamp, so common keywords like "项目" don't pin every
    # chapter to the same early segment.
    MIN_CHAPTER_GAP = 15.0  # seconds — chapters tighter than this get redistributed
    chapter_times: list[float] = []
    grounded: list[bool] = []  # True if keyword search found a match
    prev_end = 0.0
    for sec in outline:
        kw = _extract_keywords(sec.get("title", ""))
        ts = _find_segment(kw, start=prev_end)
        if ts >= 0:
            chapter_times.append(ts)
            grounded.append(True)
        else:
            # No keyword match — trust the LLM only if its guess is in range
            llm_ts = _safe_llm_ts(sec.get("timestamp", 0), prev_end, total)
            ts = float(llm_ts) if llm_ts is not None else 0.0
            chapter_times.append(ts)
            grounded.append(False)
        prev_end = chapter_times[-1] + 1  # next chapter must be after this one

    # Evenly distribute chapters that got ts=0
    n_chapters = len(outline)
    zero_indices = [i for i, t in enumerate(chapter_times) if t == 0]
    if zero_indices and n_chapters > 0:
        step = total / n_chapters
        for idx, zidx in enumerate(zero_indices):
            chapter_times[zidx] = step * idx

    # Clamp into [0, total-1] then ensure strictly increasing order
    for i in range(n_chapters):
        chapter_times[i] = max(0.0, min(chapter_times[i], total - 1))
        if i > 0 and chapter_times[i] <= chapter_times[i - 1]:
            chapter_times[i] = chapter_times[i - 1] + 1

    # Fix tightly-packed chapters: any chain of chapters within 15 seconds
    # of each other gets redistributed with enforced minimum spacing.
    # This handles both 2-item overlaps and 3+ item clusters in one pass.
    _MIN_CH_SPACING = 15.0
    for _pass in range(3):  # multi-pass: redistribution can create new overlaps
        changed = False
        i = 1
        while i < n_chapters:
            if chapter_times[i] - chapter_times[i - 1] >= _MIN_CH_SPACING:
                i += 1
                continue
            # Find the extent of this overlap chain
            chain_start = i - 1
            while chain_start > 0 and chapter_times[chain_start] - chapter_times[chain_start - 1] < _MIN_CH_SPACING:
                chain_start -= 1
            chain_end = i
            while chain_end + 1 < n_chapters and chapter_times[chain_end + 1] - chapter_times[chain_end] < _MIN_CH_SPACING:
                chain_end += 1
            # Redistribute [chain_start..chain_end] in local range
            local_lo = chapter_times[chain_start - 1] if chain_start > 0 else 0.0
            local_hi = chapter_times[chain_end + 1] if chain_end + 1 < n_chapters else float(total)
            n = chain_end - chain_start + 1
            span = local_hi - local_lo
            for idx in range(n):
                chapter_times[chain_start + idx] = local_lo + span * (idx + 1) / (n + 1)
            changed = True
            i = chain_end + 1
        if not changed:
            break

    # Global spacing enforcement: if a gap between adjacent chapters is
    # more than 2× the expected average spacing, the dense chapters after
    # that gap are bunched together.  Redistribute them evenly across the
    # available space.  This catches cases like 5 chapters all landing in
    # the last 15 seconds of a 12-minute video.
    if n_chapters >= 2:
        expected = total / n_chapters
        i = 1
        while i < n_chapters:
            if chapter_times[i] - chapter_times[i - 1] <= 2 * expected:
                i += 1
                continue
            # Chapter i is too far from i-1 → chapters i..end are bunched
            chain_start = i
            chain_end = n_chapters - 1
            lo = chapter_times[chain_start - 1]
            hi = float(total)
            n = chain_end - chain_start + 1
            span = hi - lo
            for idx in range(n):
                chapter_times[chain_start + idx] = lo + span * (idx + 1) / (n + 1)
            break

    # Tail check: if the last chapter is significantly before the video
    # end (more than 2× expected spacing), the LLM clustered all chapters
    # in the first portion.  Redistribute ALL chapters evenly across the
    # full video duration.
    if n_chapters >= 2:
        expected = total / n_chapters
        if total - chapter_times[-1] > 2 * expected:
            step = total / (n_chapters + 1)
            for idx in range(n_chapters):
                chapter_times[idx] = step * (idx + 1)

    # Dedup + sort: ensure chapter timestamps are unique and strictly
    # increasing.  After redistribution, two chapters can land on the
    # same second; sort them and bump duplicates by +1s.
    paired = sorted(zip(chapter_times, outline), key=lambda p: p[0])
    chapter_times = [p[0] for p in paired]
    outline = [p[1] for p in paired]
    for i in range(1, n_chapters):
        if chapter_times[i] <= chapter_times[i - 1]:
            chapter_times[i] = chapter_times[i - 1] + 1

    for sec, ts in zip(outline, chapter_times):
        sec["timestamp"] = int(ts)

    # --- Fix part timestamps ---
    for i, sec in enumerate(outline):
        parts = sec.get("part_outline", [])
        n_parts = len(parts)
        if n_parts == 0:
            continue
        ch_start = chapter_times[i]
        ch_end = chapter_times[i + 1] if i + 1 < n_chapters else total

        part_times: list[float] = []
        part_grounded: list[bool] = []
        for part in parts:
            kw = _extract_keywords(part.get("content", ""))
            ts = _find_segment(kw, start=ch_start, end=ch_end)
            if ts >= 0:
                part_times.append(ts)
                part_grounded.append(True)
            else:
                # LLM fallback, constrained to the chapter's window
                llm_ts = _safe_llm_ts(part.get("timestamp", 0), ch_start, ch_end)
                ts = float(llm_ts) if llm_ts is not None else 0.0
                part_times.append(ts)
                part_grounded.append(False)

        # Distribute zeros evenly within chapter window
        zero_pidx = [j for j, t in enumerate(part_times) if t == 0]
        if zero_pidx:
            span = ch_end - ch_start
            sub_step = span / (n_parts + 1)
            for k, zj in enumerate(zero_pidx):
                part_times[zj] = ch_start + sub_step * (k + 1)

        # Ensure within chapter bounds and increasing
        for j in range(n_parts):
            part_times[j] = max(ch_start, min(part_times[j], ch_end - 1))
            if j > 0 and part_times[j] <= part_times[j - 1]:
                part_times[j] = part_times[j - 1] + 1

        # Fix remaining overlaps: parts that are < 3 seconds apart.
        # Only redistribute when 3+ items form a cluster (regardless of
        # grounding) — this catches cases like 3 parts at 0:57/0:58/0:59.
        # 2-item clusters are left alone (common when both match the same
        # subtitle segment).
        _PART_OVERLAP = 3.0
        for j in range(1, n_parts):
            if part_times[j] - part_times[j - 1] < _PART_OVERLAP:
                chain_start = j - 1
                while chain_start > 0 and part_times[chain_start] - part_times[chain_start - 1] < _PART_OVERLAP:
                    chain_start -= 1
                chain_end = j
                while chain_end + 1 < n_parts and part_times[chain_end + 1] - part_times[chain_end] < _PART_OVERLAP:
                    chain_end += 1
                n = chain_end - chain_start + 1
                if n >= 3:
                    span = ch_end - ch_start
                    for idx in range(n):
                        part_times[chain_start + idx] = ch_start + span * (idx + 1) / (n + 1)
                break

        # Dedup + sort parts: ensure unique, strictly increasing timestamps
        # within the chapter window.
        part_paired = sorted(zip(part_times, parts), key=lambda p: p[0])
        part_times = [p[0] for p in part_paired]
        parts = [p[1] for p in part_paired]
        for j in range(1, n_parts):
            if part_times[j] <= part_times[j - 1]:
                part_times[j] = part_times[j - 1] + 1
            # Re-clamp after dedup bump
            part_times[j] = min(part_times[j], ch_end - 1)

        for part, ts in zip(parts, part_times):
            part["timestamp"] = int(ts)

    return outline


def _find_balanced_json(text: str, start: int) -> str | None:
    """Find a balanced JSON object starting at `start` index (must be `{`)."""
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def parse_outline_json(full_body: str) -> tuple[str, list[dict]]:
    """Split an LLM response into (markdown_body, outline).

    The outline is a 2-level structure extracted from the body, matching
    biliscope/B站's `conclusion` API shape:

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

    Extraction strategy (lenient):
    1. Try strict ```json ... ``` code fence first.
    2. If not found, search for `"outline"` in the text, go backwards to
       the nearest `{`, and use balanced-brace counting to extract the
       full JSON object.
    3. If parsing fails at any step → WARNING + (full_body, []).

    The extracted JSON block is always removed from the markdown body
    so users never see raw JSON in the summary text.

    Field types are coerced (string ``timestamp`` → int) so a sloppy LLM
    output still parses.  Sections with empty/missing ``part_outline``
    are dropped (avoids empty chapter rows in the UI).
    Never raises — a 90-second LLM call should not be wasted on a trailing comma.
    """
    md = full_body
    raw = None

    # --- Strategy 1: strict code fence ---
    pattern = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
    match = pattern.search(full_body)
    if match:
        md = (full_body[:match.start()] + full_body[match.end():]).strip()
        raw = match.group(1).strip()

    # --- Strategy 2: lenient — find "outline" or "chapters" key, extract balanced JSON ---
    if raw is None:
        # Look for the outline/chapters key anywhere in the body
        outline_idx = full_body.find('"outline"')
        if outline_idx == -1:
            outline_idx = full_body.find("'outline'")
        if outline_idx == -1:
            outline_idx = full_body.find('"chapters"')
        if outline_idx == -1:
            outline_idx = full_body.find("'chapters'")
        if outline_idx != -1:
            # Scan backwards from outline_idx to find the opening `{`
            for j in range(outline_idx - 1, -1, -1):
                if full_body[j] == '{':
                    candidate = _find_balanced_json(full_body, j)
                    if candidate:
                        # Remove the JSON block from markdown
                        md = (full_body[:j] + full_body[j + len(candidate):]).strip()
                        raw = candidate
                        break
                # Stop if we hit a markdown heading (but NOT newline —
                # LLMs often output bare JSON after a blank line)
                if full_body[j] == '#' and j > 0:
                    break

    # --- Parse ---
    if raw is None:
        return _strip_outline_section(md), []

    try:
        parsed = json.loads(raw)
        # Support both "outline" (old format) and "chapters" (new format)
        outline_raw = parsed.get("outline") or parsed.get("chapters") or []
        if not isinstance(outline_raw, list):
            raise ValueError("outline/chapters is not a list")
        clean: list[dict] = []
        for sec in outline_raw:
            if not isinstance(sec, dict):
                continue
            try:
                title = str(sec["title"])
            except (KeyError, TypeError, ValueError):
                continue
            # New "chapters" format: {title, summary} — no timestamps
            if "summary" in sec and "timestamp" not in sec:
                raw_summary = sec.get("summary", "")
                if isinstance(raw_summary, list):
                    # Array of bullet points
                    summary_items = [str(s).strip() for s in raw_summary if str(s).strip()]
                else:
                    # Single string
                    summary_items = [str(raw_summary).strip()] if str(raw_summary).strip() else []
                if not summary_items:
                    summary_items = [title]
                clean.append({
                    "title": title,
                    "timestamp": 0,
                    "summary": summary_items,
                })
                continue
            # Old "outline" format: {title, timestamp, part_outline}
            try:
                timestamp = int(sec["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            parts_raw = sec.get("part_outline", [])
            if not isinstance(parts_raw, list) or not parts_raw:
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
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("parse_outline_json: invalid JSON in LLM response, returning empty outline: %s", e)
        clean = []

    # Final defensive pass — strip the trailing 视频大纲 section header
    # (and any JSON still attached to it) from the markdown body. This
    # runs unconditionally because the heading itself leaks into the
    # rendered UI even after a successful JSON extraction, and a totally
    # malformed LLM output (no code fence, no `"outline"` key, garbled
    # characters) can leave the entire outline-section tail intact.
    return _strip_outline_section(md), clean


# Variants of the 视频大纲 section header seen in the wild. Light LLMs
# (mimo-v2-flash and similar) sometimes drop a leading `视` (→ `频大纲`)
# or the `## ` prefix (→ `视频大纲` inline). The first match is the canonical
# header; the others are corruption shapes we still want to strip.
_OUTLINE_SECTION_VARIANTS = ("视频大纲", "视大纲", "频大纲")


def _strip_outline_section(md: str) -> str:
    """Remove trailing 视频大纲 section and/or bare JSON from markdown.

    This is the final defensive pass: even when the upstream extraction
    strategies fail (no code fence, no balanced JSON, json.loads error),
    the outline-section tail of the body is never shown to the user.

    Two cases are handled:
    1. 视频大纲 section header (with or without ##/### prefix) — strip
       everything from the header onward.
    2. Bare JSON block at the end containing "outline" or "chapters" —
       strip the entire JSON object.  This catches LLMs that output
       JSON without a code fence and without a section header.

    Variants are tried in order from longest to shortest. The longest
    match wins so a corrupted shorter variant inside the canonical
    `视频大纲` (e.g. `频大纲` is a substring of `视频大纲`) doesn't
    cause the cut to land inside the section header itself.
    """
    # Case 1: 视频大纲 section header
    for variant in _OUTLINE_SECTION_VARIANTS:
        idx = md.rfind(variant)
        if idx >= 0:
            head = md[:idx]
            # Trim any trailing `##`/`###` markers and whitespace the
            # `rfind` cut left behind.
            head = re.sub(r"[ \t]*#+\s*$", "", head)
            return head.rstrip()

    # Case 2: bare JSON at the end (no section header, no code fence).
    # Find the last `{` and check if the balanced JSON contains "outline"
    # or "chapters".  Only strip if the JSON reaches the end of the text
    # (not embedded JSON in the middle of prose).
    last_brace = md.rfind('{')
    if last_brace >= 0:
        candidate = _find_balanced_json(md, last_brace)
        if candidate and last_brace + len(candidate) >= len(md) - 1:
            if '"outline"' in candidate or '"chapters"' in candidate:
                head = md[:last_brace].rstrip()
                # Also strip any trailing "视频大纲" text before the JSON
                for variant in _OUTLINE_SECTION_VARIANTS:
                    if head.endswith(variant):
                        head = head[:-len(variant)].rstrip()
                        break
                head = re.sub(r"[ \t]*#+\s*$", "", head)
                return head.rstrip()

    return md.rstrip()

