from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import urllib.request

from aiohttp import web

from backend.bili_client import BiliClient
from backend.config import DEFAULT_PORT
from backend.player_engine import PlayerEngine
from backend.server import create_app
from backend.tray import TrayController
from backend.tray_popup import NativeTrayPopup

CREATE_NO_WINDOW = 0x08000000


def _try_wake_existing_instance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.6) as resp:
            info = json.loads(resp.read().decode("utf-8"))
            if info.get("app") == "BiliMusic":
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/ui/open",
                    data=b"{}",
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=1.0).close()
                return True
    except Exception:
        pass
    return False


def _pick_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _SubprocessWindow:
    """Shared lifecycle helper for on-demand pywebview window subprocesses."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _send(self, cmd: str) -> bool:
        if not self._is_alive():
            return False
        try:
            if self._proc and self._proc.stdin:
                self._proc.stdin.write(f"{cmd}\n".encode("utf-8"))
                self._proc.stdin.flush()
                return True
        except Exception:
            pass
        return False

    def _spawn(self, flag: str, module: str, *args: str) -> None:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        cmd = (
            [sys.executable, flag, *args]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", module, *args]
        )
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )

    def close(self) -> None:
        if self._is_alive():
            try:
                self._send("quit")
                if self._proc:
                    self._proc.wait(timeout=1.5)
            except Exception:
                try:
                    if self._proc:
                        self._proc.terminate()
                except Exception:
                    pass
        self._proc = None


class UiWindowManager(_SubprocessWindow):
    """Spawns and disposes the pywebview UI subprocess on demand."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def open_or_focus(self) -> None:
        if self._send("focus"):
            return
        self._spawn("--ui-window", "backend.ui_window", self._url)


async def run_daemon(open_on_start: bool = True) -> None:
    loop = asyncio.get_running_loop()
    port = _pick_port(DEFAULT_PORT)
    ui_url = f"http://127.0.0.1:{port}/"
    ui_mgr = UiWindowManager(ui_url)

    stop_event = asyncio.Event()
    bili = BiliClient()
    tray_holder: dict[str, TrayController | None] = {"tray": None}
    popup_holder: dict[str, NativeTrayPopup | None] = {"popup": None}

    def on_tray_state(state: dict) -> None:
        tray = tray_holder["tray"]
        if tray:
            tray.update_state(state)
        popup = popup_holder["popup"]
        if popup:
            popup.notify_state_changed()

    engine = PlayerEngine(loop=loop, bili=bili, on_tray_update=on_tray_state)

    def request_quit() -> None:
        loop.call_soon_threadsafe(stop_event.set)

    def on_popup_action(action: str) -> None:
        coro = None
        if action == "prev":
            coro = engine.prev_track()
        elif action == "next":
            coro = engine.next_track()
        elif action == "toggle":
            coro = engine.toggle_play()
        if coro is not None:
            asyncio.run_coroutine_threadsafe(coro, loop)

    tray_popup = NativeTrayPopup(
        get_state=engine.tray_state,
        on_action=on_popup_action,
        on_open_ui=ui_mgr.open_or_focus,
        on_quit=request_quit,
    )
    popup_holder["popup"] = tray_popup
    tray_popup.start()

    tray = TrayController(
        loop=loop,
        on_open_ui=ui_mgr.open_or_focus,
        on_toggle_play=engine.toggle_play,
        on_next=engine.next_track,
        on_prev=engine.prev_track,
        on_quit=request_quit,
        on_toggle_popup=tray_popup.toggle_at,
    )
    tray_holder["tray"] = tray

    app = create_app(
        bili=bili,
        engine=engine,
        on_open_ui=ui_mgr.open_or_focus,
        on_quit=request_quit,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    engine.start()
    tray.start()

    if open_on_start:
        ui_mgr.open_or_focus()

    try:
        await stop_event.wait()
    finally:
        tray_popup.close()
        ui_mgr.close()
        tray.stop()
        engine.close()
        await runner.cleanup()
        await bili.close()


def _ensure_stdio() -> None:
    # --noconsole 冻结进程下 stdout/stderr 可能为 None，避免第三方库写入报错
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> None:
    _ensure_stdio()
    if len(sys.argv) >= 3 and sys.argv[1] == "--ui-window":
        from backend.ui_window import main as ui_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        ui_main()
        return

    open_on_start = "--tray" not in sys.argv and "--minimized" not in sys.argv
    if _try_wake_existing_instance(DEFAULT_PORT):
        return
    try:
        asyncio.run(run_daemon(open_on_start=open_on_start))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
