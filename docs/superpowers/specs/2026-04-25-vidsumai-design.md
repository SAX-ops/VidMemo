# VidSumAI 设计文档

## Context

开发一款支持多平台的网络视频下载器 VidSumAI，基于 MoSCoW 法则进行优先级管理。第一版为最小 MVP，仅包含核心下载功能。

## 项目概要

| 维度 | 选择 |
|------|------|
| 前端 | Vue 3 + Nuxt.js 3 |
| 后端 | Python FastAPI |
| 下载引擎 | yt-dlp (subprocess 调用) |
| 传输方式 | 浏览器流式下载 |
| UI 风格 | 深色极简，参考 snapvee.com |
| 范围 | 最小 MVP |

## 架构设计

```
┌─────────────────────────────────────────────────────┐
│                    Browser (Vue)                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────┐ │
│  │ URL输入  │  │ 清晰度  │  │    下载进度条       │ │
│  └─────────┘  └─────────┘  └─────────────────────┘ │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP/WebSocket
┌───────────────────────▼─────────────────────────────┐
│              Python Backend (FastAPI)                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────┐ │
│  │链接解析  │  │格式提取  │  │    流式传输        │ │
│  └─────────┘  └─────────┘  └─────────────────────┘ │
│                       │                              │
│              ┌────────▼────────┐                     │
│              │    yt-dlp       │                     │
│              │   (subprocess)  │                     │
│              └─────────────────┘                     │
└─────────────────────────────────────────────────────┘
```

## MoSCoW 优先级

### Must Have (MVP)
- [x] 基本下载功能：输入 URL，解析视频信息，下载视频
- [x] 主流网站支持：YouTube、TikTok、Instagram、Bilibili
- [x] 清晰度选择：支持 1080p、720p、480p、360p、240p
- [x] 进度显示：WebSocket 实时推送下载进度
- [x] 预览功能：解析后可直接播放视频再决定是否下载
- [x] 打开文件夹：下载完成后可打开浏览器默认下载目录

### Should Have (第二版)
- [ ] 批量下载：支持多个链接同时提交
- [ ] 任务管理：查看历史下载记录
- [ ] 自定义下载路径：用户选择保存位置（非浏览器默认）

### Could Have (后续)
- [ ] AI 智能总结：视频内容摘要（暂不实现）

### Won't Have
- 独立音质选择（音质随画质自动适配）
- 视频格式转换
- 加密网站下载
- 会员/登录态内容

## UI 设计规范

### 品牌识别
- **Logo**：播放键图标 + 渐变色背景
- **主色**：红黄渐变 (#ff6b6b → #feca57)
- **背景**：深色 (#0a0a0f)
- **文字**：白色为主，灰色 (#888) 为辅

### 核心页面
1. **首页**
   - 大标题："无水印高清视频一键下载"
   - 卖点标签：极速解析、4K 超高清、无水印、多平台支持
   - 下载输入框 + "解析" 按钮
   - 清晰度选择下拉框
   - 预览播放器区域
   - 下载按钮 + 进度条
   - 支持平台展示

### 交互流程（预览后下载）
```
用户粘贴链接 → 点击"解析" → 显示封面/标题/平台/时长 → 用户选画质 → 点击"预览" → 播放器直接播放 → 确认要下载 → 点击"下载到本地" → 浏览器下载 → 显示"打开文件夹"按钮
```

### 预览播放器 UI
预览区域在解析成功后显示：

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│              [视频封面图 - 未预览状态]                    │
│                                                         │
│     ▶  点击预览按钮开始播放                              │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  平台：YouTube                                           │
│  标题：Rick Astley - Never Gonna Give You Up             │
│  时长：3:33                                             │
│  已选画质：1080p                                         │
└─────────────────────────────────────────────────────────┘
        [预览视频]                      [下载到本地]
```

预览播放器激活状态：

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│              [HTML5 Video 播放器]                        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  平台：YouTube                                           │
│  标题：Rick Astley - Never Gonna Give You Up             │
│  时长：3:33                                             │
│  已选画质：1080p                                         │
└─────────────────────────────────────────────────────────┘
```

### 下载后交互
```
下载完成
    │
    ├── 显示："下载完成！保存到：C:\Users\用户名\Downloads"
    │
    ├── 显示："打开文件夹" 按钮
    │           │
    │           └── 点击 → 后端执行 os.startfile(download_folder)
    │
    └── 显示："重新下载" 按钮
```

### 下载路径选择
- 首次下载时，显示"选择下载文件夹"按钮（使用 `<input type="file" webkitdirectory>`）
- 路径保存到 localStorage
- 之后下载时显示："将保存到：你上次选择的文件夹"，并提供"更改"按钮
- 实际下载仍到浏览器默认目录，"打开文件夹"打开的是浏览器默认目录

## API 设计

### 端点

```
POST /api/parse
  - 输入：{ url: string }
  - 输出：{ title, thumbnail, duration, platform, formats: [{quality, ext, size, url}] }

POST /api/start-download
  - 输入：{ url: string, quality: string }
  - 输出：{ task_id: string }

GET /api/download/{task_id}
  - 流式返回视频文件
  - Header: Content-Disposition: attachment

WebSocket /ws/progress/{task_id}
  - 实时推送：{ status, progress, speed, eta, downloaded }

POST /api/open-folder
  - 输入：{ folder_path: string }（可选，不传则打开默认下载目录）
  - 后端执行：os.startfile(folder_path) (Windows)
  - 输出：{ success: true }
```

## 技术实现

### 后端 (Python FastAPI)

```python
# 核心依赖
- fastapi
- uvicorn
- yt-dlp (通过 subprocess 调用)
- websockets

# 关键实现
1. /api/parse: 调用 yt-dlp --dump-json 获取视频信息
2. /api/download: 调用 yt-dlp 下载，流式传输到客户端
3. WebSocket: 通过 yt-dlp progress hook 推送进度
```

### 前端 (Vue + Nuxt.js)

```javascript
// 核心依赖
- nuxt 3
- @nuxtjs/tailwindcss (样式)
- 原生 WebSocket

// 关键组件
1. DownloadInput: URL 输入 + 解析按钮
2. VideoPreview: 视频预览播放器（含封面、info、预览按钮、下载按钮）
3. QualitySelector: 画质选择下拉框
4. ProgressTracker: 进度条显示 + 打开文件夹按钮
5. PlatformList: 支持平台展示

// localStorage 使用
- downloadFolder: 用户上次选择的下载文件夹路径
```

## 验证方案

1. **功能测试**
   - 输入 YouTube 链接，验证解析和下载
   - 输入 TikTok 链接，验证解析和下载
   - 测试清晰度选择功能
   - 验证进度条实时更新
   - **验证预览播放功能**：点击预览后视频是否正常播放
   - **验证下载完成交互**：下载完成后是否显示"打开文件夹"按钮

2. **边界测试**
   - 无效链接处理
   - 网络错误处理
   - 大文件下载稳定性
   - 预览 URL 过期处理（高画质 URL 可能较快过期）

3. **UI 测试**
   - 响应式布局（桌面端）
   - 深色主题一致性
   - 交互流程顺畅：URL → 解析 → 预览 → 下载 → 打开文件夹

## 文件结构

```
vidsumai/
├── frontend/              # Nuxt.js 前端
│   ├── pages/
│   │   └── index.vue     # 首页
│   ├── components/
│   │   ├── DownloadInput.vue    # URL 输入 + 解析按钮
│   │   ├── VideoPreview.vue      # 视频预览播放器
│   │   ├── QualitySelector.vue   # 画质选择下拉框
│   │   ├── ProgressTracker.vue   # 下载进度条
│   │   └── PlatformList.vue      # 支持平台展示
│   └── nuxt.config.ts
├── backend/               # FastAPI 后端
│   ├── main.py           # 入口
│   ├── routers/
│   │   └── download.py   # 下载路由
│   ├── services/
│   │   └── ytdlp.py      # yt-dlp 封装
│   ├── pyproject.toml    # Python 依赖（uv 管理）
│   └── uv.lock
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-25-vidsumai-design.md
```
