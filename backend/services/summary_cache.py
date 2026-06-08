"""File-based cache for AI video summaries.

Backing store: a single JSON file keyed by raw `url|language`.
A public `_make_cache_key` helper is exported (returns md5(url|language)[:16])
but the on-disk format uses the human-readable form for easier debugging.
TTL is enforced lazily on access; expired entries are deleted on read.
Writes are atomic (write to .tmp, then os.replace) so a crash mid-write
can't corrupt the cache.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union


def _make_cache_key(url: str, language: str) -> str:
    return hashlib.md5(f"{url}|{language}".encode("utf-8")).hexdigest()[:16]


@dataclass
class CachedSummary:
    summary_md: str
    outline: list
    subtitle_meta: dict
    cached_at: str  # ISO 8601

    def __eq__(self, other):
        if isinstance(other, CachedSummary):
            return (
                self.summary_md == other.summary_md
                and self.outline == other.outline
                and self.subtitle_meta == other.subtitle_meta
                and self.cached_at == other.cached_at
            )
        if isinstance(other, dict):
            return (
                self.summary_md == other.get("summary_md")
                and self.outline == other.get("outline")
                and self.subtitle_meta == other.get("subtitle_meta")
                and self.cached_at == other.get("cached_at")
            )
        return NotImplemented

    def __hash__(self):
        # outline is a list of nested dicts, so tuple(self.outline) won't hash;
        # serialize deterministically to get a stable hash.
        outline_key = json.dumps(self.outline, sort_keys=True, ensure_ascii=False)
        return hash((self.summary_md, outline_key, tuple(sorted(self.subtitle_meta.items())), self.cached_at))


class SummaryCache:
    def __init__(self, path: Path, ttl_days: int = 30):
        self.path = Path(path)
        self.ttl = timedelta(days=ttl_days)

    def get(self, url: str, language: str) -> Optional[CachedSummary]:
        key = self._storage_key(url, language)
        data = self._read()
        entry = data.get(key)
        if not entry:
            return None
        # Backward compat: old entries used `chapters` instead of `outline`.
        # Treat them as misses so they get re-saved with the new schema on next
        # request, rather than crashing the dataclass.
        if "outline" not in entry and "chapters" in entry:
            logging.warning(
                "SummaryCache.get: entry %s uses old `chapters` schema, ignoring. "
                "It will be re-saved with the new `outline` schema on next request.",
                key,
            )
            return None
        # Check expiry
        cached_at = self._parse_iso(entry["cached_at"])
        if datetime.now(timezone.utc) - cached_at > self.ttl:
            # Lazy delete
            del data[key]
            self._write(data)
            return None
        return CachedSummary(
            summary_md=entry["summary_md"],
            outline=entry["outline"],
            subtitle_meta=entry["subtitle_meta"],
            cached_at=entry["cached_at"],
        )

    def set(self, url: str, language: str, data: Union[CachedSummary, dict]) -> None:
        key = self._storage_key(url, language)
        if isinstance(data, CachedSummary):
            payload = {
                "summary_md": data.summary_md,
                "outline": data.outline,
                "subtitle_meta": data.subtitle_meta,
                "cached_at": data.cached_at,
            }
        else:
            payload = {
                "summary_md": data["summary_md"],
                "outline": data["outline"],
                "subtitle_meta": data["subtitle_meta"],
                "cached_at": data["cached_at"],
            }
        all_data = self._read()
        all_data[key] = payload
        self._write(all_data)

    @staticmethod
    def _storage_key(url: str, language: str) -> str:
        """Human-readable key for the on-disk JSON file (url|language)."""
        return f"{url}|{language}"

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logging.warning("Summary cache %s corrupt, starting fresh: %s", self.path, e)
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        """Parse an ISO 8601 timestamp, accepting the 'Z' UTC suffix on Python <3.11."""
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
