"""macOS 虚拟机：Parallels 窗口截图里 LoL 客户端只占一块（1280×720 左右，周围是 Windows 桌面）。
先在主页找到客户端的位置，再在选人截图里只识别客户端内部，头像才认得出来（队友、预选栏都靠头像）。"""
from pathlib import Path

import cv2

from lolhex.config import Settings
from lolhex.engine import Engine
from lolhex.vision import capture, clientfind
from lolhex.vision.portraits import IconBank, client_icons

FIX = Path(__file__).parent / "fixtures"


def test_find_client_on_home_screen():
    box = clientfind.find_client(cv2.imread(str(FIX / "client_home_vm.png")))
    assert box is not None
    x, y, w, h = box
    assert abs(x - 100) <= 2 and abs(y - 92) <= 2 and abs(w - 1280) <= 4 and abs(h - 720) <= 4


def test_champ_select_recognized_inside_located_client(store, tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "IS_MACOS", True)
    eng = Engine(Settings(), home=tmp_path, store=store)
    eng._icon_bank = IconBank(client_icons())
    home = cv2.imread(str(FIX / "client_home_vm.png"))
    eng._client_crop(home, (0, 0))            # 主页上定位一次
    cs_img = cv2.imread(str(FIX / "champ_select_title_kled.png"))
    crop, origin = eng._client_crop(cs_img, (0, 0))  # 选人界面沿用定位结果
    assert crop.shape[:2] == (720, 1280) and origin == (100, 92)
    cs = eng.analyze_champ_select(crop, origin)
    assert cs and cs.get("mine") == "240"    # 240 = 克烈（暴怒骑士），我方那一行的头像
