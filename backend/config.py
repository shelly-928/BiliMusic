from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BIN_DIR = ROOT_DIR / "backend" / "bin"
LIBMPV_DLL = BIN_DIR / "libmpv-2.dll"
ICON_PATH = ROOT_DIR / "src" / "assets" / "icon.png"

LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
DATA_DIR = LOCAL_APPDATA / "BiliMusicPy"
COOKIES_FILE = DATA_DIR / "cookies.json"
STATE_FILE = DATA_DIR / "player_state.json"
WEBVIEW_DATA_DIR = DATA_DIR / "webview_data"

DEFAULT_PORT = int(os.environ.get("BILIMUSIC_PORT", "17890"))
APP_VERSION = "0.1.0"
