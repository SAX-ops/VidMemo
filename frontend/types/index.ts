export interface FormatInfo {
  quality: string
  ext: string
  size: number | null
  url: string
  audio_url?: string
}

export interface VideoInfo {
  title: string
  thumbnail: string
  duration: number | null
  platform: string
  url: string
  max_quality: string
  formats: FormatInfo[]
}

export interface ProgressUpdate {
  status: string
  progress: number
  speed: string
  eta: string
  downloaded: string
}

export interface DownloadState {
  url: string
  parsing: boolean
  downloading: boolean
  videoInfo: VideoInfo | null
  selectedQuality: string
  progress: ProgressUpdate | null
  error: string | null
}
