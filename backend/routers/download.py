from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Header
from fastapi.responses import StreamingResponse, Response
from models import ParseRequest, VideoInfo
from services.ytdlp import YtdlpService
from yt_dlp import YoutubeDL
import asyncio
import hashlib
import os
import re
import subprocess
import httpx
import time
from typing import Optional
from urllib.parse import urlparse, quote

router = APIRouter()
ytdlp_service = YtdlpService()

# Use absolute path for downloads directory
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PREVIEW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "previews"))
os.makedirs(PREVIEW_DIR, exist_ok=True)


def _detect_video_format(first_bytes: bytes) -> str:
    """Sniff a video container's MIME type from its leading bytes.

    yt-dlp's `outtmpl: '-'` forces MPEG-TS output (per its source: when
    ext == 'mp4' and tmpfilename == '-', it uses `-f mpegts`). If we serve
    those bytes with Content-Type: video/mp4, the browser tries to parse
    them as fragmented MP4 (looking for moov/ftyp boxes) and fails with a
    silent decode error → `<video>` fires `error` → user sees
    "视频预览加载失败". Detect the actual format and return the correct
    MIME type so the browser uses the right demuxer.
    """
    if not first_bytes:
        return 'application/octet-stream'
    # MPEG-TS: sync byte 0x47 is the first byte, then every 188 bytes.
    if first_bytes[0] == 0x47:
        return 'video/mp2t'
    # MP4 / MOV: ISO base media file — first box is "ftyp".
    if len(first_bytes) >= 8 and first_bytes[4:8] == b'ftyp':
        return 'video/mp4'
    # Matroska / WebM: EBML header.
    if first_bytes[:4] == b'\x1a\x45\xdf\xa3':
        return 'video/webm'
    # FLV
    if first_bytes[:3] == b'FLV':
        return 'video/x-flv'
    # Unknown — let the browser sniff rather than mislabel.
    return 'application/octet-stream'


@router.post("/parse", response_model=VideoInfo)
async def parse_video(request: ParseRequest):
    try:
        result = await ytdlp_service.parse_url(request.url)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download/{task_id}")
async def download_file(task_id: str):
    file_path = None

    # First try: check if task is in memory (same session)
    print(f"[download] Looking for task_id={task_id}")
    print(f"[download] Available tasks: {list(ytdlp_service.tasks.keys())}")
    if task_id in ytdlp_service.tasks:
        task = ytdlp_service.tasks[task_id]
        if task["status"] == "completed":
            file_path = task.get("file_path")
            # Resolve relative paths to absolute
            if file_path and not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)
            if file_path and os.path.exists(file_path):
                filename = os.path.basename(file_path)
                async def file_iterator():
                    try:
                        with open(file_path, "rb") as f:
                            while chunk := f.read(8192):
                                yield chunk
                    finally:
                        # Clean up temporary file after streaming
                        try:
                            os.remove(file_path)
                            print(f"[download] Cleaned up: {file_path}")
                        except OSError:
                            pass
                return StreamingResponse(
                    file_iterator(),
                    media_type="video/mp4",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    }
                )

    # Second try: look for file in downloads folder (file persists across restarts)
    candidate = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    if os.path.exists(candidate):
        file_path = candidate
        filename = f"{task_id}.mp4"
        async def file_iterator():
            try:
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Clean up temporary file after streaming
                try:
                    os.remove(file_path)
                    print(f"[download] Cleaned up: {file_path}")
                except OSError:
                    pass
        return StreamingResponse(
            file_iterator(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    raise HTTPException(status_code=404, detail="File not found")


@router.post("/start-download")
async def start_download(request: ParseRequest):
    try:
        task_id = await ytdlp_service.start_download(
            url=request.url,
            quality=request.quality,
            output_dir=DOWNLOAD_DIR
        )
        return {"task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.websocket("/ws/progress/{task_id}")
async def progress_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()

    if task_id not in ytdlp_service.tasks:
        await websocket.close(code=4004, reason="Task not found")
        return

    try:
        while True:
            task = ytdlp_service.tasks.get(task_id)
            if not task:
                break

            await websocket.send_json({
                "status": task["status"],
                "progress": task.get("progress", 0),
                "speed": task.get("speed", ""),
                "eta": task.get("eta", ""),
                "downloaded": task.get("downloaded", "")
            })

            if task["status"] in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass


@router.post("/open-folder")
async def open_folder(folder_path: Optional[str] = None):
    """Open the specified folder in file explorer (Windows)"""

    try:
        if folder_path and os.path.exists(folder_path):
            target = folder_path
        else:
            # Open default downloads folder for current user
            target = os.path.join(os.path.expanduser("~"), "Downloads")

        # Windows: use explorer to open folder
        subprocess.Popen(f'explorer "{target}"')
        return {"success": True, "path": target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thumbnail/{filename}")
async def serve_thumbnail(filename: str):
    """Serve locally cached thumbnails (e.g. Instagram)."""
    thumb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'thumbnails')
    file_path = os.path.join(thumb_dir, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    with open(file_path, 'rb') as f:
        data = f.read()
    return Response(content=data, media_type='image/jpeg')


@router.get("/proxy/image")
async def proxy_image(url: str = Query(...)):
    """Proxy image requests to bypass Referer hotlink protection"""
    parsed = urlparse(url)
    allowed_domains = ['bilibili.com', 'hdslb.com', 'bfmtv.com', 'fbcdn.net', 'cdninstagram.com',
                       'xhscdn.com', 'xiaohongshu.com',
                       'ytimg.com', 'ggpht.com', 'googlevideo.com']
    is_allowed = any(d in parsed.netloc for d in allowed_domains)

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Domain not allowed for proxy")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }
    if 'xiaohongshu' in parsed.netloc or 'xhscdn' in parsed.netloc:
        headers['Referer'] = 'https://www.xiaohongshu.com/'
    elif 'ytimg' in parsed.netloc or 'ggpht' in parsed.netloc:
        headers['Referer'] = 'https://www.youtube.com/'
    else:
        headers['Referer'] = 'https://www.bilibili.com/'

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch image")

            content_type = resp.headers.get('content-type', 'image/jpeg')
            return Response(content=resp.content, media_type=content_type)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Image proxy error: {str(e)}")


@router.get("/proxy/stream")
async def proxy_stream(url: str = Query(...), range: Optional[str] = Header(None)):
    """Proxy video/audio stream requests with proper Referer headers.
    Supports Range requests for seeking."""
    parsed = urlparse(url)
    allowed_domains = ['bilibili.com', 'bilivideo.com', 'hdslb.com',
                       'tiktok.com', 'tiktokcdn.com', 'tiktokcdn-us.com',
                       'bfmtv.com', 'fbcdn.net', 'cdninstagram.com',
                       'xhscdn.com', 'xiaohongshu.com',
                       'googlevideo.com']
    is_allowed = any(d in parsed.netloc for d in allowed_domains)

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Domain not allowed for proxy")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    }

    # Cap browser's Range to MAX_RANGE_SIZE. YouTube's CDN rejects open-ended
    # `Range: bytes=0-` requests with 0 bytes back (verified: TTFB=0.7s, then
    # hang until timeout). HTML5 <video> always sends `bytes=0-` on the first
    # GET, so without this cap the browser deadlocks: never receives init
    # segment → never fires loadeddata → "loading" forever.
    # After we respond with `Content-Range: bytes 0-N/total`, the browser
    # sends follow-up Range requests with explicit end (`bytes=5242880-...`),
    # which the CDN accepts normally — so the cap only applies to the first
    # large request.
    MAX_RANGE_SIZE = 2 * 1024 * 1024  # 2MB — YouTube CDN works reliably up to 2MB per Range request
    if range:
        m = re.match(r'bytes=(\d+)-(\d*)', range)
        if m:
            start = int(m.group(1))
            end_str = m.group(2)
            if end_str == '' or int(end_str) - start + 1 > MAX_RANGE_SIZE:
                end = start + MAX_RANGE_SIZE - 1
                range = f'bytes={start}-{end}'
        headers['Range'] = range
    else:
        # No Range from browser — issue a capped one. Otherwise YouTube
        # serves the full file and proxy would buffer gigabytes.
        range = f'bytes=0-{MAX_RANGE_SIZE - 1}'
        headers['Range'] = range

    # Set platform-specific Referer
    if 'bilibili' in parsed.netloc or 'bilivideo' in parsed.netloc or 'hdslb' in parsed.netloc:
        headers['Referer'] = 'https://www.bilibili.com/'
        headers['Origin'] = 'https://www.bilibili.com'
    elif 'tiktok' in parsed.netloc or 'tiktokcdn' in parsed.netloc:
        headers['Referer'] = 'https://www.tiktok.com/'
    elif 'xiaohongshu' in parsed.netloc or 'xhscdn' in parsed.netloc:
        headers['Referer'] = 'https://www.xiaohongshu.com/'
    elif 'googlevideo' in parsed.netloc:
        headers['Referer'] = 'https://www.youtube.com/'
        headers['Origin'] = 'https://www.youtube.com'

    try:
        # Stream from CDN to browser chunk-by-chunk. The previous version used
        # `resp = await client.get(...)` + `resp.content` which buffers the full
        # body into memory before responding — for a 700MB YouTube stream through
        # a 100KB/s Clash proxy, that means the browser sees zero bytes for 2+
        # hours. `client.send(..., stream=True)` + `aiter_bytes` starts yielding
        # chunks to the browser as the CDN delivers them.
        # Stream from CDN to browser chunk-by-chunk. We use aiohttp instead
        # of httpx for the body read loop — httpx's anyio-based read raises
        # `httpcore.ReadError` mid-body when the upstream CDN goes through
        # Clash on Windows, leaving the browser with 206 status + 0-byte
        # body. aiohttp uses a different async network backend that handles
        # the proxy connection more gracefully.
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=60, sock_read=30)
        # trust_env=True tells aiohttp to read HTTP_PROXY/HTTPS_PROXY/NO_PROXY
        # from os.environ — same env vars that httpx picks up automatically.
        # Without it aiohttp tries to connect directly to googlevideo.com
        # (bypassing Clash) and times out on the SSL handshake.
        #
        # IMPORTANT: do NOT use `async with aiohttp.ClientSession(...) as session`
        # or `async with session.get(...) as resp`. Those context managers call
        # `__aexit__` synchronously when the `return StreamingResponse(...)` line
        # is reached, which closes `resp` BEFORE the StreamingResponse has
        # started iterating over it. The browser then receives a 206 status with
        # an empty body. The fix is a manual lifecycle: keep the session and the
        # response object alive for as long as the `relay` generator runs, and
        # close them in the generator's `finally` block.
        session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
        try:
            resp = await session.get(url, headers=headers, allow_redirects=True)
            if resp.status not in (200, 206):
                resp.close()
                await session.close()
                raise HTTPException(status_code=resp.status, detail="Failed to fetch stream")

            init_headers = {'Accept-Ranges': 'bytes'}
            cr = resp.headers.get('Content-Range')
            if cr:
                init_headers['Content-Range'] = cr

            async def relay():
                try:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        yield chunk
                finally:
                    resp.close()
                    await session.close()

            return StreamingResponse(
                relay(),
                status_code=resp.status,
                media_type=resp.headers.get('content-type', 'video/mp4'),
                headers=init_headers,
            )
        except Exception:
            # On any error before returning the StreamingResponse, clean up.
            if not session.closed:
                await session.close()
            raise
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Stream proxy error: {str(e)}")


@router.post("/preview-merge")
async def preview_merge(request: dict):
    """Merge video + audio streams into a single MP4 for preview playback.
    Used for platforms with DASH-separated streams (e.g. Instagram)."""
    video_url = request.get("video_url")
    audio_url = request.get("audio_url")
    if not video_url or not audio_url:
        raise HTTPException(status_code=400, detail="video_url and audio_url required")

    # Cache key from URL hashes
    cache_key = hashlib.md5((video_url + audio_url).encode()).hexdigest()[:16]
    output_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")

    # Return cached if exists
    if os.path.isfile(output_path):
        return {"filename": f"{cache_key}.mp4"}

    # Clean old previews (>30 min)
    try:
        now = time.time()
        for f in os.listdir(PREVIEW_DIR):
            fp = os.path.join(PREVIEW_DIR, f)
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > 1800:
                os.remove(fp)
    except OSError:
        pass

    # Download both streams
    video_tmp = os.path.join(PREVIEW_DIR, f"{cache_key}_v.tmp")
    audio_tmp = os.path.join(PREVIEW_DIR, f"{cache_key}_a.tmp")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
            'Referer': 'https://www.instagram.com/',
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            v_resp, a_resp = await asyncio.gather(
                client.get(video_url, headers=headers),
                client.get(audio_url, headers=headers)
            )
            if v_resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Video fetch failed: {v_resp.status_code}")
            if a_resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Audio fetch failed: {a_resp.status_code}")

            with open(video_tmp, 'wb') as f:
                f.write(v_resp.content)
            with open(audio_tmp, 'wb') as f:
                f.write(a_resp.content)

        # Merge with ffmpeg (stream copy, no re-encoding)
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', video_tmp, '-i', audio_tmp,
             '-c', 'copy', '-movflags', '+faststart', output_path],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="ffmpeg merge failed")

        return {"filename": f"{cache_key}.mp4"}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="ffmpeg merge timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Stream fetch error: {str(e)}")
    finally:
        for tmp in [video_tmp, audio_tmp]:
            try:
                os.remove(tmp)
            except OSError:
                pass


@router.get("/preview-stream")
async def preview_stream(url: str = Query(...), quality: str = Query("720p"), cache: int = Query(1)):
    """Generate a merged preview MP4 via yt-dlp and serve it.

    For platforms where CDN URLs can't be loaded directly in the browser
    (TikTok, etc.) or where direct API gives DASH streams (B站 via yt-dlp
    WBI endpoint with cookies), this endpoint:
    - Caches the merged MP4 in PREVIEW_DIR for 30 minutes
    - First request: downloads + merges to a temp file, then renames it
      into the cache, then returns FileResponse. The client has to wait
      for the full download (~10-30s for a 60MB B站 1080P video) before
      playback starts.
    - Repeat requests: returns the cached file with FileResponse (full
      Range support, instant seek).

    Pass `?cache=0` to force re-download even on cache hit.

    Why disk-based, not stream-to-stdout:
    yt-dlp's `outtmpl: '-' + merge_output_format: 'mp4'` forces MPEG-TS
    output, and the resulting TS file is broken for B站 DASH sources:
    the PMT registers the video stream as stream_type 0x06 (private data)
    instead of 0x1B (AVC), so no demuxer can decode it. Writing to a
    proper MP4 file produces a correct, seekable result.
    """
    from starlette.responses import FileResponse
    import glob

    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]
    # Use %(ext)s in the temp template so yt-dlp's `merge_output_format:
    # 'mp4'` resolves to a real .mp4 filename. yt-dlp always treats
    # outtmpl as a template and appends the extension if it's not there.
    output_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")
    output_tmp = os.path.join(PREVIEW_DIR, f"{cache_key}.tmp.%(ext)s")

    # Cache hit: serve the file (FileResponse supports Range requests).
    # Sniff the format from the file's first bytes — defensive in case a
    # future code path produces a non-MP4 container.
    if cache and os.path.isfile(output_path):
        with open(output_path, 'rb') as f:
            head = f.read(4096)
        media_type = _detect_video_format(head)
        return FileResponse(output_path, media_type=media_type)

    # Clean old previews (>30 min) on cache miss
    try:
        now = time.time()
        for f in os.listdir(PREVIEW_DIR):
            fp = os.path.join(PREVIEW_DIR, f)
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > 1800:
                os.remove(fp)
    except OSError:
        pass

    # Douyin uses its own API (yt-dlp's extractor is broken since 2024-04)
    if 'douyin.com' in url:
        from services.douyin import download_douyin
        try:
            await download_douyin(url, quality, output_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Preview download failed: {str(e)}")
        if not os.path.isfile(output_path):
            raise HTTPException(status_code=500, detail="Preview file not created")
        with open(output_path, 'rb') as f:
            head = f.read(4096)
        return FileResponse(output_path, media_type=_detect_video_format(head))

    # For Bilibili, read Firefox cookies so logged-in users get 1080P in
    # the merged preview file. The direct API can't reach 1080P without
    # B站's WBI signing, but yt-dlp handles that internally.
    cookie_file = (
        ytdlp_service._get_firefox_cookie_file()
        if ytdlp_service._is_bilibili(url) else None
    )

    # Build format spec from quality
    quality_lower = quality.lower()
    if 'p' in quality_lower:
        quality_num = int(quality_lower.replace('p', ''))
    else:
        quality_num = 720
    height_max = int(quality_num * 1.1)
    # 'best' fallback handles both DASH (separate streams) and combined formats
    format_spec = f'bestvideo[height<={height_max}]+bestaudio/best[height<={height_max}]/best'

    # Pre-flight: validate URL before committing to a full download.
    # yt-dlp's extract_info runs in ~1s for valid URLs and returns
    # immediately with a clear error for 404/region-lock/private content.
    def _preflight():
        opts = ytdlp_service._get_base_ydl_opts(url, cookie_file=cookie_file)
        opts['quiet'] = True
        opts['no_warnings'] = True
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)

    try:
        await asyncio.to_thread(_preflight)
    except Exception as e:
        if cookie_file:
            try:
                os.unlink(cookie_file)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Preview pre-flight failed: {str(e)}")

    # Download + merge to a temp file, then atomically rename into the
    # cache. yt-dlp's outtmpl replaces `%(ext)s` with the merge format's
    # extension (`.mp4`), so the produced file is `{cache_key}.tmp.mp4`.
    # We glob for the actual file rather than guessing the extension.
    try:
        await ytdlp_service.download_to_file(
            url=url,
            format_spec=format_spec,
            output_path=output_tmp,
            cookie_file=cookie_file,
        )
    except Exception as e:
        # Clean up any partial output yt-dlp may have left behind
        for partial in glob.glob(
            os.path.join(PREVIEW_DIR, f"{cache_key}.tmp.*")
        ):
            try:
                os.unlink(partial)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Preview download failed: {str(e)}")

    candidates = glob.glob(os.path.join(PREVIEW_DIR, f"{cache_key}.tmp.*"))
    if not candidates:
        raise HTTPException(status_code=500, detail="Preview file not created")
    produced_file = candidates[0]

    try:
        os.rename(produced_file, output_path)
    except OSError:
        # Cross-device or permission error — fall back to copy+remove
        import shutil
        shutil.move(produced_file, output_path)

    with open(output_path, 'rb') as f:
        head = f.read(4096)
    media_type = _detect_video_format(head)
    return FileResponse(output_path, media_type=media_type)


@router.get("/preview-file/{filename}")
async def serve_preview_file(filename: str):
    """Serve a merged preview file."""
    file_path = os.path.join(PREVIEW_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Preview file not found")

    def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(file_iterator(), media_type="video/mp4")
