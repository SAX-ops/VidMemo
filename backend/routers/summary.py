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
