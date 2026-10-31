"""macOS 窗口查找与矩形（Quartz，只读）。

窗口句柄用 CGWindowID（整数），与 Windows 的 hwnd 同类型，所以 window.py 的签名不用改。

坐标一律用**物理像素**：capture 返回的也是物理像素，两边同一空间（上游的不变式：
`mask_drawn(img, rect, drawn_rects())` 直接相减，三者必须同单位）。

实测要点（macOS 26.7 / 多屏混合 DPR，2026-10-30）：
  - CGWindowBounds 与 Qt 的 QScreen.geometry() 是同一套坐标（主屏左上角原点，y 向下），
    可以直接喂给 QScreen.grabWindow，**不需要 y 轴翻转**。
  - Parallels 虚拟机窗口的 kCGWindowName 为空字符串，只能按 owner 匹配 + 取面积最大。
  - CGWindowListCreateImage 在 macOS 26 上返回全零，所以按屏幕区域抓（见 capture.py）。
  - kCGWindowSharingState 普遍是 0，但不影响按屏幕区域抓（那只挡按窗口抓）。
"""

from __future__ import annotations

import sys
import threading
import time

import Quartz

from .window import Rect

# 游戏窗口：原生客户端按标题；虚拟机窗口标题为空，按 owner
GAME_TITLES = ("League of Legends (TM) Client",)
CLIENT_TITLES = ("League of Legends",)
VM_OWNERS = ("Parallels Desktop", "VMware Fusion", "UTM")

# 自己贴上去的浮窗（按 pid 记），判定前台时不算「别的程序」
_companions: set[int] = set()
_last_other = 0
_fg_lock = threading.Lock()


# ---------------------------------------------------------------- 窗口枚举

def _window_info() -> list[dict]:
    """屏幕上 layer=0 的窗口：id / owner / title / pid / bounds（点）。"""
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    out = []
    for w in wins:
        if w.get("kCGWindowLayer") != 0:
            continue
        b = w.get("kCGWindowBounds", {}) or {}
        width, height = int(b.get("Width", 0)), int(b.get("Height", 0))
        if width < 200 or height < 150:  # 和上游 client_rect 同一门槛
            continue
        out.append({
            "id": int(w.get("kCGWindowNumber", 0)),
            "owner": w.get("kCGWindowOwnerName") or "",
            "title": w.get("kCGWindowName") or "",
            "pid": int(w.get("kCGWindowOwnerPID", 0)),
            "x": int(b.get("X", 0)), "y": int(b.get("Y", 0)),
            "w": width, "h": height,
        })
    return out


def _match(owner_sub: str, title_sub: str) -> int:
    """按 owner/title 子串找窗口，多个命中时取面积最大的。"""
    hits = [w for w in _window_info()
            if (not owner_sub or owner_sub.lower() in w["owner"].lower())
            and (not title_sub or title_sub.lower() in w["title"].lower())]
    if not hits:
        return 0
    return max(hits, key=lambda w: w["w"] * w["h"])["id"]


# 手动指定的游戏窗口（tools/pick_window.py 写入）。机器上可能开着多个虚拟机，
# 按面积猜会猜错，所以选一次就固定下来；窗口不在了再退回自动。
#
# 也可以直接指定「整块显示器」——全屏游戏时这比按窗口抓更省事，也不受标题栏影响。
# 显示器用负数句柄表示：-1 = 第 0 块屏，-2 = 第 1 块屏，以此类推。
_choice_cache: tuple[float, int] | None = None
_choice_doc: tuple[float, dict] | None = None


def choice_doc() -> dict:
    """读 window_choice.json 原文（2 秒缓存）。没有就返回空 dict。"""
    global _choice_doc
    now = time.monotonic()
    if _choice_doc and now - _choice_doc[0] < 2.0:
        return _choice_doc[1]

    from ..config import app_home
    path = app_home() / "window_choice.json"
    try:
        import json
        want = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(want, dict):
            want = {}
    except (OSError, ValueError, ImportError):
        want = {}
    _choice_doc = (now, want)
    return want


def locked() -> bool:
    """是否「锁定」：锁定后不再要求游戏窗口在前台。

    为什么需要：上游按「游戏窗口不在前台就暂停」省 OCR。但虚拟机里跑游戏时，
    只要鼠标没点在虚拟机上，Parallels 就不是前台，识别就一直停在
    「游戏不在前台，暂停」。选定窗口/整屏并锁定后，就按选中的那块一直抓。
    整屏（负句柄）本来就没有对应进程，一直是前台。
    """
    return bool(choice_doc().get("lock"))


def _chosen_window() -> int:
    """读手动选择。窗口按 owner + 位置最接近匹配；显示器直接返回负句柄。"""
    global _choice_cache
    now = time.monotonic()
    if _choice_cache and now - _choice_cache[0] < 2.0:
        return _choice_cache[1]

    want = choice_doc()
    if not want:
        return 0

    if want.get("kind") == "display":
        idx = int(want.get("display", 0))
        err, displays, _ = Quartz.CGGetActiveDisplayList(16, None, None)
        if not err and 0 <= idx < len(displays):
            _choice_cache = (now, -(idx + 1))
            return -(idx + 1)
        return 0

    best, best_d = 0, None
    for w in _window_info():
        if w["owner"] != want.get("owner"):
            continue
        d = (abs(w["x"] - want.get("x", 0)) + abs(w["y"] - want.get("y", 0))
             + abs(w["w"] - want.get("w", 0)) + abs(w["h"] - want.get("h", 0)))
        if best_d is None or d < best_d:
            best, best_d = w["id"], d
    _choice_cache = (now, best)
    return best


def find_game_window() -> int:
    """游戏窗口：优先用手动指定的；否则按标题找客户端，再按 owner 找虚拟机窗口。"""
    wid = _chosen_window()
    if wid:
        return wid
    for t in GAME_TITLES:
        wid = _match("", t)
        if wid:
            return wid
    for owner in VM_OWNERS:
        wid = _match(owner, "")
        if wid:
            return wid
    return 0


def find_client_window() -> int:
    """客户端大厅窗口。找不到就返回 0（上游把 0 当「没有客户端」处理）。"""
    for t in CLIENT_TITLES:
        wid = _match("", t)
        if wid:
            return wid
    return _match("Riot", "")


def _info_of(wid: int) -> dict | None:
    for w in _window_info():
        if w["id"] == wid:
            return w
    return None


# ---------------------------------------------------------------- 缩放换算

def _display_scale(display) -> float:
    """一块显示器的缩放倍数（物理像素 / 点）。

    ⚠️ 不能用 CGDisplayPixelsWide：实测它在 macOS 26 上返回的是**点**宽
    （内建 Retina 返回 1800，而真实像素是 3600）。要用 display mode 的
    PixelWidth / Width 才是对的。
    """
    mode = Quartz.CGDisplayCopyDisplayMode(display)
    if mode is None:
        return 1.0
    w = Quartz.CGDisplayModeGetWidth(mode)
    pw = Quartz.CGDisplayModeGetPixelWidth(mode)
    return (pw / w) if w else 1.0


def scale_at(x: int, y: int) -> float:
    """点 (x, y) 所在显示器的缩放倍数。拿不到返回 1.0。

    macOS 多屏可以是混合 DPR（内建 Retina 2.0 + 外接 1080p 1.0），
    所以不能用主屏的 devicePixelRatio 一刀切。
    """
    err, displays, _ = Quartz.CGGetActiveDisplayList(16, None, None)
    if err or not displays:
        return 1.0
    for d in displays:
        r = Quartz.CGDisplayBounds(d)
        if (r.origin.x <= x < r.origin.x + r.size.width
                and r.origin.y <= y < r.origin.y + r.size.height):
            return _display_scale(d)
    return 1.0


def scale_for_rect(rect: Rect) -> float:
    """矩形（**物理像素**）中心所在显示器的缩放倍数。

    不能直接拿物理坐标去比 CGDisplayBounds 的点坐标，所以先把每块屏的 bounds
    按各自的缩放换算成物理像素再比对。多屏混合 DPR 时这是唯一可靠的判法。
    """
    cx = rect.left + rect.width // 2
    cy = rect.top + rect.height // 2
    err, displays, _ = Quartz.CGGetActiveDisplayList(16, None, None)
    if err or not displays:
        return 1.0
    fallback = 1.0
    for d in displays:
        r = Quartz.CGDisplayBounds(d)
        s = _display_scale(d)
        fallback = s
        px0, py0 = r.origin.x * s, r.origin.y * s
        if px0 <= cx < px0 + r.size.width * s and py0 <= cy < py0 + r.size.height * s:
            return s
    return fallback


# ---------------------------------------------------------------- 矩形

# 窗口标题栏高度（点）。macOS 没有查询「内容区」的公开 API（AX 那条路要辅助功能权限），
# 所以按 owner 查表；铺满整块屏的窗口按 0 处理。值不对会让上游的默认标题框整体偏移。
TITLEBAR = {
    "Parallels Desktop": 38,   # 实测：1799x1050 的 VM 窗口，内容区从 y=38 开始
    "VMware Fusion": 28,
    "UTM": 28,
}
TITLEBAR_DEFAULT = 28


def _titlebar_height(info: dict) -> int:
    """窗口标题栏高度（点）。窗口铺满某块屏时视为无标题栏。"""
    err, displays, _ = Quartz.CGGetActiveDisplayList(16, None, None)
    if not err and displays:
        for d in displays:
            r = Quartz.CGDisplayBounds(d)
            if (abs(info["x"] - r.origin.x) <= 1 and abs(info["y"] - r.origin.y) <= 1
                    and abs(info["w"] - r.size.width) <= 1 and abs(info["h"] - r.size.height) <= 1):
                return 0
    return TITLEBAR.get(info["owner"], TITLEBAR_DEFAULT)


def window_rect(wid: int) -> Rect | None:
    """窗口在屏幕上的物理像素矩形（含标题栏）。负句柄表示整块显示器。"""
    if wid < 0:
        return _display_rect(-wid - 1)
    w = _info_of(wid)
    if w is None:
        return None
    s = scale_at(w["x"] + w["w"] // 2, w["y"] + w["h"] // 2)
    return Rect(int(w["x"] * s), int(w["y"] * s), int(w["w"] * s), int(w["h"] * s))


def client_rect(wid: int) -> Rect | None:
    """窗口内容区在屏幕上的物理像素矩形（不含标题栏）。

    上游的默认标题框是按「游戏铺满客户区」定的，Windows 的 GetClientRect 天然不含标题栏。
    macOS 的 CGWindowBounds 含标题栏，不减掉会让默认位置整体下移一个标题栏高度，
    读到的是卡片图标而不是标题 —— 表现为「认出一堆不相干的海克斯名」。

    负句柄表示「整块显示器」（见 _chosen_window），直接返回该屏的物理像素范围。
    """
    if wid < 0:
        return _display_rect(-wid - 1)
    w = _info_of(wid)
    if w is None:
        return None
    s = scale_at(w["x"] + w["w"] // 2, w["y"] + w["h"] // 2)
    tb = _titlebar_height(w)
    return Rect(int(w["x"] * s), int((w["y"] + tb) * s),
                int(w["w"] * s), int((w["h"] - tb) * s))


def _display_rect(idx: int) -> Rect | None:
    """第 idx 块显示器的物理像素范围。全屏游戏直接抓整屏时用。"""
    err, displays, _ = Quartz.CGGetActiveDisplayList(16, None, None)
    if err or not displays or not 0 <= idx < len(displays):
        return None
    d = displays[idx]
    r = Quartz.CGDisplayBounds(d)
    s = _display_scale(d)
    return Rect(int(r.origin.x * s), int(r.origin.y * s),
                int(r.size.width * s), int(r.size.height * s))


def set_window_rect(wid: int, r: Rect) -> None:
    """macOS 上不摆窗口：overlay 走 _place_qt（Qt 自己管几何），此函数不会被调用。"""
    return None


# ---------------------------------------------------------------- 前台判定

def _frontmost_pid() -> int:
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app else 0


def _on_foreground(pid: int) -> None:
    global _last_other
    if pid and pid not in _companions:
        with _fg_lock:
            _last_other = pid


def watch_foreground() -> None:
    """macOS 上按需查询即可，不装事件钩子（overlay 每帧都会问 is_foreground）。"""
    return None


def is_foreground(wid: int) -> bool:
    """窗口所属进程是否在前台。点自己的浮窗时，按点之前那个进程算。

    负句柄（整块显示器）没有对应进程，直接算前台 —— 全屏游戏时本来就该一直识别。
    锁定时（window_choice.json 里 lock=true）也不看前台：虚拟机窗口在后台照样识别。
    """
    if not wid:
        return False
    if wid < 0 or locked():
        return True
    w = _info_of(wid)
    if w is None:
        return False
    pid = w["pid"]
    front = _frontmost_pid()
    if front in _companions:
        with _fg_lock:
            return _last_other == pid
    _on_foreground(front)
    return front == pid


def add_companion(wid: int) -> None:
    """登记自己的浮窗（按 pid）。overlay 建浮窗时调用。"""
    if not wid:
        return
    w = _info_of(wid)
    if w:
        _companions.add(w["pid"])


def give_focus(wid: int) -> None:
    """把前台还给游戏/客户端。overlay 在 macOS 上走 _place_qt，不会调用此函数。"""
    return None


# ---------------------------------------------------------------- 杂项

def enable_dpi_awareness() -> None:
    """macOS 没有 DPI 感知这回事，Qt 自己处理。"""
    return None


def lower_thread_priority() -> None:
    """当前线程降到低于正常，游戏要用 CPU 时先让给它。"""
    try:
        import os
        os.nice(5)
    except (OSError, AttributeError):
        pass


def dpi_info(wid: int = 0) -> str:
    """诊断用：窗口所在屏的缩放倍数。"""
    if not wid:
        return ""
    w = _info_of(wid)
    if w is None:
        return ""
    s = scale_at(w["x"] + w["w"] // 2, w["y"] + w["h"] // 2)
    return f"缩放 {s:g}x"


def left_button_clicked() -> bool:
    """上游没有任何地方调用，保留签名即可。"""
    return False


def cursor_pos() -> tuple[int, int]:
    """上游没有任何地方调用，保留签名即可。"""
    return (0, 0)
