from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession

from backend.config import COOKIES_FILE, DATA_DIR

BILI_API = "https://api.bilibili.com"
BILI_PASSPORT = "https://passport.bilibili.com"
BILI_REFERER = "https://www.bilibili.com"
OIAPI_QQ_LYRIC = "https://www.oiapi.net/api/QQMusicLyric"


class BiliClient:
    """Bilibili & lyrics HTTP client with Chrome TLS impersonation and cookie persistence."""

    def __init__(self) -> None:
        self._cookies: dict[str, str] = self._load_cookies()
        self._lock = asyncio.Lock()
        self._session: AsyncSession | None = None

    def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome", timeout=15)
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _load_cookies(self) -> dict[str, str]:
        try:
            if COOKIES_FILE.exists():
                data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
        except Exception:
            pass
        return {}

    def _save_cookies(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            COOKIES_FILE.write_text(
                json.dumps(self._cookies, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items() if v)

    def _absorb_response_cookies(self, resp: Any) -> bool:
        changed = False
        # Parse raw Set-Cookie headers to capture HttpOnly cookies cleanly.
        raw_headers = []
        if hasattr(resp.headers, "get_list"):
            raw_headers = resp.headers.get_list("set-cookie")
        elif hasattr(resp.headers, "multi_items"):
            raw_headers = [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]
        else:
            val = resp.headers.get("set-cookie")
            if val:
                raw_headers = [val]

        for line in raw_headers:
            pair = line.split(";", 1)[0].strip()
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name, value = name.strip(), value.strip()
            if name and self._cookies.get(name) != value:
                self._cookies[name] = value
                changed = True

        try:
            for name, value in resp.cookies.items():
                if name and value and self._cookies.get(name) != value:
                    self._cookies[name] = str(value)
                    changed = True
        except Exception:
            pass

        if changed:
            self._save_cookies()
        return changed

    async def ensure_buvid(self) -> None:
        if "buvid3" in self._cookies and "buvid4" in self._cookies:
            return
        async with self._lock:
            if "buvid3" in self._cookies and "buvid4" in self._cookies:
                return
            try:
                session = self._get_session()
                resp = await session.get(
                    f"{BILI_API}/x/frontend/finger/spi",
                    headers={"Referer": BILI_REFERER, "Origin": BILI_REFERER},
                    cookies=self._cookies,
                )
                self._absorb_response_cookies(resp)
                payload = resp.json()
                data = payload.get("data") or {}
                b3 = data.get("b_3")
                b4 = data.get("b_4")
                changed = False
                if b3 and "buvid3" not in self._cookies:
                    self._cookies["buvid3"] = str(b3)
                    changed = True
                if b4 and "buvid4" not in self._cookies:
                    self._cookies["buvid4"] = str(b4)
                    changed = True
                if changed:
                    self._save_cookies()
            except Exception:
                pass

    async def get_cookies_status(self) -> dict[str, Any]:
        sessdata = self._cookies.get("SESSDATA", "")
        bili_jct = self._cookies.get("bili_jct", "")
        dede_uid = self._cookies.get("DedeUserID", "")
        return {
            "isLoggedIn": bool(sessdata and bili_jct and dede_uid),
            "sessdata": sessdata,
            "biliJct": bili_jct,
            "dedeUserId": dede_uid,
        }

    async def logout(self) -> dict[str, bool]:
        for key in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"):
            self._cookies.pop(key, None)
        self._save_cookies()
        return {"success": True}

    async def proxy_request(
        self,
        method: str,
        base_url: str,
        path: str,
        query_string: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        await self.ensure_buvid()
        target_url = f"{base_url}/{path.lstrip('/')}"
        if query_string:
            target_url = f"{target_url}?{query_string}"

        is_passport = base_url == BILI_PASSPORT
        headers = {
            "Referer": f"{BILI_PASSPORT}/login" if is_passport else BILI_REFERER,
            "Origin": BILI_PASSPORT if is_passport else BILI_REFERER,
        }
        if content_type:
            headers["Content-Type"] = content_type
        cookie_str = self._cookie_header()
        if cookie_str:
            headers["Cookie"] = cookie_str

        is_qr_poll = "qrcode/poll" in path
        session = self._get_session()
        resp = await session.request(
            method=method,
            url=target_url,
            headers=headers,
            data=body if body else None,
            allow_redirects=not is_qr_poll,
        )
        self._absorb_response_cookies(resp)

        if is_qr_poll and resp.status_code in (301, 302):
            location = resp.headers.get("location", "")
            normalized = json.dumps(
                {
                    "code": 0,
                    "data": {
                        "code": 0,
                        "status": 0,
                        "message": "登录成功",
                        "url": location,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")
            return 200, {"Content-Type": "application/json; charset=utf-8"}, normalized

        resp_ct = resp.headers.get("content-type", "application/json; charset=utf-8")
        return resp.status_code, {"Content-Type": resp_ct}, resp.content

    async def fetch_bili_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.ensure_buvid()
        url = f"{BILI_API}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        headers = {"Referer": BILI_REFERER, "Origin": BILI_REFERER}
        cookie_str = self._cookie_header()
        if cookie_str:
            headers["Cookie"] = cookie_str
        resp = await self._get_session().get(url, headers=headers)
        self._absorb_response_cookies(resp)
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Bili API error [{payload.get('code')}]: {payload.get('message')}")
        return payload.get("data") or {}

    async def extract_audio(
        self,
        bvid: str,
        aid: str | int | None = None,
        cid: str | int | None = None,
    ) -> dict[str, Any]:
        try:
            if not bvid:
                raise ValueError("Missing bvid")
            detail = await self.fetch_bili_json("/x/web-interface/view", {"bvid": bvid})
            play_data = await self.fetch_bili_json(
                "/x/player/playurl",
                {"bvid": bvid, "cid": detail["cid"], "qn": 0, "fnver": 0, "fnval": 16, "fourk": 1},
            )
            audio_streams = (play_data.get("dash") or {}).get("audio") or []
            if not audio_streams:
                raise RuntimeError("No audio stream available")
            best = max(audio_streams, key=lambda s: s.get("bandwidth", 0))
            pic = str(detail.get("pic") or "")
            if pic.startswith("//"):
                pic = f"https:{pic}"
            elif pic.startswith("http://"):
                pic = f"https://{pic[7:]}"
            return {
                "bvid": detail.get("bvid", bvid),
                "aid": detail.get("aid", 0),
                "cid": detail.get("cid", 0),
                "title": detail.get("title", ""),
                "artist": (detail.get("owner") or {}).get("name", ""),
                "coverUrl": pic,
                "duration": detail.get("duration", 0),
                "audioUrl": best["baseUrl"],
                "audioQuality": best.get("quality", 0),
                "audioMimeType": best.get("mimeType", ""),
            }
        except Exception:
            if aid and cid:
                play_data = await self.fetch_bili_json(
                    "/x/player/playurl",
                    {"avid": aid, "cid": cid, "qn": 0, "fnver": 0, "fnval": 16, "fourk": 1},
                )
                audio_streams = (play_data.get("dash") or {}).get("audio") or []
                if not audio_streams:
                    raise RuntimeError("No audio stream available")
                best = max(audio_streams, key=lambda s: s.get("bandwidth", 0))
                return {
                    "bvid": bvid,
                    "aid": int(aid) if str(aid).isdigit() else 0,
                    "cid": int(cid) if str(cid).isdigit() else 0,
                    "title": "",
                    "artist": "",
                    "coverUrl": "",
                    "duration": 0,
                    "audioUrl": best["baseUrl"],
                    "audioQuality": best.get("quality", 0),
                    "audioMimeType": best.get("mimeType", ""),
                }
            raise

    async def lyrics_search(self, keyword: str, page: int = 1, limit: int = 10) -> list[dict[str, Any]]:
        q = keyword.strip()
        if not q:
            return []
        url = f"{OIAPI_QQ_LYRIC}?{urlencode({'keyword': q, 'page': page, 'limit': limit, 'type': 'json'})}"
        try:
            resp = await self._get_session().get(url, timeout=9)
            if resp.status_code != 200:
                return []
            data = resp.json().get("data")
            if not isinstance(data, list):
                return []
            return [item for item in data if isinstance(item, dict) and isinstance(item.get("name"), str)]
        except Exception:
            return []

    async def lyrics_get(self, song_id: str | int, fmt: str = "lrc") -> dict[str, Any] | None:
        sid = str(song_id or "").strip()
        if not sid:
            return None
        url = f"{OIAPI_QQ_LYRIC}?{urlencode({'id': sid, 'format': fmt, 'type': 'json'})}"
        try:
            resp = await self._get_session().get(url, timeout=9)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if not isinstance(payload, dict) or payload.get("code") != 1:
                return None
            data = payload.get("data")
            if isinstance(data, str):
                return {"content": data}
            if isinstance(data, dict):
                return data
            msg = payload.get("message")
            if isinstance(msg, str) and "[" in msg:
                return {"content": msg}
            return None
        except Exception:
            return None
