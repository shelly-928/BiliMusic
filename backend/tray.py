from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
from typing import Any, Callable

from PIL import Image
import pystray

from backend.config import ICON_PATH

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
ASFW_ANY = -1
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
if hasattr(user32, "SetThreadDpiAwarenessContext"):
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p


def _get_physical_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    prev_ctx = None
    if hasattr(user32, "SetThreadDpiAwarenessContext"):
        try:
            prev_ctx = user32.SetThreadDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
        except Exception:
            prev_ctx = None
    try:
        user32.GetCursorPos(ctypes.byref(pt))
    finally:
        if prev_ctx is not None:
            try:
                user32.SetThreadDpiAwarenessContext(prev_ctx)
            except Exception:
                pass
    return (int(pt.x), int(pt.y))


class _PopupTrayIcon(pystray.Icon):
    """Win32 pystray subclass: left click opens UI, right click toggles popup window."""

    def __init__(
        self,
        *args: Any,
        on_left_click: Callable[[], None],
        on_right_click: Callable[[int, int], None] | None = None,
        **kwargs: Any,
    ) -> None:
        self._on_left_click = on_left_click
        self._on_right_click = on_right_click
        super().__init__(*args, **kwargs)

    def _on_notify(self, wparam: int, lparam: int) -> None:
        if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            self._on_left_click()
            return
        if lparam == WM_RBUTTONUP and self._on_right_click is not None:
            px, py = _get_physical_cursor_pos()
            user32.AllowSetForegroundWindow(ASFW_ANY)
            self._on_right_click(px, py)
            return
        super()._on_notify(wparam, lparam)


class TrayController:
    """Lightweight Windows system tray icon supporting left-click focus and custom right-click popup."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_open_ui: Callable[[], None],
        on_toggle_play: Callable[[], asyncio.Future[Any] | Any],
        on_next: Callable[[], asyncio.Future[Any] | Any],
        on_prev: Callable[[], asyncio.Future[Any] | Any],
        on_quit: Callable[[], None],
        on_toggle_popup: Callable[[int, int], None] | None = None,
    ) -> None:
        self._loop = loop
        self._on_open_ui = on_open_ui
        self._on_toggle_play = on_toggle_play
        self._on_next = on_next
        self._on_prev = on_prev
        self._on_quit = on_quit
        self._on_toggle_popup = on_toggle_popup
        self._state: dict[str, Any] = {
            "hasTrack": False,
            "title": "未在播放",
            "artist": "搜索并播放音乐",
            "isPlaying": False,
        }
        self._icon: pystray.Icon | None = None

    def _load_image(self) -> Image.Image:
        if ICON_PATH.exists():
            with Image.open(ICON_PATH) as img:
                return img.convert("RGBA").resize((32, 32), Image.Resampling.LANCZOS)
        return Image.new("RGBA", (32, 32), (250, 45, 72, 255))

    def _dispatch(self, coro_fn: Callable[[], Any]) -> None:
        try:
            res = coro_fn()
            if asyncio.iscoroutine(res):
                asyncio.run_coroutine_threadsafe(res, self._loop)
        except Exception:
            pass

    def start(self) -> None:
        menu = None
        if self._on_toggle_popup is None:
            menu = pystray.Menu(
                pystray.MenuItem("打开 BiliMusic", lambda _i, _m: self._on_open_ui(), default=True),
                pystray.MenuItem(
                    lambda _item: "暂停" if self._state.get("isPlaying") else "播放",
                    lambda _i, _m: self._dispatch(self._on_toggle_play),
                ),
                pystray.MenuItem("上一首", lambda _i, _m: self._dispatch(self._on_prev)),
                pystray.MenuItem("下一首", lambda _i, _m: self._dispatch(self._on_next)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda _i, _m: self._on_quit()),
            )
        self._icon = _PopupTrayIcon(
            "BiliMusic",
            self._load_image(),
            "BiliMusic",
            menu=menu,
            on_left_click=self._on_open_ui,
            on_right_click=self._on_toggle_popup,
        )
        self._icon.run_detached()

    def update_state(self, state: dict[str, Any]) -> None:
        self._state = dict(state)
        if not self._icon:
            return
        try:
            if state.get("hasTrack"):
                prefix = "正在播放" if state.get("isPlaying") else "已暂停"
                tip = f"{prefix}: {state.get('title', '')}"
            else:
                tip = "BiliMusic"
            # Windows NOTIFYICONDATA tooltip max 127 chars
            self._icon.title = tip[:120]
            if self._icon.menu is not None:
                self._icon.update_menu()
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
