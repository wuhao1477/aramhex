"""macOS 虚拟机里：在 Parallels 窗口的截图中找到 LoL 客户端的矩形。

为什么需要：Windows 上截图就是客户端窗口本身，版式按整张截图换算就对；虚拟机里客户端只是窗口化的一块
（1280×720 左右，周围是 Windows 桌面），按整张截图换算每个框都偏，头像和文字都认不出来。

做法：客户端左上角的徽标在大多数界面（主页、创建房间等）都在同一个位置，拿它做模板，多尺度匹配即可得到
客户端的位置和大小。选人界面没有顶部导航栏、看不到徽标时，沿用上一次定位的结果（同一截图尺寸内有效）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# 模板是从 1280 像素宽的客户端里截的徽标：模板里 (22, 8) 是客户端内的左上角
TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "client_logo.png"
TEMPLATE_ORIGIN = (22, 8)
TEMPLATE_CLIENT_W = 1280
TEMPLATE_CLIENT_H = 720
MIN_SCORE = 0.9
_BIG = 8       # 细调时模板的放大倍数
_MARGIN = 12   # 细调搜索窗口比模板大出的像素

_tpl = None
_tpl_missing = False


def _template():
    global _tpl, _tpl_missing
    if _tpl is None and not _tpl_missing:
        _tpl = cv2.imread(str(TEMPLATE))
        if _tpl is None:  # 打包时漏带会一直静默找不到客户端，所以留一行日志（只提示一次）
            _tpl_missing = True
            log.warning("缺少客户端徽标模板 %s，虚拟机里找不到 LoL 客户端", TEMPLATE)
    return _tpl


def _refine(img: np.ndarray, tpl: np.ndarray, scale: float, loc: tuple[float, float]) -> tuple[float, tuple[int, int]]:
    """原图分辨率上细调缩放和位置。模板只有 54 像素，直接缩放只能分出 ~2% 的档，所以先放大 8 倍再缩回去，档距降到 0.2%。
    返回 (缩放, 模板左上角在原图里的位置)；细调失败就沿用粗找结果。"""
    big = cv2.resize(tpl, None, fx=_BIG, fy=_BIG, interpolation=cv2.INTER_CUBIC)
    best = (-1.0, scale, loc)
    for s in np.arange(scale * 0.97, scale * 1.03 + 1e-9, 0.002):
        t = cv2.resize(big, None, fx=s / _BIG, fy=s / _BIG, interpolation=cv2.INTER_AREA)
        xa, ya = max(0, int(loc[0]) - _MARGIN), max(0, int(loc[1]) - _MARGIN)
        xb = min(img.shape[1], int(loc[0]) + t.shape[1] + _MARGIN)
        yb = min(img.shape[0], int(loc[1]) + t.shape[0] + _MARGIN)
        roi = img[ya:yb, xa:xb]
        if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
            continue
        _, mx, _, p = cv2.minMaxLoc(cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED))
        if mx > best[0]:
            best = (mx, float(s), (xa + p[0], ya + p[1]))
    return best[1], best[2]


def find_client(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """截图 → 客户端矩形 (x, y, w, h)，相对截图左上角；找不到返回 None。"""
    tpl = _template()
    if tpl is None or img is None or img.size == 0:
        return None
    # 先缩到 1280 宽再找：Retina 上整块虚拟机画面是 2 倍像素，徽标会超出下面的缩放范围，全尺寸匹配也慢
    f = min(1.0, 1280 / img.shape[1])
    small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    best_score, best_scale, best_loc = -1.0, 1.0, (0, 0)
    for s in np.arange(0.4, 1.6, 0.02):
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] > small.shape[0] or t.shape[1] > small.shape[1]:
            continue
        score = cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(score)
        if mx > best_score:
            best_score, best_scale, best_loc = mx, float(s), loc
    if best_score < MIN_SCORE:
        return None
    # 粗找的缩放档距 2%，客户端宽会差 20 多像素；在原图上围绕粗找结果细调
    best_scale, best_loc = _refine(img, tpl, best_scale / f, (best_loc[0] / f, best_loc[1] / f))
    ox, oy = TEMPLATE_ORIGIN
    # 换算回原截图的像素
    x = round(best_loc[0] - ox * best_scale)
    y = round(best_loc[1] - oy * best_scale)
    w = round(TEMPLATE_CLIENT_W * best_scale)
    h = round(TEMPLATE_CLIENT_H * best_scale)
    # 客户端不会越出截图
    x, y = max(0, x), max(0, y)
    w, h = min(w, img.shape[1] - x), min(h, img.shape[0] - y)
    return (x, y, w, h) if w > 0 and h > 0 else None
