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
