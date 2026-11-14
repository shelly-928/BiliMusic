from __future__ import annotations

import json
from typing import Any, Callable

from aiohttp import WSMsgType, web

from backend.bili_client import BILI_API, BILI_PASSPORT, BiliClient
from backend.config import APP_VERSION, DIST_DIR
from backend.player_engine import PlayerEngine


def create_app(
    bili: BiliClient,
    engine: PlayerEngine,
    on_open_ui: Callable[[], None] | None = None,
    on_quit: Callable[[], None] | None = None,
) -> web.Application:
    app = web.Application()

    async def handle_health(_req: web.Request) -> web.Response:
        return web.json_response({"ok": True, "app": "BiliMusic", "version": APP_VERSION})

    async def handle_open_ui(_req: web.Request) -> web.Response:
        if on_open_ui:
            on_open_ui()
        return web.json_response({"ok": True})

    async def handle_app_quit(_req: web.Request) -> web.Response:
        if on_quit:
            on_quit()
        return web.json_response({"ok": True})

    async def handle_bili_api_proxy(req: web.Request) -> web.Response:
        tail = req.match_info.get("tail", "")
        body = await req.read() if req.can_read_body else None
        status, headers, content = await bili.proxy_request(
            method=req.method,
            base_url=BILI_API,
            path=tail,
            query_string=req.query_string,
            body=body,
            content_type=req.headers.get("Content-Type"),
        )
        return web.Response(status=status, body=content, headers=headers)

    async def handle_bili_passport_proxy(req: web.Request) -> web.Response:
        tail = req.match_info.get("tail", "")
        body = await req.read() if req.can_read_body else None
        status, headers, content = await bili.proxy_request(
            method=req.method,
            base_url=BILI_PASSPORT,
            path=tail,
            query_string=req.query_string,
            body=body,
            content_type=req.headers.get("Content-Type"),
        )
        return web.Response(status=status, body=content, headers=headers)

    async def handle_qr_generate(_req: web.Request) -> web.Response:
        status, _h, content = await bili.proxy_request(
            method="GET",
            base_url=BILI_PASSPORT,
            path="x/passport-login/web/qrcode/generate",
            query_string="",
        )
        data = json.loads(content.decode("utf-8"))
        if status != 200 or data.get("code") != 0:
            return web.json_response({"error": data.get("message", "qrGenerate failed")}, status=400)
        d = data.get("data") or {}
        return web.json_response({"url": d.get("url", ""), "qrcodeKey": d.get("qrcode_key", "")})

    async def handle_qr_poll(req: web.Request) -> web.Response:
        qrcode_key = req.query.get("qrcode_key", "")
        _status, _h, content = await bili.proxy_request(
            method="GET",
            base_url=BILI_PASSPORT,
            path="x/passport-login/web/qrcode/poll",
            query_string=f"qrcode_key={qrcode_key}",
        )
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            return web.json_response({"code": -1, "status": -1, "message": "unknown", "url": ""})
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        code = inner.get("code", data.get("code", -1))
        return web.json_response(
            {
                "code": code,
                "status": code,
                "message": inner.get("message") or data.get("message") or "",
                "url": inner.get("url") or "",
            }
        )

    async def handle_get_cookies(_req: web.Request) -> web.Response:
        return web.json_response(await bili.get_cookies_status())

    async def handle_logout(_req: web.Request) -> web.Response:
        return web.json_response(await bili.logout())

    async def handle_lyrics_search(req: web.Request) -> web.Response:
        kw = req.query.get("keyword", "")
        page = int(req.query.get("page", "1") or 1)
        limit = int(req.query.get("limit", "10") or 10)
        rows = await bili.lyrics_search(kw, page=page, limit=limit)
        return web.json_response(rows)

    async def handle_lyrics_get(req: web.Request) -> web.Response:
        song_id = req.query.get("id", "")
        fmt = req.query.get("format", "lrc")
        data = await bili.lyrics_get(song_id, fmt=fmt)
        return web.json_response(data)

    async def handle_player_state(_req: web.Request) -> web.Response:
        return web.json_response(engine.snapshot())

    async def dispatch_player_action(payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action == "play":
            await engine.play_track(payload["track"])
        elif action == "playNow":
            await engine.play_now(payload["track"])
        elif action == "playNext":
            await engine.play_next(payload["track"])
        elif action == "playAll":
            await engine.play_all(payload.get("tracks") or [])
        elif action == "playFromQueue":
            await engine.play_from_queue(int(payload.get("index", 0)))
        elif action == "togglePlay":
            await engine.toggle_play()
        elif action == "pause":
            await engine.pause()
        elif action == "next":
            await engine.next_track()
        elif action == "prev":
            await engine.prev_track()
        elif action == "seek":
            await engine.seek(float(payload.get("progress", 0)))
        elif action == "setVolume":
            await engine.set_volume(float(payload.get("volume", 80)))
        elif action == "setMuted":
            await engine.set_muted(bool(payload.get("muted", False)))
        elif action == "setRepeatMode":
            await engine.set_repeat_mode(str(payload.get("mode", "none")))
        elif action == "setShuffled":
            await engine.set_shuffled(bool(payload.get("shuffled", False)))
        elif action == "setAutoPlay":
            await engine.set_auto_play(bool(payload.get("autoPlay", True)))
        elif action == "addToQueue":
            added = await engine.add_to_queue(payload["track"])
            return {"ok": True, "added": added}
        elif action == "addTracksToQueue":
            await engine.add_tracks_to_queue(payload.get("tracks") or [])
        elif action == "removeFromQueue":
            await engine.remove_from_queue(str(payload.get("trackId", "")))
        elif action == "removeMultipleFromQueue":
            await engine.remove_multiple_from_queue([str(x) for x in (payload.get("trackIds") or [])])
        elif action == "moveInQueue":
            await engine.move_in_queue(int(payload.get("fromIndex", 0)), int(payload.get("toIndex", 0)))
        elif action == "clearQueue":
            await engine.clear_queue()
        elif action == "clearRecent":
            await engine.clear_recent()
        elif action == "setTheme":
            await engine.set_theme(str(payload.get("theme", "dark")))
        elif action == "updateLikeState":
            await engine.update_like_state(str(payload.get("trackId", "")), bool(payload.get("isLiked", False)))
        return {"ok": True}

    async def handle_player_action(req: web.Request) -> web.Response:
        payload = await req.json()
        res = await dispatch_player_action(payload)
        return web.json_response(res)

    async def handle_ws(req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(req)
        engine.register_ws(ws)
        try:
            await ws.send_str(json.dumps({"type": "state", "data": engine.snapshot()}, ensure_ascii=False))
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        if isinstance(payload, dict) and payload.get("action"):
                            await dispatch_player_action(payload)
                    except Exception:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            engine.unregister_ws(ws)
        return ws

    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/ui/open", handle_open_ui)
    app.router.add_post("/api/app/quit", handle_app_quit)
    app.router.add_route("*", "/bili-api/{tail:.*}", handle_bili_api_proxy)
    app.router.add_route("*", "/bili-passport/{tail:.*}", handle_bili_passport_proxy)
    app.router.add_get("/api/bili/qr-generate", handle_qr_generate)
    app.router.add_get("/api/bili/qr-poll", handle_qr_poll)
    app.router.add_get("/api/bili/cookies", handle_get_cookies)
    app.router.add_post("/api/bili/logout", handle_logout)
    app.router.add_get("/api/lyrics/search", handle_lyrics_search)
    app.router.add_get("/api/lyrics/get", handle_lyrics_get)
    app.router.add_get("/api/player/state", handle_player_state)
    app.router.add_post("/api/player/action", handle_player_action)
    app.router.add_get("/ws", handle_ws)

    # Static frontend serving from dist/
    if DIST_DIR.exists():
        assets_dir = DIST_DIR / "assets"
        if assets_dir.exists():
            app.router.add_static("/assets/", assets_dir)

        async def handle_spa(_req: web.Request) -> web.FileResponse:
            return web.FileResponse(DIST_DIR / "index.html")

        app.router.add_get("/", handle_spa)
        app.router.add_get("/{path:.*}", handle_spa)

    return app
