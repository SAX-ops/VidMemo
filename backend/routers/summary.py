"""AI 视频总结路由 — SSE 流式端点。"""

import asyncio
import json
import os
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import summarizer as summarizer_service
from services.summarizer import (
    SubtitleExtractor,
    build_summarizer,
    parse_outline_json,
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
    cache = _get_cache()

    # Cache lookup
    cached = cache.get(req.url, req.language)
    if cached is not None:
        async def gen():
            yield _sse("cache_hit", {
                "summary": cached.summary_md,
                "outline": cached.outline,
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
        # Try to get metadata for fallback
        video_meta: dict = {}
        try:
            info = await loop.run_in_executor(None, summarizer_service._get_video_info, req.url)
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

        # Continue with fallback prompt (chapters always empty for fallback)
        try:
            summarizer = build_summarizer()
        except ValueError as e:
            yield _sse("error", {"message": str(e), "code": "config_error"})
            return
        timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))
        try:
            gen = _stream_fallback(summarizer, video_meta, req.language)
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                    yield chunk
                except StopAsyncIteration:
                    break
        except asyncio.TimeoutError:
            yield _sse("error", {"message": f"AI 总结超时（{timeout}s）", "code": "timeout"})
            return
        except Exception as e:
            yield _sse("error", {"message": f"AI 总结服务暂时不可用：{e}", "code": "llm_error"})
            return

        yield _sse("outline", {"outline": []})
        yield _sse("done", "[DONE]")
        return

    # Step 2: send subtitle event
    yield _sse("subtitle", subtitle)

    # Step 3: stream summary tokens + collect
    try:
        summarizer = build_summarizer()
    except ValueError as e:
        yield _sse("error", {"message": str(e), "code": "config_error"})
        return
    accumulated: list[str] = []
    timeout = int(os.getenv("SUMMARY_TIMEOUT", "90"))
    full_text_len = len(subtitle.get("full_text") or "")
    effective_timeout = max(timeout, full_text_len // 200)

    try:
        # Each next() runs in a worker thread so a hung LLM doesn't block the
        # event loop — this is what lets asyncio.wait_for actually fire on a
        # timeout (sync iteration inside an async coroutine would block).
        # Use a sentinel return so StopIteration isn't raised into a Future
        # (PEP 479: StopIteration in a coroutine is a RuntimeError).
        _DONE = object()
        gen = summarizer.summarize_stream(
            subtitle.get("full_text", ""),
            req.language,
            has_subtitle=True,
        )
        while True:
            tok = await asyncio.wait_for(
                loop.run_in_executor(None, next, gen, _DONE),
                timeout=effective_timeout,
            )
            if tok is _DONE:
                break
            accumulated.append(tok)
            yield _sse("summary", tok)
    except asyncio.TimeoutError:
        yield _sse("error", {"message": f"AI 总结超时（{effective_timeout}s），请重试或换一个较短的字幕", "code": "timeout"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"AI 总结服务暂时不可用：{e}", "code": "llm_error"})
        return

    # Step 4: parse outline from accumulated body
    full_body = "".join(accumulated)
    md, outline = parse_outline_json(full_body)
    yield _sse("outline", {"outline": outline})

    # Step 5: write to cache
    # Store the full subtitle payload (segments + full_text + fallback_mode)
    # so the frontend's 字幕文本 tab can rehydrate from cache_hit, not just
    # the metadata.
    cache.set(req.url, req.language, {
        "summary_md": md,
        "outline": outline,
        "subtitle_meta": {
            k: subtitle[k] for k in (
                "has_subtitle", "language", "subtitle_type", "is_target_language",
                "fallback_mode", "segments", "full_text",
            )
        },
        "cached_at": datetime.now(timezone.utc).isoformat(),
    })

    yield _sse("done", "[DONE]")


async def _stream_fallback(summarizer, video_meta: dict, language: str):
    """Async wrapper around summarizer.summarize_stream(..., has_subtitle=False)."""
    gen = summarizer.summarize_stream(
        video_meta.get("title", ""),  # subtitle_text param (unused for fallback)
        language,
        has_subtitle=False,
        video_meta=video_meta,
    )
    for tok in gen:
        yield _sse("summary", tok)
