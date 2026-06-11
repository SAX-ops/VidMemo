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
    _semantic_segment,
    _validate_outline,
    build_summarizer,
    fix_outline_timestamps,
    generate_chat_answer,
    generate_executive_summary,
    generate_mindmap,
    parse_outline_json,
)
from services.summary_cache import SummaryCache

router = APIRouter()


class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"


class ChatRequest(BaseModel):
    url: str
    question: str


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
                "executive_summary": cached.executive_summary,
                "mindmap": cached.mindmap,
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


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Chat with Video — SSE endpoint.

    Reads cached subtitle/outline/executive_summary, retrieves relevant
    segments, and streams an LLM answer with chapter-level citations.
    """
    cache = _get_cache()
    cached = cache.get(req.url, "zh")
    if cached is None:
        async def gen():
            yield _sse("chat_error", {
                "message": "请先对该视频执行 AI 总结（生成字幕和大纲后再提问）",
                "code": "no_cache",
            })
        return StreamingResponse(gen(), media_type="text/event-stream",
                                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    # Check subtitle availability
    sub_meta = cached.subtitle_meta or {}
    segments = sub_meta.get("segments", [])
    if not sub_meta.get("has_subtitle") or not segments:
        async def gen():
            yield _sse("chat_error", {
                "message": "该视频无字幕，无法回答问题",
                "code": "no_subtitle",
            })
        return StreamingResponse(gen(), media_type="text/event-stream",
                                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    outline = cached.outline or []
    exec_summary = cached.executive_summary

    async def event_stream():
        loop = asyncio.get_event_loop()
        timeout = int(os.getenv("CHAT_TIMEOUT", "30"))

        try:
            gen = generate_chat_answer(
                req.question, outline, segments, exec_summary, "zh",
            )
            while True:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, next, gen, None),
                    timeout=timeout,
                )
                if result is None:
                    break

                event_type, payload = result
                if event_type == "token":
                    yield _sse("chat_token", payload)
                elif event_type == "done":
                    yield _sse("chat_done", {"citations": payload})
                elif event_type == "error":
                    yield _sse("chat_error", {"message": payload, "code": "llm_error"})
                    return

        except asyncio.TimeoutError:
            # Close the generator to release the thread and HTTP connection
            try:
                gen.close()
            except Exception:
                pass
            yield _sse("chat_error", {
                "message": f"回答超时（{timeout}s），请重试",
                "code": "timeout",
            })
            return
        except Exception as e:
            yield _sse("chat_error", {
                "message": f"AI 服务暂时不可用：{e}",
                "code": "llm_error",
            })
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
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

    # Step 2.5: semantic segmentation — timestamps come from subtitles, NOT LLM
    segments = subtitle.get("segments", [])
    duration = int(subtitle.get("duration") or 0)
    if not duration and segments:
        duration = int(segments[-1].get("end", 0))
    sem_chapters = _semantic_segment(segments) if segments else []

    # DEBUG: log segmentation results
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("[SEGMENT] sem_chapters count=%d, duration=%d", len(sem_chapters), duration)
    for i, ch in enumerate(sem_chapters):
        logger.warning("[SEGMENT] ch[%d] start=%.1f end=%.1f text_len=%d preview=%s",
            i, ch.get("start", 0), ch.get("end", 0), len(ch.get("text", "")),
            ch.get("text", "")[:60])

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
        _DONE = object()
        gen = summarizer.summarize_stream(
            subtitle.get("full_text", ""),
            req.language,
            has_subtitle=True,
            segments=segments,
            chapters=sem_chapters,
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

    # Step 4: parse LLM response and merge with chapter timestamps
    full_body = "".join(accumulated)
    logger.warning("[LLM_RAW] len=%d preview=%s", len(full_body), full_body[:300])

    if sem_chapters:
        # New architecture: validate segmentation, then merge with LLM titles
        sem_chapters = _validate_outline(sem_chapters, duration)
        md, llm_chapters = parse_outline_json(full_body)
        logger.warning("[LLM] llm_chapters count=%d, md_len=%d", len(llm_chapters), len(md))
        for i, ch_meta in enumerate(llm_chapters):
            logger.warning("[LLM] ch[%d] title=%s summary_items=%d",
                i, ch_meta.get("title", ""),
                len(ch_meta.get("summary", ch_meta.get("part_outline", []))))

        # Build outline: one timestamp per chapter, summary as bullet list
        outline = []
        for i, ch_meta in enumerate(llm_chapters):
            if i < len(sem_chapters):
                seg = sem_chapters[i]
                # Support both new "summary" array and old "part_outline"
                summary_items = ch_meta.get("summary", [])
                if not summary_items:
                    # Fallback: extract from part_outline (without timestamps)
                    summary_items = [p.get("content", "") for p in ch_meta.get("part_outline", []) if p.get("content")]
                if not summary_items:
                    summary_items = [ch_meta.get("title", "")]
                outline.append({
                    "title": ch_meta.get("title", f"章节 {i+1}"),
                    "timestamp": int(seg["start"]),
                    "summary": summary_items,
                    "source_segments": seg.get("segment_indices", []),
                })

        # Merge chapters with gap < 30 seconds
        _MIN_CH_GAP = 30
        merged = []
        for ch in outline:
            if merged and ch["timestamp"] - merged[-1]["timestamp"] < _MIN_CH_GAP:
                # Merge into previous chapter
                prev = merged[-1]
                prev["summary"].extend(ch["summary"])
                prev["source_segments"] = sorted(set(prev.get("source_segments", []) + ch.get("source_segments", [])))
                # Keep the earlier title
            else:
                merged.append(ch)
        outline = merged
    else:
        # Fallback: old architecture
        md, outline = parse_outline_json(full_body)
        outline = fix_outline_timestamps(outline, segments, duration)

    logger.warning("[OUTLINE] final outline count=%d", len(outline))
    for i, ch in enumerate(outline):
        src = ch.get("source_segments", [])
        first_s = src[0] if src else -1
        last_s = src[-1] if src else -1
        logger.warning("[OUTLINE] ch[%d] ts=%d title=%s segments=%d-%d count=%d",
            i, ch.get("timestamp", 0), ch.get("title", ""),
            first_s, last_s, len(src))

    import json as _json
    logger.warning("[OUTLINE_JSON] %s", _json.dumps(outline, ensure_ascii=False, indent=2))

    # If LLM skipped overview text, send empty — executive summary covers this now
    if not md and outline:
        logger.warning("[SUMMARY_MD] md is empty, skipping (executive summary covers this)")

    yield _sse("outline", {"outline": outline})
    yield _sse("summary_md", md)

    # Step 4.5: generate executive summary + mindmap (stage 2 — parallel).
    # Both depend only on the structured outline, so total Stage 2 latency
    # = max(exec, mindmap) instead of sum.  A failure in either branch must
    # NOT block the other: generate_* funcs swallow exceptions and return
    # None on failure; we just skip the matching SSE event so the frontend
    # silently hides the module.
    import logging as _logging
    _elog = _logging.getLogger(__name__)
    exec_task = loop.run_in_executor(None, generate_executive_summary, outline, req.language)
    mind_task = loop.run_in_executor(None, generate_mindmap, outline, req.language)

    exec_summary = await exec_task
    if exec_summary is not None:
        _elog.warning("[EXEC_SUMMARY] sending SSE: %s", str(exec_summary)[:200])
        yield _sse("executive_summary", exec_summary)
    else:
        _elog.warning("[EXEC_SUMMARY] skipped SSE because exec_summary is None")

    mindmap = await mind_task
    if mindmap is not None:
        _elog.warning("[MINDMAP] sending SSE: root=%r children=%d",
                      mindmap.get("root", "")[:30], len(mindmap.get("children", [])))
        yield _sse("mindmap", mindmap)
    else:
        _elog.warning("[MINDMAP] skipped SSE because mindmap is None")

    # Step 5: write to cache
    # Store the full subtitle payload (segments + full_text + fallback_mode)
    # so the frontend's 字幕文本 tab can rehydrate from cache_hit, not just
    # the metadata.
    cache.set(req.url, req.language, {
        "summary_md": md,
        "outline": outline,
        "executive_summary": exec_summary,
        "mindmap": mindmap,
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
