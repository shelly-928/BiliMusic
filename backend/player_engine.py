from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from typing import Any, Callable

from backend.bili_client import BiliClient
from backend.config import DATA_DIR, STATE_FILE
from backend.mpv_player import MpvPlayer


class PlayerEngine:
    """Authoritative backend playback state, queue controller, and WS state broadcaster."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        bili: BiliClient,
        on_tray_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._loop = loop
        self._bili = bili
        self._on_tray_update = on_tray_update
        self._mpv = MpvPlayer(loop, self._on_mpv_event)
        self._clients: set[Any] = set()

        self.current_track: dict[str, Any] | None = None
        self.queue: list[dict[str, Any]] = []
        self._shuffled_queue: list[dict[str, Any]] = []
        self.current_index: int = -1
        self.is_playing: bool = False
        self.progress: float = 0.0
        self.duration: float = 0.0
        self.volume: float = 80.0
        self.is_muted: bool = False
        self.repeat_mode: str = "none"
        self.is_shuffled: bool = False
        self.auto_play: bool = True
        self.loading_audio: bool = False
        self.recent_tracks: list[dict[str, Any]] = []
        self.theme: str = "dark"

        self._load_gen = 0
        self._load_task: asyncio.Task[None] | None = None
        self._last_persist_at = 0.0
        self._last_progress_push_at = 0.0

        self._load_persisted_state()

    def start(self) -> None:
        self._mpv.start()
        self._mpv.set_volume(self.volume)
        self._mpv.set_mute(self.is_muted)
        self._notify_tray()

    def close(self) -> None:
        self._persist_state(force=True)
        self._mpv.close()

    def _load_persisted_state(self) -> None:
        try:
            if not STATE_FILE.exists():
                return
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.current_track = data.get("currentTrack")
            q = data.get("queue")
            self.queue = q if isinstance(q, list) else []
            self.progress = max(0.0, float(data.get("progress") or 0.0))
            self.duration = max(0.0, float(data.get("duration") or 0.0))
            self.volume = max(0.0, min(100.0, float(data.get("volume", 80.0))))
            self.is_muted = bool(data.get("isMuted", False))
            rm = data.get("repeatMode")
            self.repeat_mode = rm if rm in ("none", "one", "all") else "none"
            self.is_shuffled = bool(data.get("isShuffled", False))
            self.auto_play = bool(data.get("autoPlay", True))
            recent = data.get("recentTracks")
            self.recent_tracks = recent[:50] if isinstance(recent, list) else []
            theme = data.get("theme")
            if theme in ("dark", "light"):
                self.theme = theme
            self._rebuild_shuffle()
            self._resync_index()
        except Exception:
            pass

    def _persist_state(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_persist_at) < 5.0:
            return
        self._last_persist_at = now
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "currentTrack": self.current_track,
                "queue": self.queue,
                "progress": self.progress,
                "duration": self.duration,
                "volume": self.volume,
                "isMuted": self.is_muted,
                "repeatMode": self.repeat_mode,
                "isShuffled": self.is_shuffled,
                "autoPlay": self.auto_play,
                "recentTracks": self.recent_tracks[:50],
                "theme": self.theme,
            }
            STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _display_queue(self) -> list[dict[str, Any]]:
        return self._shuffled_queue if self.is_shuffled else self.queue

    def _rebuild_shuffle(self) -> None:
        if not self.is_shuffled:
            self._shuffled_queue = list(self.queue)
            return
        cur_id = self.current_track.get("id") if self.current_track else None
        if cur_id:
            rest = [t for t in self.queue if t.get("id") != cur_id]
            if len(rest) >= 2:
                orig_ids = [t.get("id") for t in rest]
                random.shuffle(rest)
                if [t.get("id") for t in rest] == orig_ids:
                    random.shuffle(rest)
            else:
                random.shuffle(rest)
            in_queue = next((t for t in self.queue if t.get("id") == cur_id), None)
            self._shuffled_queue = ([in_queue] if in_queue else []) + rest
        else:
            arr = list(self.queue)
            random.shuffle(arr)
            self._shuffled_queue = arr

    def _resync_index(self) -> None:
        if not self.current_track:
            self.current_index = -1
            return
        cid = self.current_track.get("id")
        dq = self._display_queue()
        for i, item in enumerate(dq):
            if item.get("id") == cid:
                self.current_index = i
                return
        self.current_index = 0 if dq else -1

    def _record_recent(self, track: dict[str, Any]) -> None:
        tid = track.get("id")
        self.recent_tracks = [track] + [t for t in self.recent_tracks if t.get("id") != tid]
        self.recent_tracks = self.recent_tracks[:50]

    def snapshot(self) -> dict[str, Any]:
        return {
            "currentTrack": self.current_track,
            "isPlaying": self.is_playing,
            "progress": self.progress,
            "duration": self.duration,
            "volume": self.volume,
            "isMuted": self.is_muted,
            "repeatMode": self.repeat_mode,
            "isShuffled": self.is_shuffled,
            "autoPlay": self.auto_play,
            "queue": self.queue,
            "loadingAudio": self.loading_audio,
            "recentTracks": self.recent_tracks,
            "theme": self.theme,
        }

    def register_ws(self, ws: Any) -> None:
        self._clients.add(ws)

    def unregister_ws(self, ws: Any) -> None:
        self._clients.discard(ws)

    def tray_state(self) -> dict[str, Any]:
        track = self.current_track or {}
        return {
            "hasTrack": bool(self.current_track),
            "title": track.get("title") or "未在播放",
            "artist": track.get("artist") or "搜索并播放音乐",
            "cover": track.get("pic") or track.get("cover") or "",
            "isPlaying": self.is_playing,
            "queueCount": len(self.queue),
            "theme": self.theme,
        }

    def _notify_tray(self) -> None:
        if self._on_tray_update:
            self._on_tray_update(self.tray_state())

    async def _broadcast(self, msg_type: str, payload: dict[str, Any]) -> None:
        if not self._clients:
            return
        raw = json.dumps({"type": msg_type, "data": payload}, ensure_ascii=False)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_str(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _broadcast_state(self) -> None:
        self._notify_tray()
        self._persist_state(force=True)
        await self._broadcast("state", self.snapshot())

    async def _broadcast_progress(self) -> None:
        await self._broadcast(
            "progress",
            {"progress": self.progress, "duration": self.duration, "isPlaying": self.is_playing},
        )

    async def _load_and_play_track(
        self,
        track: dict[str, Any],
        autoplay: bool = True,
        resume_pos: float = 0.0,
    ) -> None:
        self._load_gen += 1
        gen = self._load_gen
        if self._load_task and not self._load_task.done():
            self._load_task.cancel()

        self.current_track = track
        self.progress = max(0.0, resume_pos)
        self.duration = float(track.get("duration") or 0.0)
        self.loading_audio = True
        self.is_playing = False
        self._resync_index()
        await self._broadcast_state()

        async def _worker() -> None:
            try:
                bvid = str(track.get("bvid") or track.get("id") or "")
                source = await self._bili.extract_audio(
                    bvid=bvid,
                    aid=track.get("aid"),
                    cid=track.get("cid"),
                )
                if gen != self._load_gen:
                    return
                if source.get("coverUrl"):
                    track["coverUrl"] = source["coverUrl"]
                    self.current_track = track
                if source.get("duration"):
                    self.duration = float(source["duration"])
                self._record_recent(dict(track))
                self._mpv.load_url(source["audioUrl"], start_seconds=resume_pos, paused=not autoplay)
                self.is_playing = autoplay
                self.loading_audio = False
                await self._broadcast_state()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                print(f"[engine] failed to load track: {exc}", file=sys.stderr, flush=True)
                if gen == self._load_gen:
                    self.loading_audio = False
                    self.is_playing = False
                    await self._broadcast_state()

        self._load_task = asyncio.create_task(_worker())

    async def _on_mpv_event(self, msg: dict[str, Any]) -> None:
        ev = msg.get("event")
        if ev == "property-change":
            name = msg.get("name")
            val = msg.get("data")
            if name == "time-pos" and isinstance(val, (int, float)):
                self.progress = float(val)
                now = time.monotonic()
                if (now - self._last_progress_push_at) >= 0.25:
                    self._last_progress_push_at = now
                    await self._broadcast_progress()
                self._persist_state(force=False)
            elif name == "duration" and isinstance(val, (int, float)):
                self.duration = float(val)
                await self._broadcast_progress()
            elif name == "pause" and isinstance(val, bool):
                new_playing = not val and self.current_track is not None and not self.loading_audio
                if new_playing != self.is_playing:
                    self.is_playing = new_playing
                    self._notify_tray()
                    await self._broadcast_progress()
        elif ev == "end-file":
            reason = msg.get("reason")
            if reason == "eof":
                await self._handle_track_end()
            elif reason == "error":
                self.loading_audio = False
                self.is_playing = False
                await self._broadcast_state()

    async def _handle_track_end(self) -> None:
        dq = self._display_queue()
        if not self.auto_play and self.repeat_mode == "none":
            self.is_playing = False
            await self._broadcast_state()
            return
        if not dq:
            self.is_playing = False
            await self._broadcast_state()
            return

        if self.repeat_mode == "one" and self.current_track:
            await self._load_and_play_track(self.current_track, autoplay=True, resume_pos=0.0)
            return

        next_idx = self.current_index + 1
        if self.repeat_mode == "all":
            next_idx = 0 if next_idx >= len(dq) else next_idx
        elif next_idx >= len(dq):
            self.is_playing = False
            self.progress = 0.0
            await self._broadcast_state()
            return

        self.current_index = next_idx
        await self._load_and_play_track(dq[next_idx], autoplay=True, resume_pos=0.0)

    # ===== Public Control Commands =====

    async def play_track(self, track: dict[str, Any]) -> None:
        self._resync_index()
        await self._load_and_play_track(track, autoplay=True, resume_pos=0.0)

    async def play_now(self, track: dict[str, Any]) -> None:
        tid = track.get("id")
        self.queue = [track] + [t for t in self.queue if t.get("id") != tid]
        self._rebuild_shuffle()
        self.current_index = 0
        await self._load_and_play_track(track, autoplay=True, resume_pos=0.0)

    async def play_next(self, track: dict[str, Any]) -> None:
        if not self.current_track:
            await self.play_now(track)
            return
        tid = track.get("id")
        without = [t for t in self.queue if t.get("id") != tid]
        cur_id = self.current_track.get("id")
        cur_idx = next((i for i, t in enumerate(without) if t.get("id") == cur_id), -1)
        insert_at = cur_idx + 1 if cur_idx >= 0 else len(without)
        self.queue = without[:insert_at] + [track] + without[insert_at:]
        self._rebuild_shuffle()
        self._resync_index()
        await self._broadcast_state()

    async def play_all(self, tracks: list[dict[str, Any]]) -> None:
        if not tracks:
            return
        self.queue = list(tracks)
        self._rebuild_shuffle()
        self.current_index = 0
        await self._load_and_play_track(self.queue[0], autoplay=True, resume_pos=0.0)

    async def play_from_queue(self, index: int) -> None:
        dq = self._display_queue()
        if index < 0 or index >= len(dq):
            return
        self.current_index = index
        await self._load_and_play_track(dq[index], autoplay=True, resume_pos=0.0)

    async def toggle_play(self) -> None:
        if not self.current_track:
            return
        if self.loading_audio:
            return
        # If restored from disk after restart and mpv hasn't loaded the track yet
        if self.duration == 0 and not self.is_playing:
            await self._load_and_play_track(self.current_track, autoplay=True, resume_pos=self.progress)
            return
        if self.is_playing:
            self._mpv.set_pause(True)
            self.is_playing = False
        else:
            # Ensure track is actually loaded in mpv (for restored state)
            if self.progress > 0 and self._load_gen == 0:
                await self._load_and_play_track(self.current_track, autoplay=True, resume_pos=self.progress)
                return
            if self._load_gen == 0:
                await self._load_and_play_track(self.current_track, autoplay=True, resume_pos=self.progress)
                return
            self._mpv.set_pause(False)
            self.is_playing = True
        await self._broadcast_state()

    async def pause(self) -> None:
        self._mpv.set_pause(True)
        self.is_playing = False
        await self._broadcast_state()

    async def next_track(self) -> None:
        dq = self._display_queue()
        if not dq:
            return
        nxt = 0 if (self.current_index + 1 >= len(dq)) else (self.current_index + 1)
        self.current_index = nxt
        await self._load_and_play_track(dq[nxt], autoplay=True, resume_pos=0.0)

    async def prev_track(self) -> None:
        dq = self._display_queue()
        if not dq:
            return
        prv = (len(dq) - 1) if (self.current_index - 1 < 0) else (self.current_index - 1)
        self.current_index = prv
        await self._load_and_play_track(dq[prv], autoplay=True, resume_pos=0.0)

    async def seek(self, seconds: float) -> None:
        pos = max(0.0, float(seconds))
        self.progress = pos
        if self._load_gen > 0:
            self._mpv.seek(pos)
        await self._broadcast_progress()

    async def set_volume(self, vol: float) -> None:
        self.volume = max(0.0, min(100.0, float(vol)))
        self._mpv.set_volume(self.volume)
        await self._broadcast_state()

    async def set_muted(self, muted: bool) -> None:
        self.is_muted = bool(muted)
        self._mpv.set_mute(self.is_muted)
        await self._broadcast_state()

    async def set_repeat_mode(self, mode: str) -> None:
        if mode in ("none", "one", "all"):
            self.repeat_mode = mode
            await self._broadcast_state()

    async def set_shuffled(self, shuffled: bool) -> None:
        self.is_shuffled = bool(shuffled)
        self._rebuild_shuffle()
        self._resync_index()
        await self._broadcast_state()

    async def set_auto_play(self, auto_play: bool) -> None:
        self.auto_play = bool(auto_play)
        await self._broadcast_state()

    async def add_to_queue(self, track: dict[str, Any]) -> bool:
        tid = track.get("id")
        if any(t.get("id") == tid for t in self.queue):
            return False
        self.queue.append(track)
        self._rebuild_shuffle()
        if not self.current_track:
            self.current_index = 0
            await self._load_and_play_track(track, autoplay=True, resume_pos=0.0)
        else:
            await self._broadcast_state()
        return True

    async def add_tracks_to_queue(self, tracks: list[dict[str, Any]]) -> None:
        existing = {t.get("id") for t in self.queue}
        added = [t for t in tracks if t.get("id") not in existing]
        if not added:
            return
        self.queue.extend(added)
        self._rebuild_shuffle()
        if not self.current_track and self.queue:
            self.current_index = 0
            await self._load_and_play_track(self.queue[0], autoplay=True, resume_pos=0.0)
        else:
            await self._broadcast_state()

    async def remove_from_queue(self, track_id: str) -> None:
        self.queue = [t for t in self.queue if t.get("id") != track_id]
        self._rebuild_shuffle()
        self._resync_index()
        await self._broadcast_state()

    async def remove_multiple_from_queue(self, track_ids: list[str]) -> None:
        id_set = set(track_ids)
        self.queue = [t for t in self.queue if t.get("id") not in id_set]
        self._rebuild_shuffle()
        self._resync_index()
        await self._broadcast_state()

    async def move_in_queue(self, from_idx: int, to_idx: int) -> None:
        if (
            from_idx == to_idx
            or from_idx < 0
            or from_idx >= len(self.queue)
            or to_idx < 0
            or to_idx >= len(self.queue)
        ):
            return
        moved = self.queue.pop(from_idx)
        self.queue.insert(to_idx, moved)
        self._rebuild_shuffle()
        self._resync_index()
        await self._broadcast_state()

    async def clear_queue(self) -> None:
        self._load_gen += 1
        self.queue = []
        self._shuffled_queue = []
        self.current_track = None
        self.current_index = -1
        self.is_playing = False
        self.progress = 0.0
        self.duration = 0.0
        self._mpv.stop()
        await self._broadcast_state()

    async def clear_recent(self) -> None:
        self.recent_tracks = []
        await self._broadcast_state()

    async def set_theme(self, theme: str) -> None:
        normalized = "light" if theme == "light" else "dark"
        if normalized != self.theme:
            self.theme = normalized
            await self._broadcast_state()

    async def update_like_state(self, track_id: str, is_liked: bool) -> None:
        if self.current_track and self.current_track.get("id") == track_id:
            self.current_track = {**self.current_track, "isLiked": is_liked}
        self.queue = [
            ({**t, "isLiked": is_liked} if t.get("id") == track_id else t)
            for t in self.queue
        ]
        self._rebuild_shuffle()
        await self._broadcast_state()
