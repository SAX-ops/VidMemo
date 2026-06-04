from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Header
from fastapi.responses import StreamingResponse, Response
from models import ParseRequest, VideoInfo
from services.ytdlp import YtdlpService
from yt_dlp import YoutubeDL
import asyncio
import hashlib
import os
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
                       'xhscdn.com', 'xiaohongshu.com']
    is_allowed = any(d in parsed.netloc for d in allowed_domains)

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Domain not allowed for proxy")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }
    if 'xiaohongshu' in parsed.netloc or 'xhscdn' in parsed.netloc:
        headers['Referer'] = 'https://www.xiaohongshu.com/'
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
                       'xhscdn.com', 'xiaohongshu.com']
    is_allowed = any(d in parsed.netloc for d in allowed_domains)

    if not is_allowed:
        raise HTTPException(status_code=403, detail="Domain not allowed for proxy")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    }

    # Forward browser's Range header to CDN
    if range:
        headers['Range'] = range

    # Set platform-specific Referer
    if 'bilibili' in parsed.netloc or 'bilivideo' in parsed.netloc or 'hdslb' in parsed.netloc:
        headers['Referer'] = 'https://www.bilibili.com/'
        headers['Origin'] = 'https://www.bilibili.com'
    elif 'tiktok' in parsed.netloc or 'tiktokcdn' in parsed.netloc:
        headers['Referer'] = 'https://www.tiktok.com/'
    elif 'xiaohongshu' in parsed.netloc or 'xhscdn' in parsed.netloc:
        headers['Referer'] = 'https://www.xiaohongshu.com/'

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code not in (200, 206):
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch stream")

            content_type = resp.headers.get('content-type', 'video/mp4')
            resp_headers = {
                'Accept-Ranges': 'bytes',
                'Content-Length': resp.headers.get('content-length', str(len(resp.content))),
            }

            # Forward Content-Range from CDN for partial responses
            if resp.status_code == 206 and 'content-range' in resp.headers:
                resp_headers['Content-Range'] = resp.headers['content-range']

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=content_type,
                headers=resp_headers,
            )
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
async def preview_stream(url: str = Query(...), quality: str = Query("720p")):
    """Download video via yt-dlp and stream it. Used for platforms like TikTok
    where CDN URLs can't be loaded directly in the browser or proxied."""
    import uuid as _uuid

    cache_key = hashlib.md5((url + quality).encode()).hexdigest()[:16]
    output_path = os.path.join(PREVIEW_DIR, f"{cache_key}.mp4")

    # Return cached if exists
    if not os.path.isfile(output_path):
        # Clean old previews (>30 min)
        try:
            now = time.time()
            for f in os.listdir(PREVIEW_DIR):
                fp = os.path.join(PREVIEW_DIR, f)
                if os.path.isfile(fp) and now - os.path.getmtime(fp) > 1800:
                    os.remove(fp)
        except OSError:
            pass

        # Douyin uses its own API (yt-dlp's extractor is broken)
        if 'douyin.com' in url:
            from services.douyin import download_douyin
            try:
                await download_douyin(url, quality, output_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Preview download failed: {str(e)}")
        else:
            # Download via yt-dlp for other platforms
            quality_lower = quality.lower()
            if 'p' in quality_lower:
                quality_num = int(quality_lower.replace('p', ''))
            else:
                quality_num = 720

            height_max = int(quality_num * 1.1)
            # Use 'best' fallback to handle both DASH (separate streams) and combined formats
            format_spec = f'bestvideo[height<={height_max}]+bestaudio/best[height<={height_max}]/best'

            def _do_download():
                opts = ytdlp_service._get_base_ydl_opts(url)
                opts.update({
                    'format': format_spec,
                    'merge_output_format': 'mp4',
                    'outtmpl': output_path,
                })
                with YoutubeDL(opts) as ydl:
                    ydl.download([url])

            try:
                await asyncio.to_thread(_do_download)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Preview download failed: {str(e)}")

    if not os.path.isfile(output_path):
        raise HTTPException(status_code=500, detail="Preview file not created")

    # FileResponse handles Range requests automatically (supports seeking)
    from starlette.responses import FileResponse
    return FileResponse(output_path, media_type="video/mp4")


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
