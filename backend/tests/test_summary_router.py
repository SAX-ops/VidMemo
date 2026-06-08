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
