"""屏幕截取：只截需要的矩形区域，返回 BGR numpy 数组。

Windows/Linux 用 mss（GDI BitBlt）：无边框/窗口化下可用；独占全屏可能截到黑屏，界面会提示改无边框。
macOS 用 Qt 的 QScreen.grabWindow：mss 在 Retina 上只给 1x 像素，识别小字号中文会掉命中率。
"""

from __future__ import annotations

import sys
import threading

import numpy as np

from . import window
from .window import Rect

IS_MACOS = sys.platform == "darwin"

_local = threading.local()


def screen_access() -> bool:
    """macOS 有没有屏幕录制权限。没有时截屏不报错，只拿到桌面壁纸，表现为认不出英雄和海克斯。"""
    if not IS_MACOS:
        return True
    import Quartz
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def _mss():
    inst = getattr(_local, "mss", None)
    if inst is None:
        import mss
        inst = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        _local.mss = inst
    return inst


def release() -> None:
    """关掉本线程的截屏实例。一次性线程用完必须调：mss 不会自己释放，每个线程会留下一块 GDI 位图（4K 约 33MB）。"""
    inst = getattr(_local, "mss", None)
    if inst is not None:
        _local.mss = None
        inst.close()


def _grab_macos(rect: Rect) -> np.ndarray:
    """rect 是物理像素；Qt 收点坐标、返回的仍是物理像素，两边单位对得上。

    实测（macOS 26.7 / 多屏混合 DPR）：CGWindowBounds 与 QScreen.geometry 同一套坐标，
    直接传即可，无需 y 轴翻转；抓 800x600 点约 2.9 ms。
    """
    from PySide6.QtGui import QGuiApplication, QImage

    from .macos_window import scale_for_rect

    s = scale_for_rect(rect) or 1.0
    x, y = round(rect.left / s), round(rect.top / s)
    w, h = max(1, round(rect.width / s)), max(1, round(rect.height / s))
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        # 没有 QGuiApplication 就没有屏幕可抓（正常跑应用时一定有；工具脚本要自己建）
        return np.zeros((rect.height, rect.width, 3), np.uint8)
    pix = screen.grabWindow(0, x, y, w, h)
    if pix.isNull():  # 坐标落到虚拟桌面之外
        return np.zeros((rect.height, rect.width, 3), np.uint8)
    img = pix.toImage().convertToFormat(QImage.Format.Format_RGB32)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)
    return np.ascontiguousarray(arr[:, :img.width(), :3])  # BGRA -> BGR


def grab(rect: Rect, mask: bool = True) -> np.ndarray:
    """截 rect 这块屏幕。mask=True（识别用）时把本程序浮窗画着的地方涂黑，不认自己画的字；
    自动截图要看浮窗摆得对不对，用 mask=False。"""
    if IS_MACOS:
        img = _grab_macos(rect)
    else:
        shot = _mss().grab({"left": rect.left, "top": rect.top,
                            "width": rect.width, "height": rect.height})
        arr = np.asarray(shot)  # BGRA
        img = np.ascontiguousarray(arr[:, :, :3])
    if mask:
        mask_drawn(img, rect, window.drawn_rects())
    return img


def mask_drawn(img: np.ndarray, rect: Rect, drawn) -> int:
    """把 drawn（屏幕物理像素）和截图 rect 重叠的部分涂黑，返回涂了几块。"""
    n = 0
    h, w = img.shape[:2]
    for d in drawn:
        x0, y0 = max(0, d.left - rect.left), max(0, d.top - rect.top)
        x1, y1 = min(w, d.left + d.width - rect.left), min(h, d.top + d.height - rect.top)
        if x0 < x1 and y0 < y1:
            img[y0:y1, x0:x1] = 0
            n += 1
    return n


def is_blank(img: np.ndarray) -> bool:
    """全黑/几乎纯色：多半是独占全屏截不到。"""
    if img.size == 0:
        return True
    # 隔 4 像素取一点就够判断是不是纯色，整张 4K 图算一次要 90 ms 左右；小条带照旧用整图
    h, w = img.shape[:2]
    sample = img if min(h, w) < 32 else img[::4, ::4]
    return float(sample.std()) < 2.0
