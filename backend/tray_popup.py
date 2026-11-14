from __future__ import annotations

from collections import OrderedDict
import ctypes
from ctypes import wintypes
from io import BytesIO
import os
import threading
import time
from typing import Any, Callable
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

WM_DESTROY = 0x0002
WM_ACTIVATE = 0x0006
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSELEAVE = 0x02A3
WM_APP_TOGGLE = 0x8001
WM_APP_REFRESH = 0x8002
WM_APP_CLOSE = 0x8003

WA_INACTIVE = 0
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000

HWND_TOPMOST = wintypes.HWND(-1)
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
TME_LEAVE = 0x00000002
IDC_ARROW = 32512
IDC_HAND = 32649

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

PANEL_W = 330
PANEL_H = 288
SHADOW_PAD = 12
WIN_W = PANEL_W + SHADOW_PAD * 2
WIN_H = PANEL_H + SHADOW_PAD * 2

ANIM_TIMER_ID = 1
ANIM_TICK_MS = 15
SHOW_DURATION_S = 0.36
HIDE_DURATION_S = 0.19


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.TrackMouseEvent.restype = wintypes.BOOL
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HICON
user32.SetCursor.argtypes = [wintypes.HICON]
user32.SetCursor.restype = wintypes.HICON
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
if hasattr(user32, "SetThreadDpiAwarenessContext"):
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

if hasattr(shcore, "GetDpiForMonitor"):
    shcore.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    ]
    shcore.GetDpiForMonitor.restype = ctypes.c_long

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL


def _ease_out_cubic(t: float) -> float:
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 1.0 - (1.0 - t) ** 3.2


def _normalize_cover_url(raw: str) -> str:
    url = (raw or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url[7:]}"
    return url


def _load_font(bold: bool, px_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates = (
        ["msyhbd.ttc", "msyh.ttc", "simhei.ttf", "segoeui.ttf"]
        if bold
        else ["msyh.ttc", "msyhl.ttc", "simhei.ttf", "segoeui.ttf"]
    )
    for name in candidates:
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, max(8, px_size))
            except Exception:
                continue
    return ImageFont.load_default()


def _truncate_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_w: int) -> str:
    if not text:
        return ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ellipsis = "..."
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + ellipsis, font=font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ellipsis) if lo > 0 else ellipsis


def _rounded_mask(w: int, h: int, radius: int, aa: int = 3) -> Image.Image:
    mask = Image.new("L", (w * aa, h * aa), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, w * aa - 1, h * aa - 1), radius=radius * aa, fill=255)
    return mask.resize((w, h), Image.Resampling.LANCZOS)


def _draw_linear_gradient(w: int, h: int, top_rgba: tuple[int, ...], bot_rgba: tuple[int, ...]) -> Image.Image:
    strip = Image.new("RGBA", (1, h))
    px = strip.load()
    denom = max(1, h - 1)
    for y in range(h):
        t = y / denom
        px[0, y] = tuple(int(round(top_rgba[i] + (bot_rgba[i] - top_rgba[i]) * t)) for i in range(4))
    return strip.resize((w, h), Image.Resampling.NEAREST)


def _draw_vector_icon(kind: str, size: int, color: tuple[int, int, int, int]) -> Image.Image:
    """Render anti-aliased playback/note vector icon at 3x supersampling."""
    aa = 3
    s = size * aa
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def pt(nx: float, ny: float) -> tuple[float, float]:
        return (nx * s / 24.0, ny * s / 24.0)

    if kind == "note":
        # Classic music note matching Material SVG path
        d.ellipse((pt(6, 13.5), pt(14, 21.0)), fill=color)
        d.rectangle((pt(12, 3), pt(14.3, 17.2)), fill=color)
        d.rectangle((pt(12, 3), pt(18.5, 7)), fill=color)
    elif kind == "prev":
        d.rectangle((pt(5.5, 5.8), pt(7.8, 18.2)), fill=color)
        d.polygon([pt(18.2, 5.8), pt(18.2, 18.2), pt(9.5, 12.0)], fill=color)
    elif kind == "next":
        d.polygon([pt(5.8, 5.8), pt(14.5, 12.0), pt(5.8, 18.2)], fill=color)
        d.rectangle((pt(16.2, 5.8), pt(18.5, 18.2)), fill=color)
    elif kind == "play":
        d.polygon([pt(8.0, 5.2), pt(19.0, 12.0), pt(8.0, 18.8)], fill=color)
    elif kind == "pause":
        d.rectangle((pt(6.2, 5.2), pt(10.0, 18.8)), fill=color)
        d.rectangle((pt(14.0, 5.2), pt(17.8, 18.8)), fill=color)

    return img.resize((size, size), Image.Resampling.LANCZOS)


class _TrayRenderer:
    """Renders high-DPI native popup frames and caches background/covers."""

    def __init__(self) -> None:
        self._base_cache: dict[tuple[str, float], Image.Image] = {}
        self._font_cache: dict[tuple[bool, int], Any] = {}
        self._icon_cache: dict[tuple[str, int, tuple[int, int, int, int]], Image.Image] = {}
        self._cover_cache: OrderedDict[tuple[str, int], Image.Image] = OrderedDict()

    def _font(self, bold: bool, px: int) -> Any:
        key = (bold, px)
        if key not in self._font_cache:
            self._font_cache[key] = _load_font(bold, px)
        return self._font_cache[key]

    def _icon(self, kind: str, px: int, color: tuple[int, int, int, int]) -> Image.Image:
        key = (kind, px, color)
        if key not in self._icon_cache:
            self._icon_cache[key] = _draw_vector_icon(kind, px, color)
        return self._icon_cache[key]

    def get_cached_cover(self, url: str, box_px: int) -> Image.Image | None:
        return self._cover_cache.get((url, box_px))

    def store_cover(self, url: str, box_px: int, raw_bytes: bytes, radius_px: int) -> Image.Image | None:
        try:
            with Image.open(BytesIO(raw_bytes)) as src:
                img = src.convert("RGBA")
        except Exception:
            return None

        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        cropped = img.crop((left, top, left + side, top + side)).resize(
            (box_px, box_px), Image.Resampling.LANCZOS
        )
        rounded = Image.new("RGBA", (box_px, box_px), (0, 0, 0, 0))
        rounded.paste(cropped, (0, 0), _rounded_mask(box_px, box_px, radius_px))
        key = (url, box_px)
        self._cover_cache[key] = rounded
        self._cover_cache.move_to_end(key)
        while len(self._cover_cache) > 16:
            self._cover_cache.popitem(last=False)
        return rounded

    def _base_panel(self, theme: str, scale: float) -> Image.Image:
        key = (theme, round(scale, 3))
        cached = self._base_cache.get(key)
        if cached is not None:
            return cached.copy()

        ww = round(WIN_W * scale)
        wh = round(WIN_H * scale)
        pad = round(SHADOW_PAD * scale)
        pw = round(PANEL_W * scale)
        ph = round(PANEL_H * scale)
        radius = round(16 * scale)

        canvas = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))

        # Soft drop shadow
        shadow = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        shadow_alpha = 115 if theme != "light" else 52
        sd.rounded_rectangle(
            (pad, pad + round(2 * scale), pad + pw - 1, pad + ph + round(3 * scale)),
            radius=radius,
            fill=(0, 0, 0, shadow_alpha),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, round(5 * scale))))
        canvas = Image.alpha_composite(canvas, shadow)

        if theme == "light":
            top_bg = (252, 252, 253, 252)
            bot_bg = (244, 245, 248, 254)
            border_c = (24, 25, 28, 28)
            now_bg = (24, 25, 28, 10)
            now_border = (24, 25, 28, 18)
            div_c = (24, 25, 28, 22)
        else:
            top_bg = (38, 38, 42, 250)
            bot_bg = (20, 20, 23, 252)
            border_c = (255, 255, 255, 28)
            now_bg = (255, 255, 255, 19)
            now_border = (255, 255, 255, 20)
            div_c = (255, 255, 255, 26)

        panel_grad = _draw_linear_gradient(pw, ph, top_bg, bot_bg)
        panel_mask = _rounded_mask(pw, ph, radius)
        panel_layer = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
        panel_layer.paste(panel_grad, (pad, pad), panel_mask)
        canvas = Image.alpha_composite(canvas, panel_layer)

        # Panel outline + inner now card + divider (anti-aliased at 2x to prevent rough corners)
        aa = 2
        ow, oh = ww * aa, wh * aa
        overlay = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        bw = max(1, round(1 * scale * aa))
        p_aa = pad * aa
        pw_aa, ph_aa = pw * aa, ph * aa
        od.rounded_rectangle(
            (p_aa, p_aa, p_aa + pw_aa - 1, p_aa + ph_aa - 1),
            radius=radius * aa,
            outline=border_c,
            width=bw,
        )

        nx0 = p_aa + round(14 * scale * aa)
        ny0 = p_aa + round(14 * scale * aa)
        nx1 = p_aa + round(316 * scale * aa)
        ny1 = p_aa + round(90 * scale * aa)
        od.rounded_rectangle(
            (nx0, ny0, nx1, ny1),
            radius=round(14 * scale * aa),
            fill=now_bg,
            outline=now_border,
            width=bw,
        )

        div_y = p_aa + round(176 * scale * aa)
        od.line((nx0, div_y, nx1, div_y), fill=div_c, width=bw)

        canvas = Image.alpha_composite(canvas, overlay.resize((ww, wh), Image.Resampling.LANCZOS))
        self._base_cache[key] = canvas
        return canvas.copy()

    def render(self, state: dict[str, Any], hover_id: str | None, scale: float) -> Image.Image:
        theme = "light" if state.get("theme") == "light" else "dark"
        canvas = self._base_panel(theme, scale)
        pad = round(SHADOW_PAD * scale)

        if theme == "light":
            text_c = (24, 25, 28, 255)
            sub_c = (24, 25, 28, 138)
            status_c = (24, 25, 28, 133)
            btn_bg = (24, 25, 28, 16)
            btn_hover = (24, 25, 28, 28)
            btn_text = (24, 25, 28, 255)
            row_text = (24, 25, 28, 220)
            row_hover = (24, 25, 28, 16)
            count_c = (24, 25, 28, 115)
            fallback_icon_c = (24, 25, 28, 128)
        else:
            text_c = (247, 247, 248, 255)
            sub_c = (255, 255, 255, 132)
            status_c = (255, 255, 255, 125)
            btn_bg = (255, 255, 255, 26)
            btn_hover = (255, 255, 255, 42)
            btn_text = (255, 255, 255, 255)
            row_text = (255, 255, 255, 220)
            row_hover = (255, 255, 255, 26)
            count_c = (255, 255, 255, 110)
            fallback_icon_c = (255, 255, 255, 158)

        # Cover box (56x56 at 24,24)
        cx = pad + round(24 * scale)
        cy = pad + round(24 * scale)
        csize = round(56 * scale)
        crad = round(12 * scale)
        cover_url = _normalize_cover_url(str(state.get("cover") or ""))
        cover_img = self.get_cached_cover(cover_url, csize) if cover_url else None
        if cover_img is not None:
            canvas.alpha_composite(cover_img, (cx, cy))
        else:
            fallback_bg = _draw_linear_gradient(csize, csize, (255, 55, 95, 108), (255, 255, 255, 22))
            f_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            f_layer.paste(fallback_bg, (cx, cy), _rounded_mask(csize, csize, crad))
            canvas = Image.alpha_composite(canvas, f_layer)
            note_px = round(22 * scale)
            note_icon = self._icon("note", note_px, fallback_icon_c)
            canvas.alpha_composite(note_icon, (cx + (csize - note_px) // 2, cy + (csize - note_px) // 2))

        has_track = bool(state.get("hasTrack"))
        is_playing = bool(state.get("isPlaying"))
        title = str(state.get("title") or "未在播放")
        artist = str(state.get("artist") or "搜索并播放音乐")
        queue_count = int(state.get("queueCount") or 0)

        font_title = self._font(True, round(14 * scale))
        font_artist = self._font(False, round(12 * scale))
        font_status = self._font(True, round(11 * scale))
        font_row = self._font(True, round(13 * scale))
        font_count = self._font(False, round(12 * scale))

        # Render text & shapes on a separate RGBA overlay and alpha_composite cleanly
        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(txt_layer)

        tx = pad + round(92 * scale)
        max_tw = round(214 * scale)
        d.text((tx, pad + round(31 * scale)), _truncate_text(d, title, font_title, max_tw), font=font_title, fill=text_c)
        d.text((tx, pad + round(54 * scale)), _truncate_text(d, artist, font_artist, max_tw), font=font_artist, fill=sub_c)

        # Status dot + text
        dot_x = pad + round(16 * scale)
        dot_y = pad + round(104 * scale)
        dot_d = round(7 * scale)
        if is_playing:
            glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            gd.ellipse(
                (dot_x - round(2 * scale), dot_y - round(2 * scale), dot_x + dot_d + round(2 * scale), dot_y + dot_d + round(2 * scale)),
                fill=(48, 209, 88, 120),
            )
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=max(1, round(2 * scale))))
            canvas = Image.alpha_composite(canvas, glow_layer)
            dot_c = (48, 209, 88, 255)
            status_txt = "正在播放"
        else:
            dot_c = (142, 142, 147, 255)
            status_txt = "已暂停" if has_track else "空闲"

        d.ellipse((dot_x, dot_y, dot_x + dot_d, dot_y + dot_d), fill=dot_c)
        d.text((dot_x + dot_d + round(6 * scale), pad + round(99 * scale)), status_txt, font=font_status, fill=status_c)

        # Control buttons: prev, play, next (using AA rounded mask for crisp pill edges)
        rects = self.button_rects(scale, pad)
        for btn_id in ("prev", "play", "next"):
            rx0, ry0, rx1, ry1 = rects[btn_id]
            rw, rh = rx1 - rx0, ry1 - ry0
            rrad = rh // 2
            hovered = hover_id == btn_id and has_track
            if btn_id == "play":
                fill_c = (255, 69, 106, 255) if hovered else (255, 55, 95, 255)
                icon_c = (255, 255, 255, 255)
                icon_kind = "pause" if is_playing else "play"
                icon_px = round(18 * scale)
                if has_track:
                    p_glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                    pgd = ImageDraw.Draw(p_glow)
                    pgd.rounded_rectangle((rx0, ry0 + round(2 * scale), rx1, ry1 + round(4 * scale)), radius=rrad, fill=(255, 55, 95, 64))
                    p_glow = p_glow.filter(ImageFilter.GaussianBlur(radius=max(2, round(5 * scale))))
                    canvas = Image.alpha_composite(canvas, p_glow)
            else:
                fill_c = btn_hover if hovered else btn_bg
                icon_c = btn_text
                icon_kind = btn_id
                icon_px = round(16 * scale)

            if not has_track:
                fill_c = (fill_c[0], fill_c[1], fill_c[2], max(8, int(fill_c[3] * 0.42)))
                icon_c = (icon_c[0], icon_c[1], icon_c[2], int(icon_c[3] * 0.42))

            btn_patch = Image.new("RGBA", (rw, rh), fill_c)
            btn_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            btn_layer.paste(btn_patch, (rx0, ry0), _rounded_mask(rw, rh, rrad))
            canvas = Image.alpha_composite(canvas, btn_layer)

            ic = self._icon(icon_kind, icon_px, icon_c)
            canvas.alpha_composite(ic, (rx0 + (rw - icon_px) // 2, ry0 + (rh - icon_px) // 2))

        # Action rows
        for row_id, label, right_txt, l_color in (
            ("show", "显示 BiliMusic", f"{queue_count} 首", row_text),
            ("quit", "退出应用", "Ctrl+Q", (255, 105, 97, 255)),
        ):
            rx0, ry0, rx1, ry1 = rects[row_id]
            rw, rh = rx1 - rx0, ry1 - ry0
            if hover_id == row_id:
                row_patch = Image.new("RGBA", (rw, rh), row_hover)
                row_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                row_layer.paste(row_patch, (rx0, ry0), _rounded_mask(rw, rh, round(10 * scale)))
                canvas = Image.alpha_composite(canvas, row_layer)
            text_y = ry0 + round(10 * scale)
            d.text((rx0 + round(12 * scale), text_y), label, font=font_row, fill=l_color)
            rw_txt = d.textlength(right_txt, font=font_count)
            d.text((rx1 - round(12 * scale) - rw_txt, text_y + round(1 * scale)), right_txt, font=font_count, fill=count_c)

        canvas = Image.alpha_composite(canvas, txt_layer)
        return canvas

    @staticmethod
    def button_rects(scale: float, pad: int) -> dict[str, tuple[int, int, int, int]]:
        gap = round(10 * scale)
        left_x = pad + round(16 * scale)
        total_w = round(298 * scale)
        avail = total_w - 2 * gap
        side_w = round(avail / 3.25)
        mid_w = avail - 2 * side_w
        cy0 = pad + round(124 * scale)
        cy1 = cy0 + round(40 * scale)
        x_play = left_x + side_w + gap
        x_next = x_play + mid_w + gap

        ax0 = pad + round(14 * scale)
        ax1 = pad + round(316 * scale)
        s0 = pad + round(188 * scale)
        q0 = pad + round(228 * scale)
        rh = round(36 * scale)
        return {
            "prev": (left_x, cy0, left_x + side_w, cy1),
            "play": (x_play, cy0, x_play + mid_w, cy1),
            "next": (x_next, cy0, x_next + side_w, cy1),
            "show": (ax0, s0, ax1, s0 + rh),
            "quit": (ax0, q0, ax1, q0 + rh),
        }


class NativeTrayPopup:
    """Native Win32 layered tray popup window rendered with Pillow.

    Lives in a dedicated Win32 message thread with zero Chromium/CLR overhead,
    zero taskbar presence, instant first-click display, and smooth animation.
    """

    def __init__(
        self,
        get_state: Callable[[], dict[str, Any]],
        on_action: Callable[[str], None],
        on_open_ui: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._get_state = get_state
        self._on_action = on_action
        self._on_open_ui = on_open_ui
        self._on_quit = on_quit

        self._renderer = _TrayRenderer()
        self._hwnd: wintypes.HWND | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._wndproc_ref: WNDPROC | None = None
        self._class_name = f"BiliMusicNativeTray_{id(self)}"

        self._lock = threading.Lock()
        self._pending_pos: tuple[int, int] | None = None
        self._hover_id: str | None = None
        self._visible = False
        self._last_hidden_at = 0.0
        self._last_cover_fetched = ""
        self._fetching_covers: set[str] = set()

        self._scale = 1.0
        self._target_x = 0
        self._target_y = 0
        self._start_y = 0
        self._end_y = 0
        self._direction = 1
        self._anim_mode: str | None = None  # "show" | "hide" | None
        self._anim_start = 0.0
        self._cached_frame: Image.Image | None = None
        self._tracking_leave = False
        self._pressed_id: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._ui_loop, name="TrayPopupThread", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def toggle_at(self, px: int, py: int) -> None:
        if self._hwnd is None:
            return
        with self._lock:
            self._pending_pos = (px, py)
        user32.PostMessageW(self._hwnd, WM_APP_TOGGLE, 0, 0)

    def notify_state_changed(self) -> None:
        if self._hwnd is not None and self._visible:
            user32.PostMessageW(self._hwnd, WM_APP_REFRESH, 0, 0)

    def close(self) -> None:
        hwnd = self._hwnd
        if hwnd is not None:
            user32.PostMessageW(hwnd, WM_APP_CLOSE, 0, 0)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _ui_loop(self) -> None:
        if hasattr(user32, "SetThreadDpiAwarenessContext"):
            try:
                user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            except Exception:
                pass

        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = self._class_name
        user32.RegisterClassExW(ctypes.byref(wc))

        ex_style = WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TOPMOST
        self._hwnd = user32.CreateWindowExW(
            ex_style,
            self._class_name,
            "BiliMusic Tray",
            WS_POPUP,
            0,
            0,
            WIN_W,
            WIN_H,
            None,
            None,
            hinst,
            None,
        )
        self._ready.set()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        try:
            user32.UnregisterClassW(self._class_name, hinst)
        except Exception:
            pass
        self._hwnd = None

    def _wndproc(self, hwnd: wintypes.HWND, msg: int, wparam: WPARAM, lparam: LPARAM) -> LRESULT:
        if msg == WM_APP_TOGGLE:
            with self._lock:
                pos = self._pending_pos
            if pos is not None:
                self._handle_toggle(pos[0], pos[1])
            return 0
        if msg == WM_APP_REFRESH:
            if self._visible:
                self._refresh_bitmap()
                if not self._anim_mode:
                    self._commit_frame(self._target_x, self._target_y, 1.0, 1.0)
            return 0
        if msg == WM_APP_CLOSE:
            user32.KillTimer(hwnd, ANIM_TIMER_ID)
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_TIMER and wparam == ANIM_TIMER_ID:
            self._on_anim_tick()
            return 0
        if msg == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE and self._visible and self._anim_mode != "hide":
                self._start_hide()
            return 0
        if msg == WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            self._on_mouse_move(x, y)
            return 0
        if msg == WM_MOUSELEAVE:
            self._tracking_leave = False
            self._pressed_id = None
            if self._hover_id is not None:
                self._hover_id = None
                if self._visible:
                    self._refresh_bitmap()
                    if not self._anim_mode:
                        self._commit_frame(self._target_x, self._target_y, 1.0, 1.0)
            return 0
        if msg == WM_LBUTTONDOWN:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            self._pressed_id = self._hit_test(x, y)
            return 0
        if msg == WM_LBUTTONUP:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            hit = self._hit_test(x, y)
            pressed = self._pressed_id
            self._pressed_id = None
            if hit and hit == pressed:
                self._trigger_action(hit)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _get_work_area(self, px: int, py: int) -> tuple[RECT, float]:
        pt = POINT(px, py)
        hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        dpi_x = wintypes.UINT(96)
        dpi_y = wintypes.UINT(96)
        if hmon:
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            if hasattr(shcore, "GetDpiForMonitor"):
                try:
                    shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                except Exception:
                    pass
        else:
            mi.rcWork = RECT(0, 0, 1920, 1040)
            mi.rcMonitor = RECT(0, 0, 1920, 1080)
        scale = max(1.0, float(dpi_x.value or 96) / 96.0)
        return mi.rcWork, scale

    def _compute_origin(self, px: int, py: int) -> tuple[int, int, float, int]:
        wa, scale = self._get_work_area(px, py)
        pad = round(SHADOW_PAD * scale)
        pw = round(PANEL_W * scale)
        ph = round(PANEL_H * scale)
        gap = round(10 * scale)

        x = px - pw // 2
        if py > wa.bottom - 140:
            y = wa.bottom - ph - gap
            direction = 1
        elif py > (wa.top + wa.bottom) // 2:
            y = py - ph - gap
            direction = 1
        else:
            y = max(wa.top + gap, py + gap)
            direction = -1

        min_x = wa.left + gap
        max_x = max(min_x, wa.right - pw - gap)
        min_y = wa.top + gap
        max_y = max(min_y, wa.bottom - ph - gap)
        x = max(min_x, min(max_x, x))
        y = max(min_y, min(max_y, y))
        return x - pad, y - pad, scale, direction

    def _handle_toggle(self, px: int, py: int) -> None:
        if self._visible and self._anim_mode != "hide":
            self._start_hide()
            return
        if (time.monotonic() - self._last_hidden_at) < 0.25:
            return
        self._start_show(px, py)

    def _start_show(self, px: int, py: int) -> None:
        hwnd = self._hwnd
        if hwnd is None:
            return
        wx, wy, scale, direction = self._compute_origin(px, py)
        self._scale = scale
        self._target_x = wx
        self._end_y = wy
        self._target_y = wy
        self._direction = direction
        self._start_y = wy + round(26 * scale * direction)
        self._hover_id = None
        self._pressed_id = None
        self._visible = True
        self._anim_mode = "show"
        self._anim_start = time.monotonic()

        self._refresh_bitmap()
        self._commit_frame(self._target_x, self._start_y, 0.90, 0.05)
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(hwnd)
        user32.SetTimer(hwnd, ANIM_TIMER_ID, ANIM_TICK_MS, None)

    def _start_hide(self) -> None:
        hwnd = self._hwnd
        if hwnd is None:
            return
        if self._visible:
            self._visible = False
            self._last_hidden_at = time.monotonic()
        self._anim_mode = "hide"
        self._anim_start = time.monotonic()
        self._start_y = self._target_y
        self._end_y = self._target_y + round(12 * self._scale * self._direction)
        user32.SetTimer(hwnd, ANIM_TIMER_ID, ANIM_TICK_MS, None)

    def _on_anim_tick(self) -> None:
        hwnd = self._hwnd
        if hwnd is None or not self._anim_mode:
            return
        elapsed = time.monotonic() - self._anim_start
        if self._anim_mode == "show":
            t = min(1.0, elapsed / SHOW_DURATION_S)
            e = _ease_out_cubic(t)
            cy = round(self._start_y + (self._end_y - self._start_y) * e)
            scale_f = 0.90 + 0.10 * e
            alpha_f = e
            self._commit_frame(self._target_x, cy, scale_f, alpha_f)
            if t >= 1.0:
                self._anim_mode = None
                user32.KillTimer(hwnd, ANIM_TIMER_ID)
        elif self._anim_mode == "hide":
            t = min(1.0, elapsed / HIDE_DURATION_S)
            e = _ease_out_cubic(t)
            cy = round(self._start_y + (self._end_y - self._start_y) * e)
            scale_f = 1.0 - 0.06 * e
            alpha_f = max(0.0, 1.0 - t)
            self._commit_frame(self._target_x, cy, scale_f, alpha_f)
            if t >= 1.0:
                self._anim_mode = None
                user32.KillTimer(hwnd, ANIM_TIMER_ID)
                user32.ShowWindow(hwnd, SW_HIDE)

    def _ensure_cover(self, state: dict[str, Any]) -> None:
        url = _normalize_cover_url(str(state.get("cover") or ""))
        if not url:
            return
        box_px = round(56 * self._scale)
        if self._renderer.get_cached_cover(url, box_px) is not None:
            return
        with self._lock:
            if url in self._fetching_covers:
                return
            self._fetching_covers.add(url)

        def _worker() -> None:
            try:
                req = Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.bilibili.com",
                    },
                )
                with urlopen(req, timeout=5) as resp:
                    raw = resp.read()
                img = self._renderer.store_cover(url, box_px, raw, round(12 * self._scale))
                if img is not None and self._hwnd is not None and self._visible:
                    user32.PostMessageW(self._hwnd, WM_APP_REFRESH, 0, 0)
            except Exception:
                pass
            finally:
                with self._lock:
                    self._fetching_covers.discard(url)

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_bitmap(self) -> None:
        state = self._get_state()
        self._ensure_cover(state)
        self._cached_frame = self._renderer.render(state, self._hover_id, self._scale)

    def _commit_frame(self, wx: int, wy: int, scale_factor: float, alpha_factor: float) -> None:
        hwnd = self._hwnd
        frame = self._cached_frame
        if hwnd is None or frame is None:
            return

        w, h = frame.size
        if scale_factor < 0.999:
            sw = max(1, round(w * scale_factor))
            sh = max(1, round(h * scale_factor))
            scaled = frame.resize((sw, sh), Image.Resampling.BILINEAR)
            composed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ox = (w - sw) // 2
            oy = (h - sh) if self._direction >= 0 else 0
            # Blend from near anchor edge cleanly while keeping inside canvas
            oy = max(0, min(h - sh, oy))
            composed.paste(scaled, (ox, oy))
            src_img = composed
        else:
            src_img = frame

        premult = src_img.convert("RGBa")
        r, g, b, a = premult.split()
        bgra_bytes = Image.merge("RGBA", (b, g, r, a)).tobytes()

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = DIB_RGB_COLORS

        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0)
        if hbmp:
            ctypes.memmove(bits_ptr, bgra_bytes, len(bgra_bytes))
            old_bmp = gdi32.SelectObject(hdc_mem, hbmp)
            pt_dst = POINT(wx, wy)
            sz = SIZE(w, h)
            pt_src = POINT(0, 0)
            bf = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, round(255 * alpha_factor))), AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(
                hwnd,
                hdc_screen,
                ctypes.byref(pt_dst),
                ctypes.byref(sz),
                hdc_mem,
                ctypes.byref(pt_src),
                0,
                ctypes.byref(bf),
                ULW_ALPHA,
            )
            gdi32.SelectObject(hdc_mem, old_bmp)
            gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

    def _hit_test(self, x: int, y: int) -> str | None:
        pad = round(SHADOW_PAD * self._scale)
        rects = self._renderer.button_rects(self._scale, pad)
        state = self._get_state()
        has_track = bool(state.get("hasTrack"))
        for key, (x0, y0, x1, y1) in rects.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                if key in ("prev", "play", "next") and not has_track:
                    return None
                return key
        return None

    def _on_mouse_move(self, x: int, y: int) -> None:
        if not self._tracking_leave and self._hwnd is not None:
            tme = TRACKMOUSEEVENT(
                ctypes.sizeof(TRACKMOUSEEVENT),
                TME_LEAVE,
                self._hwnd,
                0,
            )
            user32.TrackMouseEvent(ctypes.byref(tme))
            self._tracking_leave = True

        hit = self._hit_test(x, y)
        cursor_id = IDC_HAND if hit else IDC_ARROW
        user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(cursor_id)))
        if hit != self._hover_id:
            self._hover_id = hit
            if self._visible:
                self._refresh_bitmap()
                if not self._anim_mode:
                    self._commit_frame(self._target_x, self._target_y, 1.0, 1.0)

    def _trigger_action(self, action_id: str) -> None:
        if action_id in ("prev", "next"):
            self._on_action(action_id)
            return
        if action_id == "play":
            self._on_action("toggle")
            return
        if action_id == "show":
            self._start_hide()
            self._on_open_ui()
            return
        if action_id == "quit":
            self._start_hide()
            self._on_quit()
