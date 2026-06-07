# AI Video Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI-powered video summary module to VidSumAI: paste a YouTube or B站 URL, get a 4-section text summary + clickable chapter timestamps that jump the existing `VideoPreview` to the right time. SSE streaming, file-based 30-day cache, `SUMMARY_MOCK` for offline dev.

**Architecture:** New independent service (`routers/summary.py` + `services/summarizer.py` + `services/summary_cache.py`) sits alongside the existing download flow. SSE (not WebSocket) streams the summary token-by-token; a single `chapters` event delivers structured `[{time, title}]` JSON at the end. Frontend adds a `useSSE` composable, a `VideoSummary.vue` panel mounted after parse, and a small `defineExpose` block on `VideoPreview.vue` so chapter clicks can call `setCurrentTime` + `play`.

**Tech Stack:** Backend = FastAPI (existing) + `openai` SDK (OpenAI-compatible, works with OpenAI / Anthropic / DeepSeek) + `sse-starlette` for `EventSourceResponse`. Frontend = Vue 3 + Nuxt 3 (existing) + `marked` for markdown rendering + native `fetch` + `ReadableStream` for SSE.

**Reference docs:**
- Design spec: `docs/superpowers/specs/2026-06-07-ai-video-summary-design.md`
- Reference impl (mirror): `github.com/liyupi/free-video-downloader/backend/summarizer.py` and `frontend/src/components/VideoSummary.vue`

**Project conventions (from CLAUDE.md):**
- Backend deps via `uv add`; never raw `pip` / `python`
- Windows paths; `os.path.join`; no Linux-only commands
- yt-dlp via Python API (`from yt_dlp import YoutubeDL`), not CLI
- pytest marker: `@pytest.mark.network` for tests that hit real services
- Backend tests: `cd backend && uv run pytest ...`
- Frontend dev: `cd frontend && npx nuxi dev`

---

## File Structure

### New backend files
```
backend/services/summarizer.py        # SubtitleExtractor + VideoSummarizer + MockSummarizer + build_summarizer factory
backend/services/summary_cache.py     # File-based summary cache (TTL 30d)
backend/routers/summary.py            # POST /api/summarize (SSE)
backend/tests/test_summarizer.py      # Unit tests
backend/tests/test_summary_cache.py   # Cache unit tests
```

### Modified backend files
```
backend/main.py                       # + include_router for summary
backend/models.py                     # + SubtitleSegment, SubtitleData, Chapter, SummarizeRequest
backend/pyproject.toml                # + openai
backend/.env.example                  # + OPENAI_API_KEY, SUMMARY_MODEL, SUMMARY_MOCK, etc.
.gitignore                            # + summary_cache.json
```

### New frontend files
```
frontend/composables/useSSE.ts        # SSE client (fetch + ReadableStream + AbortController)
frontend/components/VideoSummary.vue # Summary panel (4 tabs, dark theme)
```

### Modified frontend files
```
frontend/components/VideoPreview.vue  # + defineExpose({ play, pause, setCurrentTime, getCurrentTime })
frontend/pages/index.vue              # + AI 总结 button + videoPreviewRef + onChapterClick
frontend/types/index.ts               # + SubtitleData, SubtitleSegment, Chapter, ChapterList
frontend/package.json                 # + marked
```

---

## Phase 0: Setup

### Task 1: Add backend dependencies and env scaffolding

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add `openai` dependency via uv**

```bash
cd backend && uv add openai
```

Expected: `pyproject.toml` and `uv.lock` updated with `openai>=1.x`. The `[project] dependencies` array in `pyproject.toml` now includes `"openai>=1.0.0"`.

- [ ] **Step 2: Append to `backend/.env.example`**

Append (do not overwrite existing content):

```bash
# AI Summary — set OPENAI_API_KEY (or ANTHROPIC_API_KEY) for live mode.
# When SUMMARY_MOCK=true, OPENAI_API_KEY is not required.
OPENAI_API_KEY=sk-xxx
SUMMARY_MODEL=gpt-4o-mini
# SUMMARY_BASE_URL=https://api.deepseek.com   # uncomment to use DeepSeek
SUMMARY_MOCK=false
SUMMARY_MOCK_DELAY_MS=50
SUMMARY_TIMEOUT=90

# Cache
SUMMARY_CACHE_PATH=./summary_cache.json
SUMMARY_CACHE_TTL_DAYS=30
```

If `backend/.env.example` does not exist, create it with the content above (and any existing env keys from CLAUDE.md).

- [ ] **Step 3: Add cache file to root `.gitignore`**

Append to `.gitignore` (one new line):

```
backend/summary_cache.json
```

- [ ] **Step 4: Verify backend still imports**

```bash
cd backend && uv run python -c "from main import app; print('ok')"
```

Expected: prints `ok` (no ImportError; existing routers still work).

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/.env.example .gitignore
git commit -m "chore: add openai dep and AI summary env scaffolding"
```

---

## Phase 1: Data Models

### Task 2: Add Pydantic models for subtitle and chapter

**Files:**
- Modify: `backend/models.py` (append at end)

- [ ] **Step 1: Append the four new models to `backend/models.py`**

```python
class SubtitleSegment(BaseModel):
    start: float
    end: float
    text: str


class SubtitleData(BaseModel):
    has_subtitle: bool
    language: str = ""
    subtitle_type: str = "none"  # "manual" | "auto" | "none"
    is_target_language: bool = True
    fallback_mode: Optional[str] = None  # "metadata" when has_subtitle=False
    segments: List[SubtitleSegment] = []
    full_text: str = ""


class Chapter(BaseModel):
    time: int   # seconds
    title: str


class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"
```

- [ ] **Step 2: Verify models import and serialize**

```bash
cd backend && uv run python -c "
from models import SubtitleSegment, SubtitleData, Chapter, SummarizeRequest
s = SubtitleData(has_subtitle=False)
print(s.model_dump_json())
r = SummarizeRequest(url='https://x.com')
print(r.model_dump_json())
"
```

Expected: two JSON strings printed, no exception.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat(models): add SubtitleSegment, SubtitleData, Chapter, SummarizeRequest"
```

---

## Phase 2: SubtitleExtractor

### Task 3: Bilibili URL detection + helpers (TDD)

**Files:**
- Create: `backend/services/summarizer.py`
- Test: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Write failing test for `_is_bilibili_url`**

Create `backend/tests/test_summarizer.py` with:

```python
from services.summarizer import _is_bilibili_url, _time_to_seconds


def test_is_bilibili_url_matches_domains():
    assert _is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://bilibili.com/video/BV1xx411c7mD")
    assert _is_bilibili_url("https://b23.tv/abc123")
    assert _is_bilibili_url("https://www.bilibili.com/bangumi/play/ep123")


def test_is_bilibili_url_rejects_others():
    assert not _is_bilibili_url("https://www.youtube.com/watch?v=xxx")
    assert not _is_bilibili_url("https://www.douyin.com/video/123")
    assert not _is_bilibili_url("https://example.com")


def test_time_to_seconds():
    assert _time_to_seconds("00:00:00.000") == 0.0
    assert _time_to_seconds("00:01:30.500") == 90.5
    assert _time_to_seconds("01:02:03.456") == 3723.456
```

- [ ] **Step 2: Run test, verify it fails (ImportError)**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: `ImportError: cannot import name '_is_bilibili_url' from 'services.summarizer'`.

- [ ] **Step 3: Implement helpers in `backend/services/summarizer.py`**

```python
"""AI 视频总结模块：字幕提取 + LLM 总结 + Mock + 缓存。"""

import re
from typing import Optional


def _is_bilibili_url(url: str) -> bool:
    return "bilibili.com" in url or "b23.tv" in url


def _time_to_seconds(time_str: str) -> float:
    """HH:MM:SS.mmm → 秒数。"""
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds
```

- [ ] **Step 4: Run test, verify it passes**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add _is_bilibili_url and _time_to_seconds helpers"
```

---

### Task 4: VTT parser (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing tests for `_parse_vtt`**

```python
from services.summarizer import _parse_vtt


def test_parse_vtt_simple(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello world\n\n"
        "00:00:04.000 --> 00:00:06.500\n"
        "Second line\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[0]["end"] == 3.0
    assert segs[0]["text"] == "Hello world"
    assert segs[1]["start"] == 4.0
    assert segs[1]["end"] == 6.5


def test_parse_vtt_strips_html_tags(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "<c.color>Colored</c> text\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert segs[0]["text"] == "Colored text"


def test_parse_vtt_dedup_consecutive(tmp_path):
    f = tmp_path / "subs.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Same text\n\n"
        "00:00:02.500 --> 00:00:03.500\n"
        "Same text\n\n"
        "00:00:04.000 --> 00:00:05.000\n"
        "Different\n",
        encoding="utf-8",
    )
    segs = _parse_vtt(str(f))
    assert len(segs) == 2
    assert segs[0]["text"] == "Same text"
    assert segs[1]["text"] == "Different"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 3 new tests fail with `ImportError`.

- [ ] **Step 3: Implement `_parse_vtt` in `services/summarizer.py`**

Append:

```python
def _parse_vtt(filepath: str) -> list[dict]:
    """Parse a VTT file into [{start, end, text}, ...]. Strips HTML tags; dedups consecutive duplicates."""
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
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 6 tests pass (3 prior + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add _parse_vtt with HTML strip and dedup"
```

---

### Task 5: Subtitle priority picker (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing tests for `_pick_best_subtitle`**

```python
from services.summarizer import _pick_best_subtitle


def test_pick_prefers_manual_zh_hans():
    manual = {
        "en": [{"ext": "vtt", "url": "u-en"}],
        "zh-Hans": [{"ext": "vtt", "url": "u-zh"}],
    }
    auto = {}
    lang, url, kind = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert url == "u-zh"
    assert kind == "manual"


def test_pick_falls_back_to_other_lang_with_flag():
    manual = {"en": [{"ext": "vtt", "url": "u-en"}]}
    auto = {}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "en"
    assert url == "u-en"
    assert kind == "manual"
    assert is_target is False


def test_pick_falls_back_to_auto_when_no_manual():
    manual = {}
    auto = {"zh-Hans": [{"ext": "vtt", "url": "u-zh-auto"}]}
    lang, url, kind, is_target = _pick_best_subtitle(manual, auto, "zh")
    assert lang == "zh-Hans"
    assert kind == "auto"
    assert is_target is True


def test_pick_returns_empty_when_no_subtitles():
    lang, url, kind, is_target = _pick_best_subtitle({}, {}, "zh")
    assert lang == ""
    assert url is None
    assert is_target is False
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py::test_pick_prefers_manual_zh_hans -v
```

Expected: `TypeError: _pick_best_subtitle() takes 3 positional arguments but 4 were given` (current signature).

- [ ] **Step 3: Replace `_pick_best_subtitle` in `services/summarizer.py`**

```python
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
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add _pick_best_subtitle with target-language fallback"
```

---

### Task 6: Bilibili dm/view extractor (TDD, network)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing test (network-marked)**

```python
import pytest


@pytest.mark.network
def test_extract_bilibili_real_video():
    """Hit the real B站 API. Skip when offline."""
    from services.summarizer import _extract_bilibili

    result = _extract_bilibili("https://www.bilibili.com/video/BV1GJ411x7h7")
    assert result["has_subtitle"] is True
    assert result["language"] in ("zh-Hans", "zh", "ai-zh")
    assert result["subtitle_type"] in ("manual", "auto")
    assert len(result["segments"]) > 0
    assert result["segments"][0]["start"] >= 0
    assert result["segments"][0]["text"]  # non-empty
```

- [ ] **Step 2: Run test, verify it fails (or skips if offline)**

```bash
cd backend && uv run pytest tests/test_summarizer.py::test_extract_bilibili_real_video -v
```

Expected: fails with `AttributeError: module 'services.summarizer' has no attribute '_extract_bilibili'`. If your machine is offline, the test is skipped (acceptable; the implementation is still verified by manual smoke test).

- [ ] **Step 3: Implement `_extract_bilibili` in `services/summarizer.py`**

Append:

```python
import httpx


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
```

- [ ] **Step 4: Run test, verify it passes (or skips if offline)**

```bash
cd backend && uv run pytest tests/test_summarizer.py::test_extract_bilibili_real_video -v
```

Expected: passes OR skipped. Either is fine — the manual smoke test in Phase 9 will exercise the real path.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add _extract_bilibili via dm/view API"
```

---

### Task 7: `SubtitleExtractor.extract()` — the public entry point (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing test using a stubbed yt-dlp result**

```python
from unittest.mock import patch, MagicMock


def test_extract_returns_bilibili_result(monkeypatch):
    """When B站 extractor returns a result, use it directly without calling yt-dlp."""
    from services.summarizer import SubtitleExtractor

    bilibili_result = {
        "has_subtitle": True, "language": "zh-Hans", "subtitle_type": "manual",
        "is_target_language": True, "fallback_mode": None,
        "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
        "full_text": "你好",
    }
    monkeypatch.setattr("services.summarizer._extract_bilibili", lambda url: bilibili_result)
    monkeypatch.setattr("services.summarizer._get_video_info", MagicMock())

    result = SubtitleExtractor().extract("https://www.bilibili.com/video/BV1xx")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"


def test_extract_falls_back_to_ytdlp_for_non_bilibili(monkeypatch):
    """YouTube URLs go through yt-dlp; subtitles selected by priority."""
    from services.summarizer import SubtitleExtractor

    fake_info = {
        "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "u2"}]},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": f"text-{lang}"}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert result["has_subtitle"] is True
    assert result["language"] == "zh-Hans"
    assert result["is_target_language"] is True
    assert result["full_text"] == "text-zh-Hans"


def test_extract_no_subtitles_anywhere_returns_metadata_fallback(monkeypatch):
    """No subtitles + no metadata at all → has_subtitle=False, fallback_mode=None (caller decides)."""
    from services.summarizer import SubtitleExtractor

    fake_info = {"subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx")
    assert result["has_subtitle"] is False
    assert result["language"] == ""
    assert result["full_text"] == ""


def test_extract_truncates_full_text_to_15000_chars(monkeypatch):
    from services.summarizer import SubtitleExtractor

    long_text = "x" * 20000
    fake_info = {
        "subtitles": {"zh": [{"ext": "vtt", "url": "u1"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr("services.summarizer._get_video_info", lambda url: fake_info)
    monkeypatch.setattr(
        "services.summarizer._download_and_parse",
        lambda url, lang, sub_type: [{"start": 0.0, "end": 1.0, "text": long_text}],
    )

    result = SubtitleExtractor().extract("https://www.youtube.com/watch?v=xxx", language="zh")
    assert len(result["full_text"]) == 15000
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v -k "extract"
```

Expected: 4 new tests fail with `ImportError: cannot import name 'SubtitleExtractor'`.

- [ ] **Step 3: Implement the `SubtitleExtractor` class and helpers in `services/summarizer.py`**

Append:

```python
import json
import os
import tempfile

from yt_dlp import YoutubeDL


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
```

- [ ] **Step 4: Run all summarizer tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 14 tests pass (10 prior + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add SubtitleExtractor.extract() public API"
```

---

## Phase 3: Summary Cache

### Task 8: `SummaryCache` class (TDD, all in one go)

**Files:**
- Create: `backend/services/summary_cache.py`
- Create: `backend/tests/test_summary_cache.py`

- [ ] **Step 1: Write failing tests for cache set/get/key/expiry/atomic/corrupt**

Create `backend/tests/test_summary_cache.py`:

```python
import json
import time
from pathlib import Path

import pytest

from services.summary_cache import SummaryCache, _make_cache_key


# --- key ---

def test_make_cache_key_is_deterministic():
    k1 = _make_cache_key("https://x.com", "zh")
    k2 = _make_cache_key("https://x.com", "zh")
    assert k1 == k2
    assert len(k1) == 16  # md5 truncated to 16 chars


def test_make_cache_key_differs_by_language():
    assert _make_cache_key("https://x.com", "zh") != _make_cache_key("https://x.com", "en")


def test_make_cache_key_differs_by_url():
    assert _make_cache_key("https://a.com", "zh") != _make_cache_key("https://b.com", "zh")


# --- set / get round trip ---

def test_set_then_get_round_trip(tmp_path):
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    data = {
        "summary_md": "## 视频概述\nhi",
        "chapters": [{"time": 0, "title": "开场"}],
        "subtitle_meta": {"has_subtitle": True, "language": "zh"},
        "cached_at": "2026-06-07T10:00:00Z",
    }
    cache.set("https://x.com", "zh", data)
    got = cache.get("https://x.com", "zh")
    assert got == data


def test_get_returns_none_for_unknown_key(tmp_path):
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    assert cache.get("https://x.com", "zh") is None


# --- expiry ---

def test_expired_entry_returns_none_and_is_deleted(tmp_path):
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    data = {"summary_md": "x", "chapters": [], "subtitle_meta": {}, "cached_at": "2020-01-01T00:00:00Z"}
    cache.set("https://x.com", "zh", data)
    # Manually rewrite the file with an old timestamp to simulate expiry
    raw = json.loads((tmp_path / "cache.json").read_text())
    raw["https://x.com|zh"]["cached_at"] = "2020-01-01T00:00:00Z"
    (tmp_path / "cache.json").write_text(json.dumps(raw))
    assert cache.get("https://x.com", "zh") is None
    # Should have been pruned
    raw2 = json.loads((tmp_path / "cache.json").read_text())
    assert "https://x.com|zh" not in raw2


# --- atomic write ---

def test_atomic_write_no_partial_file_on_disk(tmp_path):
    """After set(), the cache file is parseable (no .tmp leftovers)."""
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    cache.set("https://x.com", "zh", {"summary_md": "x", "chapters": [], "subtitle_meta": {}, "cached_at": "2026-06-07T00:00:00Z"})
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []
    # And the file is valid JSON
    (tmp_path / "cache.json").read_text()  # no JSON decode error


# --- corrupt file ---

def test_corrupt_file_treated_as_empty_cache(tmp_path):
    f = tmp_path / "cache.json"
    f.write_text("not valid json {{{")
    cache = SummaryCache(path=f, ttl_days=30)
    assert cache.get("https://x.com", "zh") is None
    # set() should still work and recover
    cache.set("https://x.com", "zh", {"summary_md": "x", "chapters": [], "subtitle_meta": {}, "cached_at": "2026-06-07T00:00:00Z"})
    assert cache.get("https://x.com", "zh") is not None
```

- [ ] **Step 2: Run tests, verify they fail (ImportError)**

```bash
cd backend && uv run pytest tests/test_summary_cache.py -v
```

Expected: all 8 tests fail with `ImportError`.

- [ ] **Step 3: Implement `SummaryCache` in `backend/services/summary_cache.py`**

```python
"""File-based cache for AI video summaries.

Backing store: a single JSON file keyed by md5(url|language)[:16].
TTL is enforced lazily on access; expired entries are deleted on read.
Writes are atomic (write to .tmp, then os.replace) so a crash mid-write
can't corrupt the cache.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _make_cache_key(url: str, language: str) -> str:
    return hashlib.md5(f"{url}|{language}".encode("utf-8")).hexdigest()[:16]


@dataclass
class CachedSummary:
    summary_md: str
    chapters: list[dict]
    subtitle_meta: dict
    cached_at: str  # ISO 8601


class SummaryCache:
    def __init__(self, path: Path, ttl_days: int = 30):
        self.path = Path(path)
        self.ttl = timedelta(days=ttl_days)

    def get(self, url: str, language: str) -> Optional[CachedSummary]:
        key = _make_cache_key(url, language)
        data = self._read()
        entry = data.get(key)
        if not entry:
            return None
        # Check expiry
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if datetime.now(timezone.utc) - cached_at > self.ttl:
            # Lazy delete
            del data[key]
            self._write(data)
            return None
        return CachedSummary(
            summary_md=entry["summary_md"],
            chapters=entry["chapters"],
            subtitle_meta=entry["subtitle_meta"],
            cached_at=entry["cached_at"],
        )

    def set(self, url: str, language: str, data: CachedSummary) -> None:
        key = _make_cache_key(url, language)
        all_data = self._read()
        all_data[key] = {
            "summary_md": data.summary_md,
            "chapters": data.chapters,
            "subtitle_meta": data.subtitle_meta,
            "cached_at": data.cached_at,
        }
        self._write(all_data)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt file → start fresh. Log warning in real life.
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summary_cache.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summary_cache.py backend/tests/test_summary_cache.py
git commit -m "feat(cache): add SummaryCache with TTL + atomic writes"
```

---

## Phase 4: VideoSummarizer + Mock

### Task 9: `build_summarizer` factory + API key check (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing tests for the factory and API key validation**

```python
import os


def test_build_summarizer_raises_without_api_key_when_not_mock(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_summarizer()


def test_build_summarizer_returns_mock_when_env_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "true")

    from services.summarizer import build_summarizer, MockSummarizer
    s = build_summarizer()
    assert isinstance(s, MockSummarizer)


def test_build_summarizer_returns_real_with_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import build_summarizer, VideoSummarizer
    s = build_summarizer()
    assert isinstance(s, VideoSummarizer)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v -k "build_summarizer"
```

Expected: 3 new tests fail with `ImportError`.

- [ ] **Step 3: Append factory + skeletons to `services/summarizer.py`**

```python
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
```

Also append at top of file (if not present): `import os` (it's already in the existing import block — verify).

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v -k "build_summarizer"
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add build_summarizer factory + MockSummarizer skeleton"
```

---

### Task 10: `summarize_stream` with fake OpenAI client (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing tests for streaming with a fake client**

```python
class FakeChunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]


class FakeStreamingResponse:
    def __init__(self, tokens):
        self._tokens = tokens

    def __iter__(self):
        return iter([FakeChunk(t) for t in self._tokens])


def test_summarize_stream_yields_all_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_MODEL", "fake-model")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    s.client.chat.completions.create = lambda **kwargs: FakeStreamingResponse(["Hi", " there", "!"])

    tokens = list(s.summarize_stream("subtitle text here", "zh"))
    assert "".join(tokens) == "Hi there!"


def test_summarize_stream_uses_standard_prompt_for_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["model"] = kwargs.get("model")
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("字幕内容", "zh", has_subtitle=True))
    prompt = captured["messages"][1]["content"]
    assert "视频概述" in prompt
    assert "章节时间戳" in prompt
    assert "字幕内容" in prompt


def test_summarize_stream_uses_fallback_prompt_without_subtitles(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "10")
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import VideoSummarizer
    s = VideoSummarizer()
    captured = {}
    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeStreamingResponse(["x"])
    s.client.chat.competions.create = fake_create if False else s.client.chat.completions.create
    s.client.chat.completions.create = fake_create

    list(s.summarize_stream("video title here", "zh", has_subtitle=False, video_meta={"title": "X", "duration": 600}))
    prompt = captured["messages"][1]["content"]
    assert "没有可用的字幕" in prompt
    assert "X" in prompt
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v -k "summarize_stream"
```

Expected: 3 tests fail with `TypeError: summarize_stream() got unexpected keyword argument 'has_subtitle'`.

- [ ] **Step 3: Implement `summarize_stream` + prompt builders in `services/summarizer.py`**

```python
SUMMARY_PROMPT_STANDARD = """请对以下视频字幕内容进行深度总结分析，使用 {language} 输出。

视频时长：{duration} 秒。

## 输出结构

### 1. 视频概述
（用 2-3 句话概括视频的主题和核心内容）

### 2. 内容大纲
（按视频内容的逻辑顺序，列出主要章节/段落。
 **章节数量请按视频时长动态调整**：
  - 时长 < 600 秒（< 10 分钟）：2-4 个章节
  - 时长 600-1800 秒（10-30 分钟）：4-6 个章节
  - 时长 1800-3600 秒（30-60 分钟）：6-8 个章节
  - 时长 > 3600 秒（> 60 分钟）：8-12 个章节
 每个章节用一个 `### ` 三级标题，标题文字简洁（≤ 20 字）。
 **不要在标题里嵌入时间戳**——时间戳放到最后的 JSON 块里。）

### 3. 核心知识要点
（提取视频中最重要的知识点、观点或结论，用编号列表形式。最多 8 条。）

### 4. 总结
（用 1-2 句话给出整体评价或一句话总结）

### 5. 章节时间戳（必须输出，结构化 JSON）
**在所有 markdown 之后，另起一行输出一个 JSON 代码块**，格式严格如下：

```json
{{"chapters": [{{"time": 83, "title": "GPT 的核心机制"}}, {{"time": 347, "title": "实际应用案例"}}]}}
```

要求：
- `time` 是整数秒（不是字符串，**不要加引号**）
- 章节顺序按视频中出现的先后顺序
- 章节数量与上面"内容大纲"的章节数量**完全一致**
- 标题文字必须与"内容大纲"中对应章节**完全一致**
- JSON 必须能被 `json.loads` 解析（双引号、无尾逗号、无注释）

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

### 3. 核心知识要点
（基于标题推测可能的要点，最多 3 条；不要编造具体细节）

### 4. 总结
（提醒用户此总结基于元数据，强烈建议观看原视频）

### 5. 章节时间戳
输出一个**空数组**：
```json
{{"chapters": []}}
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


# Add to VideoSummarizer class:

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
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 20 tests pass (17 prior + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add summarize_stream with standard/fallback prompts"
```

---

### Task 11: `MockSummarizer.summarize_stream` (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing test for mock streaming**

```python
def test_mock_summarizer_streams_body_and_includes_json():
    from services.summarizer import MockSummarizer
    s = MockSummarizer()
    s.DELAY_MS = 0  # instant for test
    tokens = list(s.summarize_stream("ignored", "zh"))
    body = "".join(tokens)
    assert "## 视频概述" in body
    assert '"chapters"' in body
    assert body.endswith("```\n")
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd backend && uv run pytest tests/test_summarizer.py::test_mock_summarizer_streams_body_and_includes_json -v
```

Expected: fails with `TypeError: MockSummarizer.summarize_stream() missing 1 required positional argument`.

- [ ] **Step 3: Add `summarize_stream` to `MockSummarizer` in `services/summarizer.py`**

```python
# Append to MockSummarizer class:

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
```

- [ ] **Step 4: Run test, verify it passes**

```bash
cd backend && uv run pytest tests/test_summarizer.py::test_mock_summarizer_streams_body_and_includes_json -v
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add MockSummarizer.summarize_stream"
```

---

### Task 12: Chapter JSON parser (TDD)

**Files:**
- Modify: `backend/services/summarizer.py`
- Modify: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Append failing tests for `parse_chapter_json`**

```python
from services.summarizer import parse_chapter_json


def test_parse_chapter_json_valid():
    body = (
        "## 视频概述\nhi\n"
        "## 内容大纲\nblah\n"
        "```json\n"
        '{"chapters": [{"time": 0, "title": "开场"}, {"time": 90, "title": "中段"}]}\n'
        "```\n"
    )
    md, chapters = parse_chapter_json(body)
    assert "## 视频概述" in md
    assert "```json" not in md
    assert chapters == [{"time": 0, "title": "开场"}, {"time": 90, "title": "中段"}]


def test_parse_chapter_json_no_json_block():
    body = "## 视频概述\nno chapters here"
    md, chapters = parse_chapter_json(body)
    assert md == body
    assert chapters == []


def test_parse_chapter_json_invalid_returns_empty(caplog):
    body = "## 视频概述\n```json\n{this is not valid json}\n```\n"
    md, chapters = parse_chapter_json(body)
    assert "## 视频概述" in md
    assert chapters == []


def test_parse_chapter_json_strips_preceding_markdown():
    body = "Some intro\n```json\n" + json.dumps({"chapters": [{"time": 5, "title": "x"}]}) + "\n```"
    md, chapters = parse_chapter_json(body)
    assert "Some intro" in md
    assert chapters == [{"time": 5, "title": "x"}]
```

Add at top of test file: `import json` (already in test_summary_cache.py; need to add to test_summarizer.py if not present).

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v -k "parse_chapter_json"
```

Expected: 4 new tests fail with `ImportError`.

- [ ] **Step 3: Implement `parse_chapter_json` in `services/summarizer.py`**

```python
import logging

logger = logging.getLogger(__name__)


def parse_chapter_json(full_body: str) -> tuple[str, list[dict]]:
    """Split an LLM response into (markdown_body, chapters).

    The chapters are extracted from the first ```json ... ``` block in the body.
    On parse failure, the markdown body is preserved and chapters is empty (logged WARNING).
    Never raises — a 90-second LLM call should not be wasted because of a trailing comma.
    """
    # Find the json code block
    pattern = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
    match = pattern.search(full_body)
    if not match:
        return full_body, []

    md = (full_body[:match.start()] + full_body[match.end():]).strip()
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
        chapters = parsed.get("chapters", [])
        if not isinstance(chapters, list):
            raise ValueError("chapters is not a list")
        # Validate each chapter
        clean = []
        for c in chapters:
            if not isinstance(c, dict) or "time" not in c or "title" not in c:
                raise ValueError(f"malformed chapter entry: {c}")
            clean.append({"time": int(c["time"]), "title": str(c["title"])})
        return md, clean
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("parse_chapter_json: invalid JSON in LLM response, returning empty chapters: %s", e)
        return full_body, []
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summarizer.py -v
```

Expected: 24 tests pass (20 prior + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat(summarizer): add parse_chapter_json with graceful fallback"
```

---

## Phase 5: SSE Router

### Task 13: SSE endpoint skeleton + cache hit (TDD)

**Files:**
- Create: `backend/routers/summary.py`
- Create: `backend/tests/test_summary_router.py`
- Modify: `backend/main.py` (later in this task)

- [ ] **Step 1: Append failing test for cache-hit short-circuit**

Create `backend/tests/test_summary_router.py`:

```python
import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


def _parse_sse(text: str) -> list[tuple[str, str]]:
    """Parse an SSE response body into [(event, data), ...]."""
    out = []
    cur_event, cur_data = None, []
    for line in text.split("\n"):
        if line == "":
            if cur_event is not None and cur_data:
                out.append((cur_event, "\n".join(cur_data)))
            cur_event, cur_data = None, []
        elif line.startswith(":"):
            continue
        elif ":" in line:
            field, _, val = line.partition(":")
            val = val.lstrip(" ")
            if field == "event":
                cur_event = val
            elif field == "data":
                cur_data.append(val)
    return out


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_to_done(tmp_path, monkeypatch):
    """When the URL+language is in the cache, no subtitle/summary events are emitted."""
    # Pre-seed the cache
    from services.summary_cache import SummaryCache
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    cache.set(
        "https://example.com/cached",
        "zh",
        {
            "summary_md": "## cached summary",
            "chapters": [{"time": 0, "title": "x"}],
            "subtitle_meta": {"has_subtitle": True, "language": "zh", "subtitle_type": "manual"},
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST",
            "/api/summarize",
            json={"url": "https://example.com/cached", "language": "zh"},
        ) as r:
            assert r.status_code == 200
            text = await r.aread()
            text = text.decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]
            assert event_names[0] == "cache_hit"
            assert "done" in event_names
            # No subtitle/summary/chapters events on cache hit
            assert "subtitle" not in event_names
            assert "summary" not in event_names
            assert "chapters" not in event_names
```

- [ ] **Step 2: Run test, verify it fails (404 / no route)**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: `404 Not Found` for `/api/summarize` (router not yet mounted).

- [ ] **Step 3: Create `backend/routers/summary.py` with the skeleton**

```python
"""AI 视频总结路由 — SSE 流式端点。"""

import asyncio
import json
import os
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.summarizer import (
    SubtitleExtractor,
    build_summarizer,
    parse_chapter_json,
)
from services.summary_cache import SummaryCache

router = APIRouter()


class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"


# Lazy singletons (initialized on first request)
_extractor: SubtitleExtractor | None = None
_cache: SummaryCache | None = None


def _get_cache() -> SummaryCache:
    global _cache
    if _cache is None:
        path = Path(os.getenv("SUMMARY_CACHE_PATH", "./summary_cache.json"))
        ttl = int(os.getenv("SUMMARY_CACHE_TTL_DAYS", "30"))
        _cache = SummaryCache(path=path, ttl_days=ttl)
    return _cache


def _get_extractor() -> SubtitleExtractor:
    global _extractor
    if _extractor is None:
        _extractor = SubtitleExtractor()
    return _extractor


def _sse(event: str, data) -> str:
    """Format a single SSE event. `data` is serialized to JSON."""
    if isinstance(data, (dict, list)):
        data_str = json.dumps(data, ensure_ascii=False)
    else:
        data_str = str(data)
    return f"event: {event}\ndata: {data_str}\n\n"


@router.post("/summarize")
async def summarize(req: SummarizeRequest) -> StreamingResponse:
    """Stream an AI video summary as SSE events."""
    # Cache lookup (short-circuit if hit)
    cache = _get_cache()
    cached = cache.get(req.url, req.language)
    if cached is not None:
        async def gen():
            yield _sse("cache_hit", {
                "summary": cached.summary_md,
                "chapters": cached.chapters,
                "subtitle_meta": cached.subtitle_meta,
                "cached_at": cached.cached_at,
            })
            yield _sse("done", "[DONE]")
        return StreamingResponse(gen(), media_type="text/event-stream")

    # Fall through to the streaming path (added in Task 14)
    raise HTTPException(status_code=501, detail="Not implemented in this task")
```

- [ ] **Step 4: Mount the router in `backend/main.py`**

Add one line after the existing `include_router(download.router, ...)` call:

```python
from routers import download, summary  # extend the existing import

app.include_router(summary.router, prefix="/api")
```

- [ ] **Step 5: Run test, verify it passes**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/summary.py backend/main.py backend/tests/test_summary_router.py
git commit -m "feat(summary): SSE endpoint skeleton with cache-hit short-circuit"
```

---

### Task 14: Full streaming flow (subtitle → summary → chapters) (TDD)

**Files:**
- Modify: `backend/routers/summary.py`
- Modify: `backend/tests/test_summary_router.py`

- [ ] **Step 1: Append failing test for the full streaming flow (no subtitles, no metadata → error)**

```python
@pytest.mark.asyncio
async def test_no_subtitle_and_no_metadata_emits_error(tmp_path, monkeypatch):
    """Subtitle extraction returns empty, video has no metadata → SSE error event."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))

    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": False, "language": "", "subtitle_type": "none",
                "is_target_language": False, "fallback_mode": None,
                "segments": [], "full_text": ""}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/no-sub", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]
            assert "error" in event_names
            err = next(d for e, d in events if e == "error")
            err_data = json.loads(err)
            assert "既无字幕也无元数据" in err_data["message"]


@pytest.mark.asyncio
async def test_full_flow_with_subtitles_emits_all_events(tmp_path, monkeypatch):
    """Subtitles found → subtitle → summary (tokens) → chapters → done."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")

    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": True, "language": "zh-Hans", "subtitle_type": "manual",
                "is_target_language": True, "fallback_mode": None,
                "segments": [{"start": 0, "end": 1, "text": "你好"}],
                "full_text": "你好"}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/with-sub", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]
            assert event_names[0] == "subtitle"
            assert "summary" in event_names
            assert "chapters" in event_names
            assert event_names[-1] == "done"

            # Verify chapters are valid JSON with the expected shape
            chapters_data = json.loads(next(d for e, d in events if e == "chapters"))
            assert "chapters" in chapters_data
            assert isinstance(chapters_data["chapters"], list)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: 2 new tests fail with 501 (or 404 for the no-subtitle one if the route is missing).

- [ ] **Step 3: Implement the full streaming flow in `routers/summary.py`**

Replace the `summarize` function and helpers with:

```python
@router.post("/summarize")
async def summarize(req: SummarizeRequest) -> StreamingResponse:
    cache = _get_cache()

    # Cache lookup
    cached = cache.get(req.url, req.language)
    if cached is not None:
        async def gen():
            yield _sse("cache_hit", {
                "summary": cached.summary_md,
                "chapters": cached.chapters,
                "subtitle_meta": cached.subtitle_meta,
                "cached_at": cached.cached_at,
            })
            yield _sse("done", "[DONE]")
        return StreamingResponse(gen(), media_type="text/event-stream")

    # No cache → run the full flow
    return StreamingResponse(
        _stream_summary(req, cache),
        media_type="text/event-stream",
    )


async def _stream_summary(req: SummarizeRequest, cache: SummaryCache) -> AsyncIterable[str]:
    loop = asyncio.get_event_loop()
    extractor = _get_extractor()

    # Step 1: extract subtitles (blocking → thread)
    try:
        subtitle = await loop.run_in_executor(None, extractor.extract, req.url, req.language)
    except Exception as e:
        yield _sse("error", {"message": f"无法获取字幕：{e}"})
        return

    if not subtitle["has_subtitle"]:
        # Try metadata fallback (we don't have video info in this path; signal user via error)
        yield _sse("error", {
            "message": "该视频既无字幕也无元数据，无法生成总结。",
            "code": "no_content",
        })
        return

    # Step 2: send subtitle event
    yield _sse("subtitle", subtitle)

    # Step 3: stream summary tokens + collect
    summarizer = build_summarizer()
    accumulated: list[str] = []
    timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))
    full_text_len = len(subtitle.get("full_text") or "")
    effective_timeout = max(timeout, full_text_len // 200)

    try:
        async def run_summarize():
            for tok in summarizer.summarize_stream(
                subtitle.get("full_text", ""),
                req.language,
                has_subtitle=True,
            ):
                accumulated.append(tok)
                yield _sse("summary", tok)

        # Run the stream in a thread, forward tokens, enforce timeout
        gen = run_summarize()
        while True:
            try:
                chunk = await asyncio.wait_for(gen.__anext__(), timeout=effective_timeout)
                yield chunk
            except StopAsyncIteration:
                break
    except asyncio.TimeoutError:
        yield _sse("error", {"message": f"AI 总结超时（{effective_timeout}s），请重试或换一个较短的字幕", "code": "timeout"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"AI 总结服务暂时不可用：{e}", "code": "llm_error"})
        return

    # Step 4: parse chapters from accumulated body
    full_body = "".join(accumulated)
    md, chapters = parse_chapter_json(full_body)
    yield _sse("chapters", {"chapters": chapters})

    # Step 5: write to cache
    cache.set(req.url, req.language, {
        "summary_md": md,
        "chapters": chapters,
        "subtitle_meta": {k: subtitle[k] for k in ("has_subtitle", "language", "subtitle_type", "is_target_language")},
        "cached_at": datetime.now(timezone.utc).isoformat(),
    })

    yield _sse("done", "[DONE]")
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/summary.py backend/tests/test_summary_router.py
git commit -m "feat(summary): full streaming flow (subtitle → summary → chapters → done)"
```

---

### Task 15: Mock mode + metadata-fallback flows (TDD)

**Files:**
- Modify: `backend/routers/summary.py`
- Modify: `backend/tests/test_summary_router.py`

- [ ] **Step 1: Append failing tests for the no-subtitle-with-metadata fallback**

```python
@pytest.mark.asyncio
async def test_no_subtitle_falls_back_to_metadata_prompt(tmp_path, monkeypatch):
    """When subtitle extraction returns empty but yt-dlp gives us title/duration, use the metadata prompt."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")

    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": False, "language": "", "subtitle_type": "none",
                "is_target_language": False, "fallback_mode": None,
                "segments": [], "full_text": ""}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    # Stub _get_video_info to return metadata
    from services import summarizer as s_mod
    monkeypatch.setattr(
        s_mod, "_get_video_info",
        lambda url: {"title": "测试视频标题", "duration": 600, "uploader": "测试频道"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/meta-only", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]
            # Should fall through to the metadata-fallback path
            assert "subtitle" in event_names
            sub_data = json.loads(next(d for e, d in events if e == "subtitle"))
            assert sub_data["fallback_mode"] == "metadata"
            assert "chapters" in event_names  # mock body has chapters
            chapters_data = json.loads(next(d for e, d in events if e == "chapters"))
            # Fallback prompt produces empty chapters
            assert chapters_data["chapters"] == []
```

Also add a test that the prompt builder for fallback gets the right title:

```python
def test_fallback_prompt_contains_title():
    from services.summarizer import _build_fallback_prompt
    p = _build_fallback_prompt("My Talk", "YouTube", 1800, "zh")
    assert "My Talk" in p
    assert "YouTube" in p
    assert "1800" in p
    assert "30 分钟" in p
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v -k "metadata or fallback_prompt"
```

Expected: 2 tests fail (one because the router doesn't fall back, one because the prompt builder doesn't format duration_min).

- [ ] **Step 3: Update the router's "no subtitle" branch in `routers/summary.py`**

Replace the no-subtitle branch with the metadata fallback:

```python
    if not subtitle["has_subtitle"]:
        # Try to get metadata for fallback
        video_meta: dict = {}
        try:
            from services.summarizer import _get_video_info
            info = await loop.run_in_executor(None, _get_video_info, req.url)
            video_meta = {
                "title": info.get("title", ""),
                "duration": info.get("duration", 0) or 0,
                "platform": info.get("extractor", "unknown"),
            }
        except Exception:
            pass

        if not video_meta.get("title") and not video_meta.get("duration"):
            yield _sse("error", {
                "message": "该视频既无字幕也无元数据，无法生成总结。",
                "code": "no_content",
            })
            return

        # Mark as metadata fallback
        subtitle = {
            "has_subtitle": False,
            "language": "",
            "subtitle_type": "none",
            "is_target_language": False,
            "fallback_mode": "metadata",
            "segments": [],
            "full_text": "",
            "video_meta": video_meta,
        }
        yield _sse("subtitle", subtitle)

        # Continue with fallback prompt
        summarizer = build_summarizer()
        accumulated: list[str] = []
        timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))
        try:
            gen = _stream_fallback(summarizer, video_meta, req.language, timeout)
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                    accumulated.append(_strip_data(chunk))
                    yield chunk
                except StopAsyncIteration:
                    break
        except asyncio.TimeoutError:
            yield _sse("error", {"message": f"AI 总结超时（{timeout}s）", "code": "timeout"})
            return
        except Exception as e:
            yield _sse("error", {"message": f"AI 总结服务暂时不可用：{e}", "code": "llm_error"})
            return

        # Chapters (always empty for fallback)
        yield _sse("chapters", {"chapters": []})
        yield _sse("done", "[DONE]")
        return

    # ... rest of the function (subtitle-found path) is unchanged
```

Add two helpers to `routers/summary.py`:

```python
import re as _re

def _strip_data(sse_chunk: str) -> str:
    """Extract the data portion of an SSE chunk for accumulation."""
    m = _re.search(r"^data: (.*)$", sse_chunk, _re.MULTILINE)
    return m.group(1) if m else ""


async def _stream_fallback(summarizer, video_meta: dict, language: str, timeout: int):
    """Async wrapper around summarizer.summarize_stream(..., has_subtitle=False)."""
    loop = asyncio.get_event_loop()
    from services.summarizer import _build_fallback_prompt
    # Re-use the standard streaming code path; just feed it the fallback prompt via the existing API
    gen = summarizer.summarize_stream(
        video_meta.get("title", ""),  # subtitle_text param (unused for fallback)
        language,
        has_subtitle=False,
        video_meta=video_meta,
    )
    for tok in gen:
        yield _sse("summary", tok)
```

- [ ] **Step 4: Run all router tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: 4 tests pass (3 prior + 2 new — actually 5 if you count the prompt-builder test).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/summary.py backend/tests/test_summary_router.py
git commit -m "feat(summary): metadata-fallback path when no subtitles"
```

---

### Task 16: Error handling — missing API key and timeout (TDD)

**Files:**
- Modify: `backend/routers/summary.py`
- Modify: `backend/tests/test_summary_router.py`

- [ ] **Step 1: Append failing tests for the two error paths**

```python
@pytest.mark.asyncio
async def test_missing_api_key_emits_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUMMARY_MOCK", "false")

    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": True, "language": "zh", "subtitle_type": "manual",
                "is_target_language": True, "fallback_mode": None,
                "segments": [{"start": 0, "end": 1, "text": "x"}],
                "full_text": "x"}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/x", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            err = next((d for e, d in events if e == "error"), None)
            assert err is not None
            err_data = json.loads(err)
            assert "OPENAI_API_KEY" in err_data["message"]


@pytest.mark.asyncio
async def test_timeout_emits_error(tmp_path, monkeypatch):
    """When the LLM hangs, the SSE stream emits a timeout error after SUMMARY_TIMEOUT seconds."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "1")  # 1 second

    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": True, "language": "zh", "subtitle_type": "manual",
                "is_target_language": True, "fallback_mode": None,
                "segments": [{"start": 0, "end": 1, "text": "x"}],
                "full_text": "x"}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    # Replace mock summarizer with a hanging one
    import time
    from services.summarizer import MockSummarizer
    def hang(self, subtitle_text, language="zh", **kwargs):
        time.sleep(5)  # way past the 1s timeout
        yield "x"
    monkeypatch.setattr(MockSummarizer, "summarize_stream", hang)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/timeout", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            err = next((d for e, d in events if e == "error"), None)
            assert err is not None
            err_data = json.loads(err)
            assert "超时" in err_data["message"]
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v -k "missing_api_key or timeout"
```

Expected: 2 new tests fail (the existing implementation doesn't catch these errors specifically).

- [ ] **Step 3: Wrap `summarizer = build_summarizer()` in a try/except in `routers/summary.py`**

In the subtitle-found path, wrap the summarizer construction:

```python
    try:
        summarizer = build_summarizer()
    except ValueError as e:
        yield _sse("error", {"message": str(e), "code": "config_error"})
        return
```

Ensure the existing timeout check uses `effective_timeout` (max of SUMMARY_TIMEOUT and length-based):

```python
    timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))
    full_text_len = len(subtitle.get("full_text") or "")
    effective_timeout = max(timeout, full_text_len // 200)
```

(The Task 14 code already does this; verify the variable is in scope at the timeout point.)

- [ ] **Step 4: Run all router tests, verify they pass**

```bash
cd backend && uv run pytest tests/test_summary_router.py -v
```

Expected: 6 tests pass (4 prior + 2 new).

- [ ] **Step 5: Run the full backend test suite as a regression check**

```bash
cd backend && uv run pytest
```

Expected: all tests pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/summary.py backend/tests/test_summary_router.py
git commit -m "feat(summary): handle missing API key and LLM timeout errors"
```

---

## Phase 6: Frontend Types + useSSE

### Task 17: Add TypeScript types for subtitle and chapter

**Files:**
- Modify: `frontend/types/index.ts`

- [ ] **Step 1: Append new types**

```ts
export interface SubtitleSegment {
  start: number
  end: number
  text: string
}

export interface SubtitleData {
  has_subtitle: boolean
  language: string
  subtitle_type: 'manual' | 'auto' | 'none'
  is_target_language: boolean
  fallback_mode?: 'metadata'
  segments: SubtitleSegment[]
  full_text: string
}

export interface Chapter {
  time: number
  title: string
}

export interface ChapterList {
  chapters: Chapter[]
}
```

- [ ] **Step 2: Verify the file type-checks**

```bash
cd frontend && npx tsc --noEmit types/index.ts
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/types/index.ts
git commit -m "feat(types): add SubtitleData, Chapter interfaces for AI summary"
```

---

### Task 18: `useSSE` composable

**Files:**
- Create: `frontend/composables/useSSE.ts`

- [ ] **Step 1: Implement `useSSE.ts`**

```ts
/**
 * SSE client using fetch + ReadableStream.
 *
 * Returns an object with an `abort()` function. Wire format is parsed
 * from the standard SSE event-stream format (event: / data: lines
 * separated by blank lines).
 *
 * Usage:
 *   const { abort } = useSSE('/api/summarize', { url, language }, {
 *     subtitle: (data) => { ... },
 *     summary: (data) => { ... },
 *     chapters: (data) => { ... },
 *     done: () => { ... },
 *     error: (data) => { ... },
 *   })
 *   // later: abort()
 */

export interface SseCallbacks {
  [event: string]: (data: unknown) => void
}

export function useSSE(
  url: string,
  body: unknown,
  callbacks: SseCallbacks
): { abort: () => void } {
  const controller = new AbortController()

  const dispatch = async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) {
        callbacks.error?.({ message: `HTTP ${response.status}` })
        return
      }
      if (!response.body) {
        callbacks.error?.({ message: 'No response body' })
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''
      let dataLines: string[] = []
      let hasData = false

      const fire = () => {
        if (hasData && currentEvent) {
          const handler = callbacks[currentEvent]
          const raw = dataLines.join('\n')
          if (handler) {
            try {
              handler(JSON.parse(raw))
            } catch {
              handler(raw)
            }
          }
        }
        currentEvent = ''
        dataLines = []
        hasData = false
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line === '') {
            fire()
            continue
          }
          if (line.startsWith(':')) continue
          const colonIdx = line.indexOf(':')
          if (colonIdx < 0) continue
          const field = line.slice(0, colonIdx)
          let val = line.slice(colonIdx + 1)
          if (val.startsWith(' ')) val = val.slice(1)
          if (field === 'event') {
            currentEvent = val
          } else if (field === 'data') {
            hasData = true
            dataLines.push(val)
          }
        }
      }
      fire()
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        return  // user-initiated abort, no error
      }
      callbacks.error?.({ message: err?.message || String(err) })
    }
  }

  dispatch()

  return {
    abort: () => controller.abort(),
  }
}
```

- [ ] **Step 2: Verify the file type-checks**

```bash
cd frontend && npx tsc --noEmit composables/useSSE.ts
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/composables/useSSE.ts
git commit -m "feat(composables): add useSSE with AbortController support"
```

---

## Phase 7: VideoPreview expose

### Task 19: Add `defineExpose` to `VideoPreview.vue`

**Files:**
- Modify: `frontend/components/VideoPreview.vue`

- [ ] **Step 1: Find the `</script>` closing tag in `VideoPreview.vue`**

```bash
grep -n "</script>" frontend/components/VideoPreview.vue
```

- [ ] **Step 2: Add `defineExpose` block immediately before `</script>`**

```ts
// Expose play/pause/seek controls so parent (index.vue) and sibling
// components (VideoSummary) can drive the player — e.g. chapter click
// jumps currentTime and starts playback. The ref inside this component
// is `videoPlayer` (ref to the <video> element), not `video`.
defineExpose({
  play: () => videoPlayer.value?.play(),
  pause: () => videoPlayer.value?.pause(),
  setCurrentTime: (t: number) => {
    if (videoPlayer.value) videoPlayer.value.currentTime = t
  },
  getCurrentTime: () => videoPlayer.value?.currentTime ?? 0,
})
```

- [ ] **Step 3: Verify type-checks**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/VideoPreview.vue
git commit -m "feat(VideoPreview): expose play/pause/setCurrentTime via defineExpose"
```

---

## Phase 8: VideoSummary component

### Task 20: Component shell + 4-tab dark theme skeleton

**Files:**
- Create: `frontend/components/VideoSummary.vue`

- [ ] **Step 1: Create the file with the 4-tab shell**

```vue
<template>
  <div v-if="visible" class="bg-dark-card border border-dark-border rounded-2xl overflow-hidden mt-6">
    <!-- Tab nav -->
    <div class="flex border-b border-dark-border">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all',
          activeTab === tab.key ? 'text-primary-from border-b-2 border-primary-from' : 'text-text-secondary hover:text-white',
        ]"
      >
        <span>{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- Content -->
    <div class="p-6 min-h-[300px]">
      <!-- Summary tab -->
      <div v-show="activeTab === 'summary'">
        <!-- Banner slots -->
        <div v-if="languageBanner" class="mb-3 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-300 text-sm">
          {{ languageBanner }}
        </div>
        <div v-if="fallbackBanner" class="mb-3 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-300 text-sm">
          {{ fallbackBanner }}
        </div>
        <div v-if="cacheBadge" class="mb-3 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-300 text-xs">
          ✓ 来自缓存 ({{ cacheBadge }})
        </div>

        <!-- Chapter list (from JSON event) -->
        <div v-if="chapters.length > 0" class="mb-4">
          <h3 class="text-sm font-semibold text-text-secondary mb-2">章节</h3>
          <ol class="space-y-1">
            <li
              v-for="(ch, idx) in chapters"
              :key="idx"
              class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-dark-bg/50 cursor-pointer transition-colors"
              @click="onChapterClick(ch.time)"
            >
              <span class="text-primary-from font-mono text-xs min-w-[50px]">{{ formatTime(ch.time) }}</span>
              <span class="text-white text-sm">{{ ch.title }}</span>
            </li>
          </ol>
        </div>

        <!-- Summary markdown (rendered) -->
        <div v-if="summaryText" class="prose prose-invert prose-sm max-w-none" v-html="renderedSummary" />
        <div v-else-if="loading" class="flex flex-col items-center py-12 gap-3">
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-text-secondary text-sm">{{ loadingMessage }}</span>
        </div>
        <div v-else-if="errorMessage" class="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {{ errorMessage }}
        </div>
      </div>

      <!-- Subtitle tab -->
      <div v-show="activeTab === 'subtitle'">
        <div v-if="subtitleData.segments.length > 0" class="space-y-1 max-h-[500px] overflow-y-auto">
          <div
            v-for="(seg, idx) in subtitleData.segments"
            :key="idx"
            class="flex gap-3 py-1.5 px-2 rounded hover:bg-dark-bg/30"
          >
            <span class="text-primary-from font-mono text-xs pt-1 min-w-[50px]">{{ formatTime(seg.start) }}</span>
            <span class="text-white text-sm">{{ seg.text }}</span>
          </div>
        </div>
        <div v-else class="text-text-secondary text-sm text-center py-12">该视频暂无可用字幕</div>
      </div>

      <!-- Mindmap tab (placeholder) -->
      <div v-show="activeTab === 'mindmap'" class="text-center py-12 text-text-secondary text-sm">
        思维导图将在下一迭代提供
      </div>

      <!-- Q&A tab (placeholder) -->
      <div v-show="activeTab === 'qa'" class="text-center py-12 text-text-secondary text-sm">
        AI 问答将在下一迭代提供
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { marked } from 'marked'
import type { SubtitleData, Chapter as ChapterT } from '~/types'
import { useSSE } from '~/composables/useSSE'

const props = defineProps<{
  visible: boolean
  videoUrl: string
  videoTitle?: string
}>()

const emit = defineEmits<{
  'chapter-click': [timeSec: number]
  'loading-change': [loading: boolean]
}>()

// ... state and methods (added in next steps)
const tabs = [
  { key: 'summary', label: '总结摘要', icon: '📝' },
  { key: 'subtitle', label: '字幕文本', icon: '📄' },
  { key: 'mindmap', label: '思维导图', icon: '🧠' },
  { key: 'qa', label: 'AI 问答', icon: '💬' },
] as const
const activeTab = ref<typeof tabs[number]['key']>('summary')

const summaryText = ref('')
const chapters = ref<ChapterT[]>([])
const subtitleData = ref<SubtitleData>({
  has_subtitle: false,
  language: '',
  subtitle_type: 'none',
  is_target_language: true,
  segments: [],
  full_text: '',
})

const loading = ref(false)
const loadingMessage = ref('正在提取视频字幕...')
const errorMessage = ref('')
const cacheBadge = ref('')
const languageBanner = computed(() =>
  subtitleData.value.has_subtitle && !subtitleData.value.is_target_language
    ? `字幕为 ${subtitleData.value.language}，已按原文总结（未翻译）`
    : ''
)
const fallbackBanner = computed(() =>
  subtitleData.value.fallback_mode === 'metadata'
    ? '该视频无字幕，本总结基于标题生成（精度有限）'
    : ''
)

const renderedSummary = computed(() => summaryText.value ? marked.parse(summaryText.value) as string : '')

let currentAbort: (() => void) | null = null

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function onChapterClick(t: number) {
  emit('chapter-click', t)
}

function startStream() {
  // Abort any existing stream before starting a new one
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
  // Reset state
  summaryText.value = ''
  chapters.value = []
  errorMessage.value = ''
  cacheBadge.value = ''
  subtitleData.value = {
    has_subtitle: false, language: '', subtitle_type: 'none',
    is_target_language: true, segments: [], full_text: '',
  }
  loading.value = true
  loadingMessage.value = '正在提取视频字幕...'

  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase || ''

  const { abort } = useSSE(
    `${apiBase}/api/summarize`,
    { url: props.videoUrl, language: 'zh' },
    {
      cache_hit: (data: any) => {
        cacheBadge.value = data.cached_at
        summaryText.value = data.summary
        chapters.value = data.chapters || []
        subtitleData.value = { ...subtitleData.value, ...(data.subtitle_meta || {}) }
        loading.value = false
        loadingMessage.value = '已从缓存加载'
      },
      subtitle: (data: any) => {
        subtitleData.value = data
        if (data.fallback_mode === 'metadata') {
          loadingMessage.value = '正在基于元数据生成总结...'
        } else if (data.has_subtitle) {
          loadingMessage.value = 'AI 正在分析视频内容...'
        }
      },
      summary: (data: any) => {
        summaryText.value += typeof data === 'string' ? data : JSON.stringify(data)
      },
      chapters: (data: any) => {
        chapters.value = data.chapters || []
      },
      done: () => {
        loading.value = false
        emit('loading-change', false)
      },
      error: (data: any) => {
        loading.value = false
        errorMessage.value = data?.message || '总结失败'
        emit('loading-change', false)
      },
    }
  )
  currentAbort = abort
}

watch(
  () => props.visible,
  (v) => { if (v) startStream() }
)

onMounted(() => {
  if (props.visible) startStream()
})

onBeforeUnmount(() => {
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
})
</script>
```

- [ ] **Step 2: Verify type-checks**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Manual smoke test in browser**

```bash
# Terminal 1 (backend, mock mode for offline dev)
cd backend && SUMMARY_MOCK=true SUMMARY_MOCK_DELAY_MS=20 uv run python -m uvicorn main:app --reload --port 8000

# Terminal 2 (frontend)
cd frontend && npx nuxi dev
```

Then in the browser:
1. Open http://localhost:3000
2. Paste a YouTube URL (e.g. `https://www.youtube.com/watch?v=dQw4w9WgXcQ`)
3. Click 解析视频
4. Click 解析 video → click the new "AI 总结" button (we'll add the button in the next task; for now, just verify the component renders)
5. Verify: 4 tabs visible, summary streams in over ~3s, 3 mock chapters appear, "思维导图 / AI 问答" tabs show placeholders

Expected: 总结摘要 tab shows a 4-section mock summary, chapter list shows 3 entries, other tabs show placeholders. No console errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/VideoSummary.vue
git commit -m "feat(VideoSummary): 4-tab shell with dark theme and mock streaming"
```

---

## Phase 9: index.vue integration

### Task 21: Add "AI 总结" button + videoPreviewRef + onChapterClick

**Files:**
- Modify: `frontend/pages/index.vue`

- [ ] **Step 1: Add a `ref` to the `VideoPreview` component and a `showSummary` ref**

In `<script setup>`, add:

```ts
import VideoSummary from '~/components/VideoSummary.vue'
import type { VideoInfo, ProgressUpdate, SubtitleData } from '~/types'

const videoPreviewRef = ref<InstanceType<typeof import('~/components/VideoPreview.vue').default> | null>(null)
const showSummary = ref(false)
```

(Add `SubtitleData` to the existing `import type { VideoInfo, ProgressUpdate }` line; if not used, drop it.)

- [ ] **Step 2: Add `ref="videoPreviewRef"` to the `<VideoPreview>` element in the template**

Change:

```vue
<VideoPreview
  v-if="videoInfo"
  ...
/>
```

to:

```vue
<VideoPreview
  v-if="videoInfo"
  ref="videoPreviewRef"
  ...
/>
```

- [ ] **Step 3: Add an "AI 总结" toggle button and the `<VideoSummary>` mount below `<VideoPreview>`**

Add after the `<VideoPreview>` element (and after the `<ProgressTracker>`):

```vue
<div v-if="videoInfo" class="max-w-2xl mx-auto mt-3 flex justify-end">
  <button
    @click="showSummary = !showSummary"
    class="px-4 py-2 rounded-lg text-sm font-medium transition-all"
    :class="showSummary
      ? 'bg-primary-from/20 text-primary-from border border-primary-from/30'
      : 'bg-dark-card text-white border border-dark-border hover:border-primary-from/50'"
  >
    {{ showSummary ? '✕ 关闭 AI 总结' : '✨ AI 总结' }}
  </button>
</div>

<VideoSummary
  v-if="showSummary && videoInfo"
  :visible="showSummary"
  :video-url="videoInfo.url"
  :video-title="videoInfo.title"
  @chapter-click="onChapterClick"
/>
```

- [ ] **Step 4: Add `onChapterClick` handler in `<script setup>`**

```ts
function onChapterClick(t: number) {
  videoPreviewRef.value?.setCurrentTime(t)
  // play() returns a Promise; browsers reject with NotAllowedError when
  // autoplay is blocked. We deliberately swallow that error so a chapter
  // click on certain browsers doesn't surface a console error.
  videoPreviewRef.value?.play()?.catch((err) => {
    if (err?.name !== 'NotAllowedError') {
      console.warn('VideoPreview.play() failed:', err)
    }
  })
}
```

- [ ] **Step 5: Reset `showSummary` when a new video is parsed**

In the existing `handleParsed` function, add:

```ts
showSummary.value = false
```

- [ ] **Step 6: Verify type-checks**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7: Manual browser smoke test**

With backend running in mock mode (per Task 20 step 3) and frontend dev server:

1. Paste a YouTube URL → click 解析视频
2. Verify "✨ AI 总结" button appears below the preview
3. Click it → panel appears, summary streams in
4. Click a chapter in the list
5. Verify: video jumps to the chapter's time AND starts playing

Expected: clean navigation, no console errors, video plays after chapter click.

- [ ] **Step 8: Commit**

```bash
git add frontend/pages/index.vue
git commit -m "feat(index): integrate AI summary button and chapter-click handler"
```

---

## Phase 10: Manual smoke test

### Task 22: Document and run the end-to-end smoke test

**Files:**
- Modify: this plan file (append the smoke test transcript) — optional

- [ ] **Step 1: Run mock-mode smoke test**

```bash
# Terminal 1
cd backend && SUMMARY_MOCK=true SUMMARY_MOCK_DELAY_MS=20 SUMMARY_CACHE_PATH=./summary_cache.json \
  uv run python -m uvicorn main:app --reload --port 8000

# Terminal 2
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/test", "language": "zh"}'
```

Expected output (truncated):

```
event: subtitle
data: {"has_subtitle": false, ...

event: error
data: {"message": "该视频既无字幕也无元数据，..."}
```

(The mock URL has no yt-dlp metadata, so this hits the "no content" branch — confirms the error path works.)

- [ ] **Step 2: Run with a real YouTube URL (mock mode still)**

```bash
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "language": "zh"}'
```

Expected: `subtitle` event with `has_subtitle: true`, stream of `summary` tokens, `chapters` event with the 3 mock chapters, `done`. Total time ≈ 2-3 seconds.

- [ ] **Step 3: Run a second time, verify cache hit**

```bash
# Run the same curl again
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "language": "zh"}'
```

Expected: the response starts with `event: cache_hit` instead of `subtitle`. Total time < 100ms.

- [ ] **Step 4: Verify the cache file exists**

```bash
ls -la backend/summary_cache.json
cat backend/summary_cache.json | python -m json.tool | head -20
```

Expected: file exists, valid JSON, contains the cached entry.

- [ ] **Step 5: Live-mode smoke test (optional, requires API key)**

If you have an `OPENAI_API_KEY` set:

```bash
# Stop the mock-mode server
# Terminal 1
cd backend && OPENAI_API_KEY=sk-xxx SUMMARY_CACHE_PATH=./summary_cache.json \
  uv run python -m uvicorn main:app --reload --port 8000

# Terminal 2
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=<a-video-with-subtitles>", "language": "zh"}'
```

Expected: real LLM-generated summary streams in over 5-30 seconds depending on the model, real chapters appear (or empty if the LLM forgot the JSON block, which the parser handles gracefully), `done`.

- [ ] **Step 6: Commit (only if you modified files; usually not needed)**

```bash
git status
# If clean: skip
# If you changed the plan, smoke-test notes, etc.: commit them
```

- [ ] **Step 7: Final regression check — run full backend test suite**

```bash
cd backend && uv run pytest
```

Expected: all tests pass (existing + new). No regressions.

- [ ] **Step 8: Final regression check — start the app end-to-end and verify existing download flow still works**

```bash
# Terminal 1
cd backend && uv run python -m uvicorn main:app --port 8000

# Terminal 2
cd frontend && npx nuxi dev
```

In the browser, parse a YouTube URL and start a download. Verify the existing download progress UI still works (real-time progress, completion, "open folder" button).

Expected: download completes as before. AI 总结 button is now an additional option.

---

## Self-Review Checklist (per writing-plans skill)

**Spec coverage:**

- [x] §1 Background & Goal — covered in plan header
- [x] §2 Architecture — covered in header + file structure
- [x] §3.1 File structure — covered
- [x] §3.2 SubtitleExtractor — Tasks 3-7
- [x] §3.3 VideoSummarizer + config — Tasks 9-10
- [x] §3.4.1 Standard prompt — Task 10
- [x] §3.4.2 Fallback prompt — Tasks 10, 15
- [x] §3.4.3 Parse chapter JSON — Task 12
- [x] §3.5 SSE API — Tasks 13-16
- [x] §3.6 Error handling — Task 16
- [x] §3.7 Configuration — Task 1
- [x] §3.8 Cache — Task 8
- [x] §3.9 Mock — Tasks 9, 11
- [x] §4.1 File structure — covered
- [x] §4.2 Interaction flow — covered in Task 21
- [x] §4.3 VideoSummary.vue — Task 20
- [x] §4.4 useSSE.ts — Task 18
- [x] §4.5 VideoPreview expose — Task 19
- [x] §4.6 index.vue integration — Task 21
- [x] §4.7 Bilibili cookie doc — implicit in Task 6
- [x] §5 Data contracts — Tasks 2, 17
- [x] §6.1 Unit tests — Tasks 3-12, 13-16
- [x] §6.2 Manual smoke test — Task 22
- [x] §6.4 Acceptance checklist — validated in Tasks 20-22

**Placeholder scan:** None found. Every code step has the full code block; every commit has the exact command.

**Type consistency:**
- `SubtitleData.is_target_language` — used in Tasks 5, 7, 14-16
- `SubtitleData.fallback_mode` — used in Tasks 14-15
- `Chapter.time: int` — consistent (Tasks 2, 12, 13, 14)
- `MockSummarizer.DELAY_MS` — used in Tasks 9, 11
- `summary_md` cache field — consistent (Tasks 8, 13-14)
- `videoPlayer` (not `video`) in `defineExpose` — corrected in Task 19 after reading the actual file

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-07-ai-video-summary.md`.

**Total: 22 tasks across 10 phases.** Estimated effort: ~3-4 hours of focused work (assuming backend dev is comfortable with pytest + asyncio; frontend dev is comfortable with Vue 3 `<script setup>`).

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with strong isolation.

2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints for review.

Which approach?
