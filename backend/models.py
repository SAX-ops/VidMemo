# backend/models.py
from pydantic import BaseModel
from typing import List, Optional


class FormatInfo(BaseModel):
    quality: str
    ext: str
    size: Optional[int] = None
    url: str  # Direct playback URL for preview
    audio_url: Optional[str] = None  # Separate audio stream URL (for DASH formats)
    original_height: Optional[int] = None  # Original height before standardization (for yt-dlp format selection)


class VideoInfo(BaseModel):
    title: str
    thumbnail: str
    duration: Optional[int] = None
    platform: str  # "YouTube", "TikTok", etc.
    url: str  # Original video URL
    max_quality: str  # Highest available quality, e.g. "4K", "1440p", "1080p"
    formats: List[FormatInfo]


class ParseRequest(BaseModel):
    url: str
    quality: Optional[str] = "720p"


class DownloadTask(BaseModel):
    id: str
    url: str
    status: str = "pending"
    progress: float = 0.0
    filename: Optional[str] = None


class ProgressUpdate(BaseModel):
    percent: float
    speed: str
    eta: str
    downloaded: str


class SubtitleSegment(BaseModel):
    start: float
    end: float
    text: str


class SubtitleData(BaseModel):
    has_subtitle: bool
    language: str = ""
    subtitle_type: str = "none"  # "manual" | "auto" | "none"
    is_target_language: bool = True
    fallback_mode: Optional[str] = None  # "metadata" when has_subtitle=False
    segments: List[SubtitleSegment] = []
    full_text: str = ""


class Chapter(BaseModel):
    time: int   # seconds
    title: str


class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"
