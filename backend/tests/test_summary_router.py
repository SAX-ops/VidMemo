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
    from services.summarizer import MockSummarizer
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

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
            from services.summarizer import MockSummarizer
            assert chapters_data["chapters"] == MockSummarizer.CHAPTERS


@pytest.mark.asyncio
async def test_no_subtitle_falls_back_to_metadata_prompt(tmp_path, monkeypatch):
    """When subtitle extraction returns empty but yt-dlp gives us title/duration, use the metadata prompt."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")
    from services.summarizer import MockSummarizer
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

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


def test_fallback_prompt_contains_title():
    from services.summarizer import _build_fallback_prompt
    p = _build_fallback_prompt("My Talk", "YouTube", 1800, "zh")
    assert "My Talk" in p
    assert "YouTube" in p
    assert "1800" in p
    assert "30 分钟" in p


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
            assert err_data.get("code") == "config_error"


@pytest.mark.asyncio
async def test_timeout_emits_error(tmp_path, monkeypatch):
    """When the LLM hangs, the SSE stream emits a timeout error after SUMMARY_TIMEOUT seconds."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setattr("services.summarizer.MockSummarizer.DELAY_MS", 0)
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


@pytest.mark.asyncio
async def test_missing_api_key_emits_error(tmp_path, monkeypatch):
    """When OPENAI_API_KEY is unset and SUMMARY_MOCK=false, the SSE stream emits a config_error event."""
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
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

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
