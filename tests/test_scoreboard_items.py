"""计分板装备识别：样本 scoreboard_sr_tab_items.png（召唤师峡谷 5v5，自定义对局）。

标注只包含肉眼确认过的格子。格子编号 = 队伍(0/1) 行(0-4) 格(0-6)。
准确率的要求是：答出来的必须全对（不能答错），认不出的可以报未知。
"""
from pathlib import Path

import cv2
import pytest

from lolhex.vision import scoreboard

FIX = Path(__file__).resolve().parent / "fixtures" / "scoreboard_sr_tab_items.png"
FIX_G2 = {  # 同一局里后来抓的两张（装备变多了）
    "t1": Path(__file__).resolve().parent / "fixtures" / "scoreboard_sr_tab_items_g2_t1.png",
    "t2": Path(__file__).resolve().parent / "fixtures" / "scoreboard_sr_tab_items_g2_t2.png",
}

LABELS = {
    "010": "1055", "110": "1055", "020": "1055", "140": "1055",                 # 多兰之刃
    "016": "3340", "026": "3340", "036": "3340",                                 # 守卫（饰品）
    "116": "3340", "126": "3340", "136": "3340", "146": "3340",
}
LABELS_G2 = {
    "t1": {"016": "3340", "026": "3340", "036": "3340", "146": "3340", "020": "1055", "140": "1055"},
    "t2": {"036": "3340", "046": "3340", "106": "3340", "116": "3340", "136": "3340", "146": "3340",
           "031": "2055", "042": "2055", "142": "2055", "100": "1055", "140": "1055", "130": "1054"},
}


# 游戏截图只留在本地（不进 git）；没有截图时这些用例跳过
needs_capture = pytest.mark.skipif(not FIX.exists(), reason="缺少本地计分板截图 scoreboard_sr_tab_items.png")


@pytest.fixture(scope="module")
def img():
    if not FIX.exists():
        pytest.skip("缺少本地计分板截图")
    im = cv2.imread(str(FIX))
    assert im is not None
    return im


def _cell(code):
    return int(code[0]), int(code[1]), int(code[2])


def test_grid_covers_70_cells(img):
    cells = scoreboard.read_items(img)
    assert len(cells) == 70
    assert {(c["team"], c["row"], c["slot"]) for c in cells} == {
        (t, r, s) for t in (0, 1) for r in range(5) for s in range(7)}


def test_bank_has_item_icons():
    ids, bank = scoreboard.load_bank()
    assert len(ids) > 600 and bank.shape[1:] == (64, 64, 3)
    assert "1055" in ids and "3340" in ids


def test_known_items_are_never_wrong(img):
    answered = right = 0
    for code, want in LABELS.items():
        item, _ = scoreboard.read_cell(img, *_cell(code))
        if item is not None:
            answered += 1
            assert item == want, (code, item, want)
            right += 1
    assert answered == right


def test_known_items_are_mostly_recognized(img):
    got = sum(scoreboard.read_cell(img, *_cell(code))[0] == want for code, want in LABELS.items())
    assert got >= 10, f"只认出 {got}/{len(LABELS)}"


@pytest.mark.parametrize("code", ["006", "001", "100"])
def test_empty_cells_are_none(img, code):
    assert scoreboard.read_cell(img, *_cell(code)) == (None, 0.0)


@needs_capture
@pytest.mark.parametrize("tag", ["t1", "t2"])
def test_same_game_later_captures_never_wrong(tag):
    if not FIX_G2[tag].exists():
        pytest.skip("缺少本地计分板截图")
    im = cv2.imread(str(FIX_G2[tag]))
    assert im is not None
    answered = 0
    for code, want in LABELS_G2[tag].items():
        item, _ = scoreboard.read_cell(im, *_cell(code))
        if item is not None:
            answered += 1
            assert item == want, (tag, code, item, want)
    assert answered >= 6


@pytest.mark.parametrize("code", ["031", "131", "141"])
def test_potion_cells_are_recognized(img, code):
    item, _ = scoreboard.read_cell(img, *_cell(code))
    assert item == "2003", (code, item)
