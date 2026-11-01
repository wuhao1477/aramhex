"""Tab 计分板上的装备识别（召唤师峡谷，5v5）。

只认得出来才报 id，认不出来报 None：宁可少报，也不报错。
布局是按 tests/fixtures/scoreboard_sr_tab_items.png 标定的（坐标是这张裁剪图里的像素），
换分辨率或界面缩放后需要重新标定；这是已知的上限。

每队一行 7 格：前 6 格是装备，最后 1 格是饰品。
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path

import cv2
import numpy as np

from ..data.icons import bundled_icons

# 标定值（裁剪图里的像素）
BLOCK_X = (904, 2341)      # 两队装备区起点
SLOT_PITCH = 91            # 相邻格子的间距
SLOT_INSET = (6, 80)       # 格子内区域：从格子左上角偏移的起止（x 与 y 共用）
ROW_TOP = 295.5            # 第一行的顶
ROW_PITCH = 202.5          # 行距
SLOTS = 7                  # 6 件装备 + 1 个饰品
ICON = 64                  # 图标库的边长
UI_ID_RANGE = (550000, 560000)  # 界面素材的 id 段，不参与装备匹配

OCCUPIED_STD = 30          # 格子内亮度标准差低于它就当作空格
MIN_SCORE = 0.55           # 最佳匹配低于它就报未知（误报多在 0.54 左右被遮挡的格子上；正确的装备一般 >0.57）


# 库里的图标和游戏计分板上的不一致的，用计分板上截下来的样本替换（2003 生命药水：库里是红色杯子）
SCOREBOARD_OVERRIDES = {"2003": "item_2003_scoreboard.png"}
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@functools.lru_cache(maxsize=1)
def load_bank() -> tuple[tuple[str, ...], np.ndarray]:
    """装备图标库：(id 列表, 形状 (N, 64, 64, 3) 的 float32)。"""
    ids, imgs = [], []
    for key, b64 in bundled_icons().get("item", {}).items():
        if UI_ID_RANGE[0] <= int(key) < UI_ID_RANGE[1]:  # 550xxx 是界面素材（生命条色块、派对礼品），不是装备
            continue
        if str(key) in SCOREBOARD_OVERRIDES:
            continue
        arr = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
        if arr is not None:
            ids.append(str(key))
            imgs.append(cv2.resize(arr, (ICON, ICON), interpolation=cv2.INTER_AREA))
    for key, name in SCOREBOARD_OVERRIDES.items():
        arr = cv2.imread(str(DATA_DIR / name))
        if arr is not None:
            ids.append(key)
            imgs.append(cv2.resize(arr, (ICON, ICON), interpolation=cv2.INTER_AREA))
    return tuple(ids), np.stack(imgs).astype(np.float32)


def _cell_patch(inner: np.ndarray) -> np.ndarray:
    return cv2.resize(inner, (ICON, ICON), interpolation=cv2.INTER_AREA).astype(np.float32)


def _ncc(bank: np.ndarray, patch: np.ndarray) -> np.ndarray:
    a = bank.reshape(len(bank), -1)
    a = a - a.mean(1, keepdims=True)
    b = patch.reshape(-1) - patch.mean()
    return (a @ b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b) + 1e-6)


def _inner(img: np.ndarray, team: int, row: int, slot: int) -> np.ndarray:
    x = BLOCK_X[team] + slot * SLOT_PITCH
    y = int(round(ROW_TOP + row * ROW_PITCH))
    return img[y + SLOT_INSET[0]:y + SLOT_INSET[1], x + SLOT_INSET[0]:x + SLOT_INSET[1]]


def _occupied(inner: np.ndarray) -> bool:
    # 右下角常有金币/数量数字（0、1、3），不算装备，判断占用时跳过
    body = inner[:int(inner.shape[0] * 0.55)]
    return float(body.std()) >= OCCUPIED_STD


def read_cell(img: np.ndarray, team: int, row: int, slot: int) -> tuple[str | None, float]:
    """返回 (装备 id 或 None, 分数)。空格返回 (None, 0.0)。"""
    inner = _inner(img, team, row, slot)
    if not _occupied(inner):
        return None, 0.0
    ids, bank = load_bank()
    scores = _ncc(bank, _cell_patch(inner))
    best = int(scores.argmax())
    score = float(scores[best])
    return (ids[best] if score >= MIN_SCORE else None), score


def read_items(img: np.ndarray) -> list[dict]:
    """读出计分板上所有格子：[{team, row, slot, item, score}, ...]，共 2 * 5 * 7 = 70 格。"""
    out = []
    for team in (0, 1):
        for row in range(5):
            for slot in range(SLOTS):
                item, score = read_cell(img, team, row, slot)
                out.append({"team": team, "row": row, "slot": slot, "item": item, "score": round(score, 3)})
    return out
