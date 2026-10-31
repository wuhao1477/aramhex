"""选英雄界面：窗口化、客户端没铺满截图（虚拟机里）时，头像和固定位置都对不上，要靠整屏文字认英雄。
截图是 macOS 虚拟机里实机截的（克烈锁定后的选人界面，左边我方一行和中间大字都是称号「暴怒骑士」）。"""
import json
from pathlib import Path

import cv2

from lolhex.config import Settings
from lolhex.engine import Engine
from lolhex.vision.matcher import NameMatcher

ROOT = Path(__file__).resolve().parents[1]


def _static_names():
    heroes = json.loads((ROOT / "lolhex/data/static_bundled.json").read_text(encoding="utf-8"))["heroes"]
    names = {}
    for hid, h in heroes.items():
        names[hid] = h.get("name") or ""
        names[hid + "#nick"] = h.get("nick") or ""
        names[hid + "#full"] = f"{h.get('nick', '')} {h.get('name', '')}"
    return names


def test_title_on_windowed_client_recognized(store, tmp_path, monkeypatch):
    eng = Engine(Settings(), home=tmp_path, store=store)
    monkeypatch.setattr(eng, "_hero_matcher", lambda: NameMatcher(_static_names(), 86.0))
    img = cv2.imread(str(ROOT / "tests/fixtures/champ_select_title_kled.png"))
    cs = eng.analyze_champ_select(img)
    seen = []
    monkeypatch.setattr(eng, "_set_hero_auto", lambda hid, src: seen.append((hid, src)))
    monkeypatch.setattr(eng, "_set", lambda **kw: None)
    eng._apply_champ_select(cs, img)
    assert seen == [("240", "ocr")]  # 240 = 克烈（暴怒骑士）
