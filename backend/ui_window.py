from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import threading
import webbrowser

from PIL import Image
import webview

from backend.config import DATA_DIR, ICON_PATH, STATE_FILE, WEBVIEW_DATA_DIR

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
SW_RESTORE = 9


class WindowApi:
    """JS bridge exposed as window.pywebview.api inside the WebView2 UI process.

    Note: All non-API attributes MUST start with `_` so pywebview's js_api
    introspector never walks into WinForms `.native` objects (which causes
    infinite recursion on AccessibilityObject.Bounds.Empty).
    """

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._is_maximized = False
        self._is_fullscreen = False
        self._revealed = False
        self._reveal_lock = threading.Lock()

    def _attach(self, win: webview.Window) -> None:
        self._window = win

    def _hwnd(self) -> int:
        if not self._window:
            return 0
        try:
            native = getattr(self._window, "native", None)
            if native is not None and hasattr(native, "Handle"):
                return int(native.Handle.ToInt64())
        except Exception:
            pass
        return 0

    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def maximize(self) -> bool:
        if not self._window:
            return False
        if self._is_maximized:
            self._window.restore()
            self._is_maximized = False
        else:
            self._window.maximize()
            self._is_maximized = True
        return self._is_maximized

    def close(self) -> None:
        if self._window:
            self._window.destroy()

    def is_maximized(self) -> bool:
        hwnd = self._hwnd()
        if hwnd:
            self._is_maximized = bool(user32.IsZoomed(hwnd))
        return self._is_maximized or self._is_fullscreen

    def toggle_fullscreen(self) -> bool:
        if not self._window:
            return False
        self._window.toggle_fullscreen()
        self._is_fullscreen = not self._is_fullscreen
        return self._is_fullscreen

    def is_fullscreen(self) -> bool:
        return self._is_fullscreen

    def open_external(self, url: str) -> None:
        if isinstance(url, str) and (url.startswith("https://") or url.startswith("http://")):
            webbrowser.open(url)

    def _run_file_dialog(self, handler: Any) -> Any:
        if not self._window:
            return None
        native = getattr(self._window, "native", None)
        if native is None:
            return None

        result: dict[str, Any] = {"value": None, "error": None}
        done = threading.Event()

        def _invoke() -> None:
            try:
                import System.Windows.Forms as WinForms

                result["value"] = handler(WinForms, native)
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                done.set()

        try:
            if native.InvokeRequired:
                from System import Action

                native.BeginInvoke(Action(_invoke))
            else:
                _invoke()
            done.wait(timeout=300)
        except Exception as exc:
            raise RuntimeError(f"无法打开文件选择框: {exc}") from exc

        if result["error"]:
            raise RuntimeError(str(result["error"]))
        return result["value"]

    def open_json_file(self) -> str | None:
        """Open a JSON file picker on the WinForms UI thread and return its UTF-8 text."""
        def _pick(WinForms: Any, native: Any) -> str | None:
            dialog = WinForms.OpenFileDialog()
            dialog.Filter = "JSON 文件 (*.json)|*.json|所有文件 (*.*)|*.*"
            dialog.RestoreDirectory = True
            if dialog.ShowDialog(native) == WinForms.DialogResult.OK and dialog.FileName:
                return Path(str(dialog.FileName)).read_text(encoding="utf-8-sig")
            return None

        return self._run_file_dialog(_pick)

    def save_json_file(self, filename: str, content: str) -> str | None:
        """Open a JSON save dialog on the WinForms UI thread and write UTF-8 text."""
        def _save(WinForms: Any, native: Any) -> str | None:
            dialog = WinForms.SaveFileDialog()
            dialog.Filter = "JSON 文件 (*.json)|*.json|所有文件 (*.*)|*.*"
            dialog.DefaultExt = "json"
            dialog.AddExtension = True
            dialog.RestoreDirectory = True
            dialog.FileName = Path(str(filename or "bilimusic-playlists.json")).name
            if dialog.ShowDialog(native) == WinForms.DialogResult.OK and dialog.FileName:
                target = Path(str(dialog.FileName))
                target.write_text(str(content), encoding="utf-8")
                return str(target)
            return None

        return self._run_file_dialog(_save)

    def start_drag(self) -> None:
        if not self._window or self._is_fullscreen:
            return
        native = getattr(self._window, "native", None)
        if native is None:
            return

        def _do_drag() -> None:
            hwnd = int(native.Handle.ToInt64())
            if hwnd:
                user32.ReleaseCapture()
                user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)

        try:
            if native.InvokeRequired:
                from System import Action
                native.BeginInvoke(Action(_do_drag))
            else:
                _do_drag()
        except Exception:
            pass

    def _reveal_window(self) -> None:
        with self._reveal_lock:
            if self._revealed or not self._window:
                return
            self._revealed = True
        win = self._window
        native = getattr(win, "native", None)
        if native is None:
            try:
                win.show()
            except Exception:
                pass
            return

        def _start_fade() -> None:
            try:
                import System.Windows.Forms as WinForms

                if getattr(native, "IsDisposed", False):
                    return
                native.Opacity = 0.0
                native.Show()
                native.Activate()

                def _clear_initial_focus() -> None:
                    try:
                        win.evaluate_js(
                            "if (document.activeElement && document.activeElement !== document.body "
                            "&& typeof document.activeElement.blur === 'function') { document.activeElement.blur(); }"
                        )
                    except Exception:
                        pass

                focus_timer = threading.Timer(0.05, _clear_initial_focus)
                focus_timer.daemon = True
                focus_timer.start()

                steps = 10
                state = {"step": 0}
                timer = WinForms.Timer()
                timer.Interval = 15

                def _on_tick(_sender: Any, _args: Any) -> None:
                    try:
                        if getattr(native, "IsDisposed", False):
                            timer.Stop()
                            timer.Dispose()
                            return
                        state["step"] += 1
                        t = min(1.0, state["step"] / steps)
                        native.Opacity = 1.0 - (1.0 - t) * (1.0 - t)
                        if state["step"] >= steps:
                            native.Opacity = 1.0
                            timer.Stop()
                            timer.Dispose()
                    except Exception:
                        try:
                            timer.Stop()
                            timer.Dispose()
                        except Exception:
                            pass

                timer.Tick += _on_tick
                timer.Start()
            except Exception:
                try:
                    native.Opacity = 1.0
                    win.show()
                except Exception:
                    pass

        try:
            if native.InvokeRequired:
                from System import Action

                native.BeginInvoke(Action(_start_fade))
            else:
                _start_fade()
        except Exception:
            try:
                win.show()
            except Exception:
                pass

    def _focus_window(self) -> None:
        if not self._window:
            return
        if not self._revealed:
            self._reveal_window()
            return
        try:
            self._window.restore()
            self._window.show()
            hwnd = self._hwnd()
            if hwnd:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def _stdin_control_loop(api: WindowApi) -> None:
    for raw in sys.stdin:
        cmd = raw.strip()
        if cmd == "focus":
            api._focus_window()
        elif cmd == "quit":
            api.close()
            break


def _initial_bg_color() -> str:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("theme") == "light":
                return "#F6F7F9"
    except Exception:
        pass
    return "#17181A"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m backend.ui_window <url>")

    url = sys.argv[1]
    WEBVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    api = WindowApi()
    win = webview.create_window(
        title="BiliMusic",
        url=url,
        js_api=api,
        width=1280,
        height=800,
        min_size=(1024, 640),
        frameless=True,
        easy_drag=False,
        shadow=True,
        hidden=True,
        background_color=_initial_bg_color(),
    )
    api._attach(win)

    fallback_timer = threading.Timer(1.2, api._reveal_window)
    fallback_timer.daemon = True

    def on_loaded() -> None:
        fallback_timer.cancel()
        reveal_timer = threading.Timer(0.06, api._reveal_window)
        reveal_timer.daemon = True
        reveal_timer.start()

    win.events.loaded += on_loaded
    fallback_timer.start()

    def on_maximized() -> None:
        api._is_maximized = True
        try:
            win.evaluate_js("window.dispatchEvent(new CustomEvent('bilimusic:maximized-change', {detail: true}))")
        except Exception:
            pass

    def on_restored() -> None:
        api._is_maximized = False
        try:
            win.evaluate_js("window.dispatchEvent(new CustomEvent('bilimusic:maximized-change', {detail: false}))")
        except Exception:
            pass

    win.events.maximized += on_maximized
    win.events.restored += on_restored

    threading.Thread(target=_stdin_control_loop, args=(api,), daemon=True).start()

    icon: str | None = None
    if ICON_PATH.exists():
        ico_path = DATA_DIR / "icon.ico"
        try:
            if not ico_path.exists():
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with Image.open(ICON_PATH) as img:
                    img.convert("RGBA").save(
                        ico_path,
                        format="ICO",
                        sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)],
                    )
            icon = str(ico_path)
        except Exception:
            icon = None

    webview.start(
        private_mode=False,
        storage_path=str(WEBVIEW_DATA_DIR),
        icon=icon,
        debug=False,
    )


if __name__ == "__main__":
    main()
