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
            "outline": [{"title": "x", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "c"}]}],
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
            assert "outline" not in event_names


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
    """Subtitles found → subtitle → summary (tokens) → outline → done."""
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
            assert "outline" in event_names
            assert event_names[-1] == "done"

            # Verify outline is valid JSON with the expected shape
            outline_data = json.loads(next(d for e, d in events if e == "outline"))
            assert "outline" in outline_data
            assert isinstance(outline_data["outline"], list)
            assert len(outline_data["outline"]) >= 1
            # Each chapter must have title, timestamp, summary
            for ch in outline_data["outline"]:
                assert "title" in ch
                assert "timestamp" in ch
                assert "summary" in ch


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
            assert "outline" in event_names  # mock body has outline
            outline_data = json.loads(next(d for e, d in events if e == "outline"))
            # Fallback prompt produces empty outline
            assert outline_data["outline"] == []


def test_fallback_prompt_contains_title():
    from services.summarizer import _build_fallback_prompt
    p = _build_fallback_prompt("My Talk", "YouTube", 1800, "zh")
    assert "My Talk" in p
    assert "YouTube" in p
    assert "1800" in p
    assert "30 分钟" in p


@pytest.mark.asyncio
async def test_cache_hit_includes_full_subtitle_data(tmp_path, monkeypatch):
    """Two-step: first call writes the cache (write path under test), second
    call reads it (cache_hit). The cached subtitle_meta must include segments
    + full_text, otherwise the frontend's 字幕文本 tab shows 'no subtitles'
    on the second open.
    """
    cache_path = tmp_path / "cache.json"
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setattr("services.summarizer.MockSummarizer.DELAY_MS", 0)

    from services.summarizer import SubtitleExtractor
    segments = [{"start": 0, "end": 1, "text": "你好"}, {"start": 1, "end": 2, "text": "世界"}]
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": True, "language": "zh", "subtitle_type": "manual",
                "is_target_language": True, "fallback_mode": None,
                "segments": segments, "full_text": "你好世界"}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)

    transport = ASGITransport(app=app)
    url = "https://example.com/write-then-read"
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First call: writes cache via _stream_summary Step 5
        async with ac.stream("POST", "/api/summarize", json={"url": url, "language": "zh"}) as r:
            await r.aread()
        # Second call: reads cache
        async with ac.stream("POST", "/api/summarize", json={"url": url, "language": "zh"}) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            assert events[0][0] == "cache_hit"
            cache_data = json.loads(events[0][1])
            assert cache_data["subtitle_meta"]["segments"] == segments
            assert cache_data["subtitle_meta"]["full_text"] == "你好世界"


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


# ---------------------------------------------------------------------------
# Mindmap SSE event tests
# ---------------------------------------------------------------------------


def _stub_subtitle(monkeypatch):
    """Common fake subtitle for mindmap router tests."""
    from services.summarizer import SubtitleExtractor
    def fake_extract(self, url, language="zh"):
        return {"has_subtitle": True, "language": "zh", "subtitle_type": "manual",
                "is_target_language": True, "fallback_mode": None,
                "segments": [{"start": 0, "end": 1, "text": "你好"}],
                "full_text": "你好"}
    monkeypatch.setattr(SubtitleExtractor, "extract", fake_extract)


@pytest.mark.asyncio
async def test_cache_hit_includes_mindmap(tmp_path, monkeypatch):
    """A pre-seeded cache entry with a mindmap must re-emit it via cache_hit
    so the frontend renders the mindmap tab instantly on the second open."""
    from services.summary_cache import SummaryCache
    cache_path = tmp_path / "cache.json"
    cache = SummaryCache(path=cache_path, ttl_days=30)
    mindmap = {
        "root": "缓存测试主题",
        "children": [
            {"title": "ch1", "timestamp": 0, "children": [
                {"title": "leaf1", "timestamp": 0, "children": []},
            ]},
        ],
    }
    cache.set(
        "https://example.com/cached-mindmap",
        "zh",
        {
            "summary_md": "## x",
            "outline": [{"title": "ch1", "timestamp": 0, "summary": ["leaf1"]}],
            "executive_summary": None,
            "mindmap": mindmap,
            "subtitle_meta": {"has_subtitle": True, "language": "zh", "subtitle_type": "manual"},
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/cached-mindmap", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert events[0][0] == "cache_hit"
    payload = json.loads(events[0][1])
    assert payload["mindmap"] == mindmap


@pytest.mark.asyncio
async def test_mindmap_failure_does_not_block_outline(tmp_path, monkeypatch):
    """When generate_mindmap returns None, the stream must STILL emit outline
    + executive_summary + done. Only the `mindmap` event is absent."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")
    from services.summarizer import MockSummarizer
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

    _stub_subtitle(monkeypatch)

    # Force generate_mindmap to return None (simulates LLM quality-gate failure)
    import routers.summary as router_mod
    monkeypatch.setattr(router_mod, "generate_mindmap", lambda outline, language="zh": None)
    # Force generate_executive_summary to return a valid dict so we can assert
    # the parallel branch is unaffected by the mindmap-None branch.
    fake_exec = {"core_topic": "x" * 25, "key_insights": ["a" * 15, "b" * 15, "c" * 15],
                 "author_conclusion": "结" * 30, "controversies": []}
    monkeypatch.setattr(router_mod, "generate_executive_summary",
                        lambda outline, language="zh": fake_exec)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/mindmap-skip", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]

    # Outline + executive_summary survive; mindmap event is absent
    assert "outline" in event_names
    assert "executive_summary" in event_names
    assert "mindmap" not in event_names
    assert event_names[-1] == "done"


@pytest.mark.asyncio
async def test_mindmap_emitted_when_generator_returns_dict(tmp_path, monkeypatch):
    """Happy path: a real mindmap dict from generate_mindmap reaches the wire
    as a `mindmap` SSE event."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")
    from services.summarizer import MockSummarizer
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

    _stub_subtitle(monkeypatch)

    fake_mindmap = {
        "root": "测试主题非常具体",
        "children": [
            {"title": "ch1", "timestamp": 0, "children": [
                {"title": "leaf1", "timestamp": 0, "children": []},
            ]},
        ],
    }
    import routers.summary as router_mod
    monkeypatch.setattr(router_mod, "generate_mindmap",
                        lambda outline, language="zh": fake_mindmap)
    monkeypatch.setattr(router_mod, "generate_executive_summary",
                        lambda outline, language="zh": None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/summarize",
            json={"url": "https://example.com/mindmap-ok", "language": "zh"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    mindmap_event = next((d for e, d in events if e == "mindmap"), None)
    assert mindmap_event is not None
    assert json.loads(mindmap_event) == fake_mindmap


@pytest.mark.asyncio
async def test_mindmap_persisted_to_cache_on_first_run(tmp_path, monkeypatch):
    """First run computes mindmap; second run must serve the same mindmap
    via cache_hit (proving write-through persistence)."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("SUMMARY_MOCK", "true")
    monkeypatch.setenv("SUMMARY_MOCK_DELAY_MS", "0")
    from services.summarizer import MockSummarizer
    monkeypatch.setattr(MockSummarizer, "DELAY_MS", 0)

    _stub_subtitle(monkeypatch)

    fake_mindmap = {
        "root": "持久化测试主题",
        "children": [
            {"title": "ch1", "timestamp": 0, "children": [
                {"title": "leaf", "timestamp": 0, "children": []},
            ]},
        ],
    }
    import routers.summary as router_mod
    monkeypatch.setattr(router_mod, "generate_mindmap",
                        lambda outline, language="zh": fake_mindmap)
    monkeypatch.setattr(router_mod, "generate_executive_summary",
                        lambda outline, language="zh": None)

    transport = ASGITransport(app=app)
    url = "https://example.com/mindmap-cache-roundtrip"
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First call: writes cache (and emits a live `mindmap` event)
        async with ac.stream("POST", "/api/summarize", json={"url": url, "language": "zh"}) as r:
            await r.aread()
        # Second call: must hit cache and re-emit mindmap inside cache_hit
        async with ac.stream("POST", "/api/summarize", json={"url": url, "language": "zh"}) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert events[0][0] == "cache_hit"
    payload = json.loads(events[0][1])
    assert payload["mindmap"] == fake_mindmap


# ---------------------------------------------------------------------------
# POST /api/chat tests
# ---------------------------------------------------------------------------

def _seed_chat_cache(cache_path, *, has_subtitle=True, segments=None):
    """Seed a cache entry with subtitle + outline for chat tests."""
    from services.summary_cache import SummaryCache
    cache = SummaryCache(path=cache_path, ttl_days=30)
    if segments is None:
        segments = [
            {"start": 0, "end": 3, "text": "Cursor 配合 MCP 扩展使用"},
            {"start": 3, "end": 6, "text": "通过 Vercel 一键部署上线"},
        ]
    cache.set(
        "https://example.com/chat-test",
        "zh",
        {
            "summary_md": "## x",
            "outline": [
                {"title": "AI开发流程", "timestamp": 0, "summary": ["Cursor工具"],
                 "source_segments": [0]},
                {"title": "部署资源", "timestamp": 3, "summary": ["Vercel部署"],
                 "source_segments": [1]},
            ],
            "executive_summary": {"core_topic": "开源文档翻译平台", "key_insights": ["a"],
                                  "author_conclusion": "c", "controversies": []},
            "mindmap": None,
            "subtitle_meta": {
                "has_subtitle": has_subtitle,
                "language": "zh",
                "subtitle_type": "manual",
                "segments": segments,
                "full_text": "".join(s["text"] for s in segments),
            },
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@pytest.mark.asyncio
async def test_chat_streaming_tokens_and_done(tmp_path, monkeypatch):
    """Normal flow: chat_token × N → chat_done with citations."""
    cache_path = tmp_path / "cache.json"
    _seed_chat_cache(cache_path)
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("CHAT_TIMEOUT", "30")

    import routers.summary as router_mod
    fake_tokens = ["Cursor ", "配合 ", "MCP ", "使用 [[CH_0]]。"]
    fake_citations = [{"chapter_title": "AI开发流程", "timestamp": 0}]
    call_log = [0]

    def fake_chat_gen(question, outline, segments, exec_summary, language="zh"):
        for t in fake_tokens:
            yield ("token", t)
        yield ("done", fake_citations)

    monkeypatch.setattr(router_mod, "generate_chat_answer", fake_chat_gen)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/chat-test", "question": "Cursor 怎么用？"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)
            event_names = [e[0] for e in events]

    # Must have chat_token × 4 + chat_done
    assert event_names.count("chat_token") == 4
    assert event_names[-1] == "chat_done"

    # Verify tokens contain expected text
    tokens = [d for e, d in events if e == "chat_token"]
    assert tokens[0] == "Cursor "
    assert "[[CH_0]]" in tokens[3]  # raw token still has marker

    # Verify done payload has citations
    done_data = json.loads(next(d for e, d in events if e == "chat_done"))
    assert done_data["citations"] == fake_citations


@pytest.mark.asyncio
async def test_chat_no_subtitle_returns_error(tmp_path, monkeypatch):
    """No subtitles → chat_error with code no_subtitle."""
    cache_path = tmp_path / "cache.json"
    _seed_chat_cache(cache_path, has_subtitle=False, segments=[])
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/chat-test", "question": "Cursor?"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert len(events) == 1
    assert events[0][0] == "chat_error"
    err = json.loads(events[0][1])
    assert err["code"] == "no_subtitle"


@pytest.mark.asyncio
async def test_chat_no_results_returns_error(tmp_path, monkeypatch):
    """Retrieval empty → chat_error with code no_results (no LLM call)."""
    cache_path = tmp_path / "cache.json"
    _seed_chat_cache(cache_path)
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))

    import routers.summary as router_mod
    def fake_chat_gen(question, outline, segments, exec_summary, language="zh"):
        yield ("error", "视频中没有提到这个问题")

    monkeypatch.setattr(router_mod, "generate_chat_answer", fake_chat_gen)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/chat-test", "question": "量子纠缠"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert len(events) == 1
    assert events[0][0] == "chat_error"
    err = json.loads(events[0][1])
    assert err["code"] == "llm_error"
    assert "没有提到" in err["message"]


@pytest.mark.asyncio
async def test_chat_timeout_returns_error(tmp_path, monkeypatch):
    """LLM timeout → chat_error with code timeout."""
    cache_path = tmp_path / "cache.json"
    _seed_chat_cache(cache_path)
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("CHAT_TIMEOUT", "1")

    import routers.summary as router_mod
    import time
    def slow_chat_gen(question, outline, segments, exec_summary, language="zh"):
        time.sleep(5)
        yield ("token", "x")
        yield ("done", [])

    monkeypatch.setattr(router_mod, "generate_chat_answer", slow_chat_gen)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/chat-test", "question": "test"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert len(events) == 1
    assert events[0][0] == "chat_error"
    err = json.loads(events[0][1])
    assert err["code"] == "timeout"


@pytest.mark.asyncio
async def test_chat_llm_exception_returns_error(tmp_path, monkeypatch):
    """LLM raises → chat_error with code llm_error."""
    cache_path = tmp_path / "cache.json"
    _seed_chat_cache(cache_path)
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(cache_path))

    import routers.summary as router_mod
    def boom_chat_gen(question, outline, segments, exec_summary, language="zh"):
        raise RuntimeError("simulated LLM failure")
        yield  # make it a generator

    monkeypatch.setattr(router_mod, "generate_chat_answer", boom_chat_gen)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/chat-test", "question": "test"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert len(events) == 1
    assert events[0][0] == "chat_error"
    err = json.loads(events[0][1])
    assert err["code"] == "llm_error"


@pytest.mark.asyncio
async def test_chat_no_cache_returns_error(tmp_path, monkeypatch):
    """No cache entry → chat_error with code no_cache."""
    monkeypatch.setenv("SUMMARY_CACHE_PATH", str(tmp_path / "nonexistent.json"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", "/api/chat",
            json={"url": "https://example.com/never-cached", "question": "x"},
        ) as r:
            text = (await r.aread()).decode("utf-8")
            events = _parse_sse(text)

    assert len(events) == 1
    assert events[0][0] == "chat_error"
    err = json.loads(events[0][1])
    assert err["code"] == "no_cache"
