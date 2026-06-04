# VidSumAI

多平台视频下载工具，支持 YouTube、Bilibili、Instagram、TikTok、抖音、小红书、微博、X、Facebook 等 9+ 平台。

## 功能特性

- **多平台支持** - YouTube、Bilibili、Instagram、TikTok、抖音、小红书、微博、X、Facebook
- **高清下载** - 支持 360p ~ 4K 分辨率选择
- **B站高清解锁** - 自动读取 Firefox Cookie，支持 1080P+ 高清下载
- **B站合集支持** - 多P（合集）视频自动取首个 P
- **实时进度** - WebSocket 实时推送下载进度、速度、剩余时间
- **封面预览** - 解析后显示视频封面、标题、时长等信息
- **DASH 音视频同步** - 预览时自动处理分离的视频流和音频流
- **抖音自实现** - yt-dlp 提取器失效后自实现 API 绕过反爬
- **无水印** - 自动获取无水印版本（TikTok、Instagram）
- **GFW 代理自动检测** - 自动识别本地代理，仅对 GFW 站点启用

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Nuxt.js 3 + TailwindCSS |
| 后端 | Python FastAPI |
| 下载引擎 | yt-dlp (Python API) |
| 通信 | REST API + WebSocket |

## 快速开始

### 环境要求

- Node.js 18+
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python 包管理)
- ffmpeg (视频合并)

### 安装

```bash
# 克隆仓库
git clone https://github.com/SAX-ops/VidSumAI.git
cd VidSumAI

# 安装前端依赖
cd frontend
npm install

# 安装后端依赖
cd ../backend
uv sync
```

### 启动

```bash
# 启动后端 (端口 8000)
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# 启动前端 (端口 3000)
cd frontend
npm run dev
```

访问 http://localhost:3000

## 项目结构

```
VidSumAI/
├── frontend/                # Nuxt.js 前端
│   ├── pages/              # 页面组件
│   ├── components/         # 可复用组件
│   ├── types/              # TypeScript 类型定义
│   └── nuxt.config.ts      # Nuxt 配置
├── backend/                 # FastAPI 后端
│   ├── routers/            # API 路由
│   ├── services/
│   │   ├── ytdlp.py        # yt-dlp 封装
│   │   ├── douyin.py       # 抖音自实现 API（绕过 yt-dlp 失效）
│   │   └── abogus.py       # 抖音 a_bogus 签名生成
│   ├── models.py           # Pydantic 模型
│   ├── main.py             # 应用入口
│   ├── downloads/          # 下载文件存储（gitignore）
│   ├── previews/           # 预览流缓存（30 分钟自动清理）
│   └── thumbnails/         # 缩略图缓存（Instagram 等）
└── CLAUDE.md               # Claude Code 开发文档
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/parse` | 解析视频链接 |
| POST | `/api/start-download` | 开始下载任务 |
| GET | `/api/download/{task_id}` | 下载文件（流式） |
| WS | `/api/ws/progress/{task_id}` | 实时进度推送 |
| POST | `/api/open-folder` | 打开下载目录（Windows Explorer） |
| GET | `/api/thumbnail/{filename}` | 本地缩略图（Instagram 缓存） |
| GET | `/api/proxy/image` | 图片代理（B站/Instagram/小红书 防盗链） |
| GET | `/api/proxy/stream` | 视频/音频流代理（支持 Range 请求） |
| GET | `/api/preview-stream` | 预览流（抖音/TikTok/X 服务端下载+合并） |

## 平台说明

| 平台 | 解析 | 下载 | 备注 |
|------|------|------|------|
| YouTube | ✅ | ✅ | 全画质（360p ~ 4K），直链预览 |
| Bilibili (B站) | ✅ | ✅ | Firefox 登录后可下载 1080P+ |
| Instagram | ✅ | ✅ | 缩略图本地缓存，DASH 音视频同步 |
| TikTok | ✅ | ✅ | 无水印，服务端预览流 |
| 抖音 | ✅ | ✅ | 自实现 API 绕过（yt-dlp 已失效） |
| 小红书 | ✅ | ✅ | CDN 代理绕过防盗链 |
| 微博 | ✅ | ✅ | |
| X (Twitter) | ✅ | ✅ | 浏览器 cookies 自动读取 |
| Facebook | ✅ | ✅ | share 链接 + Reel 全支持 |

### B站 1080P+ 高清下载

1080P 及以上画质需要登录态 Cookie。当前实现自动读取本地 Firefox 浏览器配置：

1. 在 Firefox 中登录 bilibili.com
2. 解析时服务自动从 `%APPDATA%\Mozilla\Firefox\Profiles\*\cookies.sqlite` 提取 `bilibili.com` 相关 Cookie
3. Cookie 模式失败时自动回退到 visitor 模式（最高 480p）

Chrome / Edge 暂不支持（Cookie 数据库加密格式不同）。

## 支持平台

| 平台 | 解析 | 下载 | 备注 |
|------|------|------|------|
| YouTube | ✅ | ✅ | |
| TikTok | ✅ | ✅ | 无水印 |
| Instagram | ✅ | ✅ | 无水印 |
| Bilibili | ✅ | ✅ | 高清需登录 |
| Twitter/X | ✅ | ✅ | |

## 开发说明

### Python 环境

本项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖，所有 Python 命令需通过 `uv run` 执行：

```bash
# ✅ 正确
uv run python main.py
uv run pytest

# ❌ 错误
python main.py
pip install xxx
```

## 免责声明

本项目仅供学习交流使用，请勿用于商业用途。下载内容版权归原作者所有，请遵守相关平台服务条款及当地法律法规。

## License

MIT
