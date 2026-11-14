<div align="center">
  <img src="./src/assets/icon.png" width="112" height="112" alt="BiliMusic Logo" />
  <h1>BiliMusic Py (v0.1.0)</h1>
  <p>
    <strong>基于 Bilibili 的桌面音乐播放器（Python + libmpv + pywebview 重构分支）</strong>
  </p>
  <p>
    当前分支基于 <a href="https://github.com/HanversionOvO/BiliMusic">HanversionOvO/BiliMusic</a> v1.0.2 改写 ·
    <a href="https://github.com/shelly-928/BiliMusic">分支仓库</a>
  </p>
</div>

## 分支说明

本分支保留原版 React + TypeScript 界面与交互设计，将桌面运行时和播放后端由 Electron 重写为轻量 Python 架构：

- **本地服务与 API 代理**：使用 Python `aiohttp`（默认端口 `17890`）托管前端构建产物并代理 Bilibili / 歌词请求（`curl-cffi`）。
- **独立音频后端**：使用 `python-mpv` + `libmpv-2.dll` 进行无头音频解码与播放控制，脱离浏览器 `<audio>` 限制。
- **按需窗口与常驻托盘**：通过 `pystray` 常驻系统托盘，仅在打开界面时启动 `pywebview` 渲染子进程，关闭窗口后销毁窗口进程以减少空闲内存占用。
- **平台聚焦**：当前围绕 Windows 桌面端重构；原版完整产品介绍以及 Electron / HarmonyOS PC 工程说明请参见 [原版仓库](https://github.com/HanversionOvO/BiliMusic)。仓库中保留的 `electron/`、`platform/HarmonyOS/`、`scripts/` 为上游历史目录，非当前运行时依赖。

## 环境要求

- Windows 10 / 11（依赖 Edge WebView2 运行时，系统通常已内置）
- Python `>= 3.11`（推荐使用 `uv` 管理虚拟环境）
- Node.js `>= 20` 与 `npm`（用于构建 `dist/` 前端资源）
- `libmpv-2.dll`（Windows x64）：需自行放置到 `backend/bin/libmpv-2.dll`（`backend/bin/` 已被 `.gitignore` 忽略）

## 快速开始

### 1. 安装前端依赖并构建

```bash
npm install
npm run build
```

### 2. 创建虚拟环境并安装 Python 依赖

```bash
uv venv
uv pip install aiohttp curl-cffi pillow pystray python-mpv pywebview
```

依赖清单与版本下限见 [pyproject.toml](./pyproject.toml)。

### 3. 准备 libmpv

将 `libmpv-2.dll` 放入以下路径：

```text
backend/bin/libmpv-2.dll
```

### 4. 启动应用

方式一：直接运行根目录脚本（若缺少 `dist/index.html` 会自动执行 `npm run build` 并以无控制台模式启动）：

```bat
start.bat
```

方式二：命令行启动：

```bash
.venv\Scripts\python.exe -m backend.main
```

可选启动参数与环境变量：

- `--tray` 或 `--minimized`：启动后仅驻留系统托盘，不立即弹出主窗口。
- `BILIMUSIC_PORT`：自定义本地服务端口（默认 `17890`）。

### 前端开发调试

在后端已启动的情况下，也可单独启动 Vite 开发服务器，或者直接修改前端后重新运行 `npm run build`：

```bash
npm run dev
```

## 项目结构

```text
bilimusic/
├─ backend/
│  ├─ main.py            守护进程入口、单实例唤醒、pywebview 子进程管理
│  ├─ server.py          aiohttp HTTP/WebSocket 服务与 API 路由
│  ├─ bili_client.py     Bilibili 与歌词 API 请求封装
│  ├─ player_engine.py   播放队列、随机/循环逻辑与状态持久化
│  ├─ mpv_player.py      libmpv 音频播放控制封装
│  ├─ ui_window.py       pywebview 主界面子进程
│  ├─ tray.py            pystray 系统托盘控制
│  ├─ tray_popup.py      原生托盘弹窗子进程
│  ├─ config.py          路径、端口、版本号配置
│  └─ bin/               放置 libmpv-2.dll（未纳入 Git）
├─ src/                  React 前端页面、播放器状态与 Web Bridge
├─ dist/                 前端构建产物（npm run build 生成）
├─ start.bat             Windows 一键启动脚本
├─ pyproject.toml        Python 项目与依赖定义
└─ package.json          前端依赖与构建脚本
```

## 数据持久化

运行时数据保存在本地用户目录下（Windows 默认为 `%LOCALAPPDATA%\BiliMusicPy`）：

- `cookies.json`：Bilibili 登录会话凭证
- `player_state.json`：当前曲目、播放队列、进度与播放模式状态
- `webview_data/`：WebView2 缓存与前端 `localStorage` 数据（歌单、主题、设置、歌词缓存等）

## 免责声明与致谢

- 本项目仅用于学习、研究与个人使用，与 Bilibili、Apple Music、Apple Inc. 及相关服务提供方无任何从属或商业合作关系，不内置任何音频、视频或歌词资源。请遵守相关平台服务条款与版权法律法规。
- 界面设计与核心前端逻辑源自 [HanversionOvO/BiliMusic](https://github.com/HanversionOvO/BiliMusic)（作者：MikannQAQ）。
