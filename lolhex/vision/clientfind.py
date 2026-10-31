"""macOS 虚拟机里：在 Parallels 窗口的截图中找到 LoL 客户端的矩形。

为什么需要：Windows 上截图就是客户端窗口本身，版式按整张截图换算就对；虚拟机里客户端只是窗口化的一块
（1280×720 左右，周围是 Windows 桌面），按整张截图换算每个框都偏，头像和文字都认不出来。

做法：客户端左上角的徽标在大多数界面（主页、创建房间等）都在同一个位置，拿它做模板，多尺度匹配即可得到
客户端的位置和大小。选人界面没有顶部导航栏、看不到徽标时，沿用上一次定位的结果（同一截图尺寸内有效）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# 模板是从 1280 像素宽的客户端里截的徽标：模板里 (22, 8) 是客户端内的左上角
TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "client_logo.png"
TEMPLATE_ORIGIN = (22, 8)
TEMPLATE_CLIENT_W = 1280
TEMPLATE_CLIENT_H = 720
MIN_SCORE = 0.9

_tpl = None


def _template():
    global _tpl
    if _tpl is None:
        _tpl = cv2.imread(str(TEMPLATE))
    return _tpl


def find_client(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """截图 → 客户端矩形 (x, y, w, h)，相对截图左上角；找不到返回 None。"""
    tpl = _template()
    if tpl is None or img is None or img.size == 0:
        return None
    best_score, best_scale, best_loc = -1.0, 1.0, (0, 0)
    for s in np.arange(0.5, 1.6, 0.02):
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] > img.shape[0] or t.shape[1] > img.shape[1]:
            continue
        score = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(score)
        if mx > best_score:
            best_score, best_scale, best_loc = mx, float(s), loc
    if best_score < MIN_SCORE:
        return None
    ox, oy = TEMPLATE_ORIGIN
    x = round(best_loc[0] - ox * best_scale)
    y = round(best_loc[1] - oy * best_scale)
    w = round(TEMPLATE_CLIENT_W * best_scale)
    h = round(TEMPLATE_CLIENT_H * best_scale)
    # 客户端不会越出截图
    x, y = max(0, x), max(0, y)
    w, h = min(w, img.shape[1] - x), min(h, img.shape[0] - y)
    return (x, y, w, h) if w > 0 and h > 0 else None
