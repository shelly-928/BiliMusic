from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from typing import Any, Awaitable, Callable

from backend.config import BIN_DIR, LIBMPV_DLL


def _import_mpv() -> Any:
    if not LIBMPV_DLL.exists():
        raise FileNotFoundError(f"libmpv-2.dll not found at {LIBMPV_DLL}")
    bin_dir = str(BIN_DIR)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(bin_dir)
    path_val = os.environ.get("PATH", "")
    if bin_dir not in path_val.split(os.pathsep):
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{path_val}"
    import mpv

    return mpv


class MpvPlayer:
    """Headless in-process audio player backed by libmpv-2.dll."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._loop = loop
        self._on_event = on_event
        self._lock = threading.Lock()
        self._player: Any = None
        self._mpv_mod: Any = None
        self._last_time_pos_emit = 0.0

    def _dispatch_event(self, payload: dict[str, Any]) -> None:
        if self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._on_event(payload), self._loop)
        except RuntimeError:
            pass

    def start(self) -> None:
        mpv = _import_mpv()
        self._mpv_mod = mpv

        player = mpv.MPV(
            config=False,
            idle=True,
            vid="no",
            vo="null",
            audio_display="no",
            load_scripts=False,
            osc=False,
            osd_level=0,
            sub_auto="no",
            audio_file_auto="no",
            ytdl=False,
            cache=True,
            demuxer_max_bytes="4MiB",
            demuxer_max_back_bytes="1MiB",
            demuxer_readahead_secs=15,
            referrer="https://www.bilibili.com",
            http_header_fields="Origin: https://www.bilibili.com",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        @player.property_observer("time-pos")
        def _on_time_pos(_name: str, value: Any) -> None:
            if not isinstance(value, (int, float)):
                return
            now = time.monotonic()
            if (now - self._last_time_pos_emit) < 0.1:
                return
            self._last_time_pos_emit = now
            self._dispatch_event(
                {"event": "property-change", "name": "time-pos", "data": float(value)}
            )

        @player.property_observer("duration")
        def _on_duration(_name: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                self._dispatch_event(
                    {"event": "property-change", "name": "duration", "data": float(value)}
                )

        @player.property_observer("pause")
        def _on_pause(_name: str, value: Any) -> None:
            if isinstance(value, bool):
                self._dispatch_event(
                    {"event": "property-change", "name": "pause", "data": value}
                )

        @player.event_callback("end-file")
        def _on_end_file(event: Any) -> None:
            data = getattr(event, "data", None)
            if data is None:
                return
            if data.reason == mpv.MpvEventEndFile.EOF:
                self._dispatch_event({"event": "end-file", "reason": "eof"})
            elif data.reason == mpv.MpvEventEndFile.ERROR:
                err = getattr(data, "error", 0)
                print(f"[mpv] playback error code={err}", file=sys.stderr, flush=True)
                self._dispatch_event({"event": "end-file", "reason": "error", "error": err})

        with self._lock:
            self._player = player

    def load_url(self, url: str, start_seconds: float = 0.0, paused: bool = False) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        self._last_time_pos_emit = 0.0
        player.pause = bool(paused)
        if start_seconds > 0.2:
            player.loadfile(url, "replace", start=f"{start_seconds:.2f}")
        else:
            player.loadfile(url, "replace")

    def set_pause(self, paused: bool) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        player.pause = bool(paused)

    def seek(self, seconds: float) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        player.seek(max(0.0, float(seconds)), "absolute")

    def set_volume(self, volume: float) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        player.volume = max(0.0, min(100.0, float(volume)))

    def set_mute(self, muted: bool) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        player.mute = bool(muted)

    def stop(self) -> None:
        with self._lock:
            player = self._player
        if player is None:
            return
        player.stop()

    def close(self) -> None:
        with self._lock:
            player = self._player
            self._player = None
        if player is not None:
            try:
                player.terminate()
            except Exception:
                pass
