import asyncio
import hashlib
import os
import re
import socket
import sqlite3
import tempfile
import uuid
import threading
from typing import Dict, Optional

from yt_dlp import YoutubeDL

from models import VideoInfo, FormatInfo

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub('', text)


def _detect_proxy() -> Optional[str]:
    """Auto-detect proxy: env vars first, then scan common proxy ports."""
    for key in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
        val = os.environ.get(key, '')
        if val:
            return val

    common_ports = [
        (7890, 'Clash'), (7891, 'Clash'), (7897, 'Clash'),
        (10809, 'V2Ray'), (10808, 'V2Ray'), (1080, 'SOCKS'),
        (1081, 'SOCKS'), (8080, 'HTTP'), (8118, 'Privoxy'),
    ]
    for port, name in common_ports:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.3):
                print(f'[proxy] Detected {name} on port {port}')
                return f'http://127.0.0.1:{port}'
        except (OSError, socket.timeout):
            continue

    return None


class YtdlpService:
    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._proxy = _detect_proxy()
        if self._proxy:
            print(f'[proxy] Using proxy: {self._proxy}')
        else:
            print(f'[proxy] No proxy detected')

    @staticmethod
    def _format_bytes_simple(n: int) -> str:
        """Format bytes to human-readable string (used by progress callbacks)."""
        if n < 1024:
            return f"{n} B"
        elif n < 1024 ** 2:
            return f"{n / 1024:.2f} KiB"
        elif n < 1024 ** 3:
            return f"{n / 1024 ** 2:.2f} MiB"
        else:
            return f"{n / 1024 ** 3:.2f} GiB"

    @staticmethod
    def is_douyin(url: str) -> bool:
        return 'douyin.com' in url

    # Domain → display name mapping for common platforms
    _PLATFORM_MAP = {
        'youtube.com': 'YouTube', 'youtu.be': 'YouTube',
        'douyin.com': '抖音', 'iesdouyin.com': '抖音',
        'tiktok.com': 'TikTok',
        'instagram.com': 'Instagram',
        'bilibili.com': 'B站', 'b23.tv': 'B站',
        'twitter.com': 'X', 'x.com': 'X',
        'xiaohongshu.com': '小红书', 'xhslink.com': '小红书',
        'weibo.com': '微博', 'weibo.cn': '微博',
        'kuaishou.com': '快手',
        'zhihu.com': '知乎',
        'v.qq.com': '腾讯视频',
        'iqiyi.com': '爱奇艺',
        'youku.com': '优酷',
        'vimeo.com': 'Vimeo',
        'dailymotion.com': 'Dailymotion',
        'twitch.tv': 'Twitch',
        'facebook.com': 'Facebook', 'fb.watch': 'Facebook',
        'reddit.com': 'Reddit',
        'pinterest.com': 'Pinterest',
        'snapchat.com': 'Snapchat',
        'linkedin.com': 'LinkedIn',
        'threads.net': 'Threads',
    }

    def _extract_platform(self, url: str) -> str:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        # Remove port and www prefix
        host = host.split(':')[0].removeprefix('www.')
        for domain, name in self._PLATFORM_MAP.items():
            if host == domain or host.endswith('.' + domain):
                return name
        # Fallback: use main domain name, capitalized
        parts = host.split('.')
        if len(parts) >= 2:
            return parts[-2].capitalize()
        return host.capitalize() or "Unknown"

    def _is_bilibili(self, url: str) -> bool:
        return 'bilibili.com' in url or 'b23.tv' in url

    @staticmethod
    def _is_twitter(url: str) -> bool:
        return 'twitter.com' in url or 'x.com' in url

    @staticmethod
    def _needs_proxy(url: str) -> bool:
        """Check if URL is on a GFW-blocked site that needs proxy."""
        blocked = ['youtube.com', 'youtu.be', 'google.com',
                   'twitter.com', 'x.com', 'tiktok.com',
                   'instagram.com', 'facebook.com', 'fb.watch']
        return any(d in url for d in blocked)

    def _has_firefox_bilibili_cookies(self) -> bool:
        """Quick check: does the Firefox profile have any bilibili cookies?

        Used to decide between the direct B站 API (no cookies, 720P) and
        yt-dlp (uses cookies, can get 1080P+). This avoids creating a temp
        cookie file when we don't actually need it.
        """
        try:
            profiles_dir = os.path.join(
                os.environ.get('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles'
            )
            if not os.path.isdir(profiles_dir):
                return False
            for profile in os.listdir(profiles_dir):
                cookie_path = os.path.join(profiles_dir, profile, 'cookies.sqlite')
                if not os.path.isfile(cookie_path):
                    continue
                try:
                    conn = sqlite3.connect(f'file:{cookie_path}?mode=ro', uri=True)
                    cursor = conn.cursor()
                    cursor.execute(
                        'SELECT 1 FROM moz_cookies WHERE host LIKE "%bilibili%" LIMIT 1'
                    )
                    has = cursor.fetchone() is not None
                    conn.close()
                    if has:
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _get_firefox_cookie_file(self) -> Optional[str]:
        """Read Bilibili cookies from Firefox and write to a Netscape cookie file.
        Returns the temp file path, or None if no cookies found."""
        try:
            profiles_dir = os.path.join(os.environ.get('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles')
            if not os.path.isdir(profiles_dir):
                return None

            # Find the most recently modified profile with cookies.sqlite
            best_cookie = None
            best_mtime = 0
            for profile in os.listdir(profiles_dir):
                cookie_path = os.path.join(profiles_dir, profile, 'cookies.sqlite')
                if os.path.isfile(cookie_path):
                    mtime = os.path.getmtime(cookie_path)
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_cookie = cookie_path

            if not best_cookie:
                return None

            conn = sqlite3.connect(f'file:{best_cookie}?mode=ro', uri=True)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT host, name, value, path, expiry, isSecure '
                'FROM moz_cookies WHERE host LIKE "%bilibili%"'
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return None

            # Write Netscape format cookie file
            fd, cookie_file = tempfile.mkstemp(suffix='_bilibili_cookies.txt')
            with os.fdopen(fd, 'w') as f:
                f.write('# Netscape HTTP Cookie File\n')
                for host, name, value, path, expiry, is_secure in rows:
                    secure = 'TRUE' if is_secure else 'FALSE'
                    domain_flag = 'TRUE' if host.startswith('.') else 'FALSE'
                    f.write(f'{host}\t{domain_flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n')

            print(f'[yt-dlp] Exported {len(rows)} Bilibili cookies from Firefox')
            return cookie_file

        except Exception as e:
            print(f'[yt-dlp] Failed to read Firefox cookies: {e}')
            return None

    def _get_base_ydl_opts(self, url: str, cookie_file: Optional[str] = None) -> dict:
        """Get base yt-dlp options, with Bilibili-specific settings when needed."""
        opts = {
            'no_warnings': True,
            'quiet': True,
        }
        if self._proxy and self._needs_proxy(url):
            opts['proxy'] = self._proxy
        if self._is_bilibili(url):
            opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Referer': 'https://www.bilibili.com/',
                'Origin': 'https://www.bilibili.com',
            }
            if cookie_file:
                opts['cookiefile'] = cookie_file
            else:
                opts['extractor_args'] = {'bilibili': ['visitor=true']}
        elif self._is_twitter(url):
            # X/Twitter requires login cookies — read from browser
            appdata = os.environ.get('LOCALAPPDATA', '')
            if os.path.isfile(os.path.join(appdata, 'Google', 'Chrome', 'User Data', 'Default', 'Cookies')):
                opts['cookiesfrombrowser'] = ('chrome',)
            elif os.path.isfile(os.path.join(appdata, 'Microsoft', 'Edge', 'User Data', 'Default', 'Cookies')):
                opts['cookiesfrombrowser'] = ('edge',)
            else:
                opts['cookiesfrombrowser'] = ('firefox',)
        return opts

    def _try_with_cookie_fallback(self, extract_fn, url: str):
        """Try extraction with browser cookies first, fall back to visitor mode on failure."""
        if self._is_bilibili(url):
            cookie_file = self._get_firefox_cookie_file()
            if cookie_file:
                try:
                    opts = self._get_base_ydl_opts(url, cookie_file=cookie_file)
                    result = extract_fn(opts)
                    return result
                except Exception as e:
                    print(f'[yt-dlp] Cookie extraction failed ({e}), falling back to visitor mode')
                finally:
                    try:
                        os.unlink(cookie_file)
                    except OSError:
                        pass
            # Fallback: visitor mode (max 480p, no login needed)
            opts = self._get_base_ydl_opts(url)
            return extract_fn(opts)
        else:
            opts = self._get_base_ydl_opts(url)
            return extract_fn(opts)

    def _download_instagram_thumbnail(self, url: str) -> Optional[str]:
        """Download Instagram thumbnail via yt-dlp and return local path.
        Instagram CDN blocks direct access, so we use yt-dlp's special handling."""
        thumb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'thumbnails')
        os.makedirs(thumb_dir, exist_ok=True)

        # Use URL hash as filename
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        thumb_path = os.path.join(thumb_dir, f'{url_hash}.jpg')

        # Return cached if exists
        if os.path.isfile(thumb_path):
            return thumb_path

        def _download():
            opts = {
                'no_warnings': True,
                'quiet': True,
                'writethumbnail': True,
                'skip_download': True,
                'outtmpl': os.path.join(thumb_dir, url_hash),
            }
            with YoutubeDL(opts) as ydl:
                ydl.download([url])

        try:
            _download()
            # yt-dlp may save as .jpg, .webp, etc.
            for ext in ['.jpg', '.webp', '.png', '.jpeg']:
                candidate = os.path.join(thumb_dir, url_hash + ext)
                if os.path.isfile(candidate):
                    if ext != '.jpg':
                        os.rename(candidate, thumb_path)
                    return thumb_path
        except Exception as e:
            print(f'[yt-dlp] Failed to download Instagram thumbnail: {e}')
        return None

    @staticmethod
    def _standard_height(height: int) -> int:
        """Round non-standard heights (e.g. Bilibili's 1030) to nearest standard resolution."""
        standard = [2160, 1440, 1080, 720, 480, 360, 240]
        for s in standard:
            # Within 10% of a standard resolution counts as that resolution
            if abs(height - s) / s < 0.1:
                return s
        return height

    async def parse_url(self, url: str) -> VideoInfo:
        # Douyin uses its own API (yt-dlp's extractor is broken)
        if self.is_douyin(url):
            from .douyin import parse_douyin
            return await parse_douyin(url)

        # Bilibili: choose path based on whether we have login cookies.
        # - With Firefox cookies: yt-dlp (1080P+ for logged-in users)
        # - Without cookies: direct API (fast, 720P for guests)
        if self._is_bilibili(url):
            if not self._has_firefox_bilibili_cookies():
                try:
                    from .bilibili import parse_bilibili
                    return await parse_bilibili(url)
                except Exception as e:
                    print(f'[bilibili] Direct API failed ({e}), falling back to yt-dlp')
            # else: fall through to yt-dlp path, which will use the cookies

        def _extract_info(opts):
            # Use 'bv*+ba/b' for all platforms: tries separate video+audio, falls back to best (progressive).
            # 'best[height>=144]' was used before but fails for Facebook (height is unreliable there).
            opts['format'] = 'bv*+ba/b'
            opts['download'] = False
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return info

        data = await asyncio.to_thread(self._try_with_cookie_fallback, _extract_info, url)

        # Bilibili anthologies (合集/多P) return a playlist — use first entry's data
        if data.get('_type') == 'playlist' and data.get('entries'):
            first_entry = next((e for e in data['entries'] if e), None)
            if first_entry:
                if not data.get('thumbnail'):
                    data['thumbnail'] = first_entry.get('thumbnail')
                if not data.get('formats'):
                    data['formats'] = first_entry.get('formats', [])
                if not data.get('duration'):
                    data['duration'] = first_entry.get('duration')

        # Instagram CDN blocks direct thumbnail access — download via yt-dlp
        if 'instagram.com' in url and data.get('thumbnail'):
            local_thumb = await asyncio.to_thread(self._download_instagram_thumbnail, url)
            if local_thumb:
                data['thumbnail'] = local_thumb

        formats = []
        for f in data.get('formats', []):
            if f.get('vcodec') and f.get('vcodec') != 'none' and f.get('height'):
                orig_h = f['height']
                h = self._standard_height(orig_h)
                quality = f"{h}p"
                formats.append(FormatInfo(
                    quality=quality,
                    ext=f.get('ext', 'mp4'),
                    size=f.get('filesize') or f.get('filesize_approx'),
                    url=f.get('url', ''),
                    original_height=orig_h
                ))

        seen = set()
        unique_formats = []
        for f in sorted(formats, key=lambda x: int(x.quality.replace('p', '')), reverse=True):
            if f.quality not in seen:
                seen.add(f.quality)
                unique_formats.append(f)

        unique_formats = [f for f in unique_formats if f.quality != '144p']

        # For DASH-separated streams (e.g. Instagram), attach audio URL to each video format
        # so the frontend can merge video+audio for preview using MSE
        audio_url = None
        for f in data.get('formats', []):
            if f.get('acodec') and f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                audio_url = f.get('url', '')
                break
        if audio_url:
            for fmt in unique_formats:
                fmt.audio_url = audio_url

        max_q = unique_formats[0].quality if unique_formats else 'Unknown'
        max_q_display = max_q
        if max_q.endswith('p'):
            h = int(max_q.replace('p', ''))
            if h >= 2160:
                max_q_display = '4K'
            elif h >= 1440:
                max_q_display = '2K'
            elif h >= 1080:
                max_q_display = '1080p'

        thumbnail = data.get('thumbnail', '')
        # Convert local thumbnail path to API URL
        if thumbnail and os.path.isfile(thumbnail):
            thumbnail = f'/api/thumbnail/{os.path.basename(thumbnail)}'

        return VideoInfo(
            title=data.get('title', 'Unknown'),
            thumbnail=thumbnail,
            duration=int(data['duration']) if data.get('duration') else None,
            platform=self._extract_platform(url),
            url=url,
            max_quality=max_q_display,
            formats=unique_formats[:10]
        )

    async def start_download(
        self,
        url: str,
        quality: str,
        output_dir: str
    ) -> str:
        task_id = str(uuid.uuid4())

        # Douyin uses its own download path
        if self.is_douyin(url):
            output_path = os.path.join(os.path.abspath(output_dir), f'{task_id}.mp4')
            with self._lock:
                self.tasks[task_id] = {
                    'status': 'downloading',
                    'progress': 0,
                    'speed': '',
                    'eta': '',
                    'downloaded': '',
                    'file_path': None,
                    'output_path': output_path,
                }
            asyncio.create_task(self._run_douyin_download(task_id, url, quality, output_path))
            return task_id

        # Bilibili: try direct API first, fall back to yt-dlp on failure.
        # Direct path: known .mp4 extension. yt-dlp fallback uses %(ext)s template
        # and yt-dlp itself picks the extension (mp4 due to merge_output_format).
        if self._is_bilibili(url):
            direct_path = os.path.join(os.path.abspath(output_dir), f'{task_id}.mp4')
            ytdlp_path = os.path.join(os.path.abspath(output_dir), f'{task_id}.%(ext)s')
            with self._lock:
                self.tasks[task_id] = {
                    'status': 'downloading',
                    'progress': 0,
                    'speed': '',
                    'eta': '',
                    'downloaded': '',
                    'file_path': None,
                    'output_path': direct_path,
                }
            asyncio.create_task(self._run_bilibili_download(
                task_id, url, quality, direct_path, ytdlp_path
            ))
            return task_id

        # Use absolute path to avoid working directory issues in download endpoint
        output_path = os.path.join(os.path.abspath(output_dir), f'{task_id}.%(ext)s')

        quality_lower = quality.lower()
        if 'p' in quality_lower:
            quality_num = int(quality_lower.replace('p', ''))
        else:
            quality_num = 0

        if quality == 'audio':
            format_spec = 'bestaudio/best'
        elif quality_num > 0:
            # Add 10% tolerance because _standard_height rounds non-standard heights
            # (e.g. 384p → 360p). The original height might be slightly above the standard.
            height_max = int(quality_num * 1.1)
            format_spec = f'bestvideo[height<={height_max}]+bestaudio/best[height<={height_max}]/best'
        else:
            format_spec = 'bestvideo+bestaudio/best'

        # For Bilibili, prepare cookie file for HD downloads
        cookie_file = self._get_firefox_cookie_file() if self._is_bilibili(url) else None

        with self._lock:
            self.tasks[task_id] = {
                'status': 'downloading',
                'progress': 0,
                'speed': '',
                'eta': '',
                'downloaded': '',
                'file_path': None,
                'output_path': output_path,
            }

        asyncio.create_task(self._run_download(task_id, url, format_spec, output_path, cookie_file))

        return task_id

    async def _run_download(self, task_id: str, url: str, format_spec: str, output_path: str, cookie_file: Optional[str] = None):
        """Run yt-dlp download. Progress is calculated based on downloaded bytes
        across multiple files (video + audio), normalized to 0-100%."""

        # Track cumulative progress across multiple files
        prev_downloaded = 0
        prev_filename = None  # detect file switch via filename change
        file_index = 0  # 0 = first file (video), 1 = second file (audio)
        cumulative_bytes = 0  # bytes completed from previous files
        current_file_total = 0  # total bytes of the current file
        total_bytes_all = 0  # grand total across all files

        # The expected final file path: replace %(ext)s template with mp4
        final_file_path = output_path.replace('%(ext)s', 'mp4')

        def _format_bytes(n: int) -> str:
            if n < 1024:
                return f"{n} B"
            elif n < 1024 ** 2:
                return f"{n / 1024:.2f} KiB"
            elif n < 1024 ** 3:
                return f"{n / 1024 ** 2:.2f} MiB"
            else:
                return f"{n / 1024 ** 3:.2f} GiB"

        def progress_hook(d):
            nonlocal prev_downloaded, prev_filename, file_index, cumulative_bytes, current_file_total, total_bytes_all

            with self._lock:
                if task_id not in self.tasks:
                    return

                task = self.tasks[task_id]

                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0) or 0
                    total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0) or 0
                    filename = d.get('filename', '')

                    # Detect file switch via filename change (more reliable than byte reset)
                    if prev_filename and filename and filename != prev_filename:
                        # Lock in previous file's total — assume it was 100% done
                        if current_file_total > 0:
                            cumulative_bytes += current_file_total
                        file_index += 1
                        current_file_total = 0
                        prev_downloaded = 0

                    prev_filename = filename
                    prev_downloaded = downloaded
                    if total > 0:
                        current_file_total = total

                    # Grand total = sum of all files' totals
                    # total_bytes_all is set incrementally as we learn each file's total
                    total_bytes_all = max(total_bytes_all, cumulative_bytes + current_file_total)

                    # Calculate byte-proportional progress
                    if total_bytes_all > 0:
                        overall_progress = (cumulative_bytes + downloaded) * 100 / total_bytes_all
                    else:
                        overall_progress = 0

                    task['progress'] = min(99, overall_progress)
                    task['speed'] = _strip_ansi(d.get('_speed_str', '') or '')
                    eta_raw = _strip_ansi(d.get('_eta_str', '') or '')
                    task['eta'] = '' if eta_raw.lower() == 'unknown' else eta_raw
                    task['downloaded'] = _format_bytes(cumulative_bytes + downloaded)
                    task['status'] = 'downloading'

                elif d['status'] == 'finished':
                    # yt-dlp calls 'finished' for each intermediate file (video, then audio).
                    # Don't set completed here — wait for ydl.download() to return.
                    task['progress'] = 99

        def _download_with_opts(ydl_opts):
            ydl_opts.update({
                'format': format_spec,
                'merge_output_format': 'mp4',
                'outtmpl': output_path,
                'progress_hooks': [progress_hook],
            })
            print(f'[yt-dlp] Downloading with format: {format_spec}')
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        def _download():
            if cookie_file:
                # Try with browser cookies first, fall back to visitor mode
                try:
                    ydl_opts = self._get_base_ydl_opts(url, cookie_file=cookie_file)
                    _download_with_opts(ydl_opts)
                    return
                except Exception as cookie_err:
                    print(f'[yt-dlp] Cookie download failed ({cookie_err}), falling back to visitor mode')
            ydl_opts = self._get_base_ydl_opts(url)
            _download_with_opts(ydl_opts)

        try:
            await asyncio.to_thread(_download)
            # All files downloaded and merged — now mark as completed
            with self._lock:
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    task['progress'] = 100
                    task['status'] = 'completed'
                    task['file_path'] = final_file_path
        except Exception as e:
            print(f'[yt-dlp] Download error: {e}')
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = str(e)
        finally:
            # Clean up temp cookie file
            if cookie_file:
                try:
                    os.unlink(cookie_file)
                except OSError:
                    pass

    async def _run_bilibili_download(
        self, task_id: str, url: str, quality: str, direct_path: str, ytdlp_path: str
    ):
        """Try the direct B站 API first; on any failure, fall back to yt-dlp.

        The direct API path writes a complete .mp4 (no A/V merge needed because
        `fnval=0` returns a single durl entry). yt-dlp fallback uses the
        standard video+audio merge.
        """
        try:
            from .bilibili import download_bilibili
            import time as _time

            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['status'] = 'downloading'
                    self.tasks[task_id]['progress'] = 0

            start_time = _time.monotonic()

            def _on_progress(downloaded: int, total: int):
                elapsed = _time.monotonic() - start_time
                pct = (downloaded / total * 100) if total > 0 else 0
                speed_bps = downloaded / elapsed if elapsed > 0 else 0
                remaining = (total - downloaded) / speed_bps if speed_bps > 0 else 0
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id]['progress'] = min(99, pct)
                        self.tasks[task_id]['downloaded'] = self._format_bytes_simple(downloaded)
                        self.tasks[task_id]['speed'] = f"{self._format_bytes_simple(int(speed_bps))}/s" if speed_bps > 0 else ''
                        self.tasks[task_id]['eta'] = f"{int(remaining)}s" if remaining > 0 else ''

            await download_bilibili(url, quality, direct_path, on_progress=_on_progress)

            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['progress'] = 100
                    self.tasks[task_id]['status'] = 'completed'
                    self.tasks[task_id]['file_path'] = direct_path
            return
        except Exception as e:
            print(f'[bilibili] Direct download failed ({e}), falling back to yt-dlp')

        # Fall back to yt-dlp. Reset progress and reconstruct the format spec.
        # Also try Firefox cookies so logged-in users still get 1080P.
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]['status'] = 'downloading'
                self.tasks[task_id]['progress'] = 0

        quality_lower = quality.lower()
        if quality == 'audio':
            format_spec = 'bestaudio/best'
        elif 'p' in quality_lower:
            quality_num = int(quality_lower.replace('p', ''))
            height_max = int(quality_num * 1.1)
            format_spec = (
                f'bestvideo[height<={height_max}]+bestaudio/'
                f'best[height<={height_max}]/best'
            )
        else:
            format_spec = 'bestvideo+bestaudio/best'

        cookie_file = self._get_firefox_cookie_file()
        try:
            await self._run_download(task_id, url, format_spec, ytdlp_path, cookie_file)
        finally:
            if cookie_file:
                try:
                    os.unlink(cookie_file)
                except OSError:
                    pass

    async def _run_douyin_download(self, task_id: str, url: str, quality: str, output_path: str):
        """Download Douyin video using the dedicated Douyin API."""
        try:
            from .douyin import download_douyin
            import time as _time

            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['progress'] = 0
                    self.tasks[task_id]['status'] = 'downloading'

            start_time = _time.monotonic()

            def _on_progress(downloaded: int, total: int):
                elapsed = _time.monotonic() - start_time
                pct = (downloaded / total * 100) if total > 0 else 0
                speed_bps = downloaded / elapsed if elapsed > 0 else 0
                remaining = (total - downloaded) / speed_bps if speed_bps > 0 else 0
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id]['progress'] = min(99, pct)
                        self.tasks[task_id]['downloaded'] = self._format_bytes_simple(downloaded)
                        self.tasks[task_id]['speed'] = f"{self._format_bytes_simple(int(speed_bps))}/s" if speed_bps > 0 else ''
                        self.tasks[task_id]['eta'] = f"{int(remaining)}s" if remaining > 0 else ''

            await download_douyin(url, quality, output_path, on_progress=_on_progress)

            with self._lock:
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    task['progress'] = 100
                    task['status'] = 'completed'
                    task['file_path'] = output_path
        except Exception as e:
            print(f'[Douyin] Download error: {e}')
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = str(e)

    async def stream_to_stdout(
        self, url: str, format_spec: str, cookie_file: Optional[str] = None
    ):
        """DEPRECATED: broken for B站 DASH sources. yt-dlp's `outtmpl: '-'`
        forces MPEG-TS output, and the resulting TS file registers the
        video stream as stream_type 0x06 (private data) in the PMT
        instead of 0x1B (AVC) — no demuxer can decode it. Kept for
        callers that might want to experiment, but the preview endpoint
        now uses `download_to_file` instead.
        """
        # Reuse the implementation below for backward compatibility.
        async for chunk in self._stream_to_stdout_impl(url, format_spec, cookie_file):
            yield chunk

    async def _stream_to_stdout_impl(
        self, url: str, format_spec: str, cookie_file: Optional[str] = None
    ):
        """Stream yt-dlp's merged MP4 output to an async generator.

        yt-dlp downloads video+audio to temp files, runs ffmpeg to merge
        them, and writes the merged bytes. With `outtmpl: '-'`, the
        destination is the process's stdout (fd 1). We redirect fd 1/fd 2
        to an os.pipe at the OS level — this captures both yt-dlp's
        direct writes AND the ffmpeg subprocess's stdout (subprocesses
        inherit file descriptors, not Python's sys.stdout). A reader
        thread drains the pipe and pushes chunks into the queue that
        this generator yields back. The first frame becomes available
        to the client as soon as the moov atom is in the receive buffer
        (~1-2 MB into the stream).

        The cookie_file (if any) is automatically cleaned up after the
        stream finishes, whether the download succeeded or failed.

        NOTE: produces MPEG-TS, not MP4 — see `stream_to_stdout` docstring.
        """
        import os as _os
        import queue as queue_module

        # Sentinel values pushed into the queue to signal end/error
        CHUNK_DONE = object()
        CHUNK_ERROR = object()

        inner_queue: queue_module.Queue = queue_module.Queue()
        outer_queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        loop = asyncio.get_running_loop()

        def _run_download():
            # Create a pipe and redirect fd 1 (stdout) and fd 2 (stderr) to it.
            # The ffmpeg subprocess inherits these fds, so its output goes to
            # the pipe regardless of how yt-dlp configures Python's sys.stdout.
            read_fd, write_fd = _os.pipe()
            saved_stdout_fd = _os.dup(1)
            saved_stderr_fd = _os.dup(2)
            _os.dup2(write_fd, 1)
            _os.dup2(write_fd, 2)
            _os.close(write_fd)

            def _read_pipe():
                try:
                    while True:
                        # Use a moderate chunk size; too small wastes syscalls,
                        # too large adds latency for the first frame.
                        data = _os.read(read_fd, 65536)
                        if not data:
                            break
                        inner_queue.put(data)
                except OSError:
                    pass
                finally:
                    try:
                        _os.close(read_fd)
                    except OSError:
                        pass

            pipe_thread = threading.Thread(target=_read_pipe, daemon=True)
            pipe_thread.start()

            error = None
            try:
                opts = self._get_base_ydl_opts(url, cookie_file=cookie_file)
                opts.update({
                    'format': format_spec,
                    'merge_output_format': 'mp4',
                    'outtmpl': '-',
                    'quiet': True,
                    'no_warnings': True,
                    # Move moov atom to start of file so the browser can
                    # start playing as soon as the header is buffered.
                    'postprocessor_args': {
                        'ffmpeg_o': ['-movflags', '+faststart'],
                    },
                })
                with YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                error = e
                print(f'[yt-dlp] Stream error: {e}')
            finally:
                # Close the write end of the pipe to signal EOF to the reader.
                # This is done by restoring the original fd 1/2, which makes
                # the pipe's write end have no references and close.
                try:
                    _os.dup2(saved_stdout_fd, 1)
                    _os.dup2(saved_stderr_fd, 2)
                    _os.close(saved_stdout_fd)
                    _os.close(saved_stderr_fd)
                except OSError:
                    pass

            pipe_thread.join(timeout=10)
            if error is not None:
                inner_queue.put(CHUNK_ERROR)
            else:
                inner_queue.put(CHUNK_DONE)

        thread = threading.Thread(target=_run_download, daemon=True)
        thread.start()

        async def _bridge():
            while True:
                item = await loop.run_in_executor(None, inner_queue.get)
                await outer_queue.put(item)
                if item is CHUNK_DONE or item is CHUNK_ERROR:
                    return

        bridge_task = asyncio.create_task(_bridge())

        try:
            while True:
                chunk = await outer_queue.get()
                if chunk is CHUNK_DONE:
                    break
                if chunk is CHUNK_ERROR:
                    raise RuntimeError('yt-dlp streaming failed')
                yield chunk
        finally:
            thread.join(timeout=5)
            if not bridge_task.done():
                bridge_task.cancel()
                try:
                    await bridge_task
                except (asyncio.CancelledError, Exception):
                    pass
            if cookie_file:
                try:
                    os.unlink(cookie_file)
                except OSError:
                    pass

    async def download_to_file(
        self, url: str, format_spec: str, output_path: str,
        cookie_file: Optional[str] = None,
    ) -> None:
        """Download + merge to a local file path. No progress tracking.

        Used for preview generation — we don't need WebSocket progress, we
        just need the final merged file on disk. The caller (the
        preview-stream endpoint) serves the file with FileResponse, which
        gives the browser full Range support for seeking.

        Why this instead of `stream_to_stdout`:
        yt-dlp's `outtmpl: '-' + merge_output_format: 'mp4'` forces MPEG-TS
        output, and the resulting TS file is broken for B站 DASH sources:
        the PMT registers the video stream as stream_type 0x06 (private
        data) instead of 0x1B (AVC), so no demuxer can decode it. Writing
        to a regular MP4 file produces a correct, seekable result.

        Trade-off: the client has to wait for the full download before
        playback starts (~10-30s for a 60MB B站 1080P video). The cache
        hit path remains instant.

        Cookie file (if any) is cleaned up automatically.
        """
        def _do_download(cookiefile: Optional[str]):
            opts = self._get_base_ydl_opts(url, cookie_file=cookiefile)
            opts.update({
                'format': format_spec,
                'merge_output_format': 'mp4',
                'outtmpl': output_path,
                'quiet': True,
                'no_warnings': True,
                'postprocessor_args': {
                    'ffmpeg_o': ['-movflags', '+faststart'],
                },
            })
            with YoutubeDL(opts) as ydl:
                ydl.download([url])

        try:
            if cookie_file:
                # Try with cookies first; fall back to visitor mode on
                # any failure (mirrors _run_download's behavior).
                try:
                    await asyncio.to_thread(_do_download, cookie_file)
                    return
                except Exception as cookie_err:
                    print(f'[yt-dlp] Cookie download failed ({cookie_err}), falling back to visitor mode')
            await asyncio.to_thread(_do_download, None)
        finally:
            if cookie_file:
                try:
                    os.unlink(cookie_file)
                except OSError:
                    pass
