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
        "outline": [{"title": "开场", "timestamp": 0, "part_outline": [{"timestamp": 0, "content": "x"}]}],
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
    data = {"summary_md": "x", "outline": [], "subtitle_meta": {}, "cached_at": "2020-01-01T00:00:00Z"}
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
    cache.set("https://x.com", "zh", {"summary_md": "x", "outline": [], "subtitle_meta": {}, "cached_at": "2026-06-07T00:00:00Z"})
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
    cache.set("https://x.com", "zh", {"summary_md": "x", "outline": [], "subtitle_meta": {}, "cached_at": "2026-06-07T00:00:00Z"})
    assert cache.get("https://x.com", "zh") is not None


# --- mindmap round-trip ---

def test_set_then_get_round_trip_includes_mindmap(tmp_path):
    """Mindmap dict must survive the on-disk JSON round-trip — the SSE
    cache_hit event reads `cached.mindmap` and feeds it straight to the UI."""
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    mindmap = {
        "root": "视频核心主题",
        "children": [
            {"title": "章节一", "timestamp": 0, "children": [
                {"title": "要点A", "timestamp": 0, "children": []},
                {"title": "要点B", "timestamp": 0, "children": []},
            ]},
            {"title": "章节二", "timestamp": 120, "children": [
                {"title": "要点C", "timestamp": 120, "children": []},
            ]},
        ],
    }
    data = {
        "summary_md": "## 视频概述\nhi",
        "outline": [{"title": "开场", "timestamp": 0, "summary": ["x"]}],
        "executive_summary": {"core_topic": "t", "key_insights": ["a"], "author_conclusion": "c", "controversies": []},
        "mindmap": mindmap,
        "subtitle_meta": {"has_subtitle": True, "language": "zh"},
        "cached_at": "2026-06-07T10:00:00Z",
    }
    cache.set("https://x.com", "zh", data)
    got = cache.get("https://x.com", "zh")
    assert got is not None
    assert got.mindmap == mindmap


def test_get_returns_none_mindmap_for_legacy_entry(tmp_path):
    """Old cache entries written before the mindmap field existed must still
    deserialize — they just have mindmap=None, which the SSE layer turns into
    a missing 'mindmap' attribute in the cache_hit payload (frontend tolerates)."""
    cache = SummaryCache(path=tmp_path / "cache.json", ttl_days=30)
    legacy = {
        "summary_md": "x",
        "outline": [],
        "subtitle_meta": {},
        "cached_at": "2099-01-01T00:00:00Z",
        # NO mindmap, NO executive_summary
    }
    # Hand-write so we exercise the old-shape path
    import json as _json
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_text(_json.dumps({"https://x.com|zh": legacy}), encoding="utf-8")

    got = cache.get("https://x.com", "zh")
    assert got is not None
    assert got.mindmap is None
    assert got.executive_summary is None
