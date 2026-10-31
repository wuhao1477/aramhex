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
    ox, oy = TEMPLATE_ORIGIN
    # 换算回原截图的像素
    x = round((best_loc[0] - ox * best_scale) / f)
    y = round((best_loc[1] - oy * best_scale) / f)
    w = round(TEMPLATE_CLIENT_W * best_scale / f)
    h = round(TEMPLATE_CLIENT_H * best_scale / f)
    # 客户端不会越出截图
    x, y = max(0, x), max(0, y)
    w, h = min(w, img.shape[1] - x), min(h, img.shape[0] - y)
    return (x, y, w, h) if w > 0 and h > 0 else None
