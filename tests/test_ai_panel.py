"""三选一页的 AI 区域：只显示当前这组卡的结果；关闭、未配置时说明原因。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolhex.engine import _ai_key_str  # noqa: E402


@pytest.fixture
def win(store, tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    monkeypatch.setenv("AI_BASE_URL", "https://ai.test/v1")
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setenv("AI_MODEL", "m")
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from lolhex.config import Settings
    from lolhex.engine import Engine
    from lolhex.ui.mainwindow import MainWindow
    from lolhex.ui.overlay import Overlay

    eng = Engine(Settings(seen_welcome=True), home=tmp_path, store=store)
    overlay = Overlay(eng)
    w = MainWindow(eng, overlay)
    overlay.timer.stop()
    w.show()
    yield w, eng
    w.hide()
    overlay.set_visible(False)
    w.deleteLater()
    overlay.panel.deleteLater()
    overlay.badges.deleteLater()
    overlay.champ.deleteLater()
    eng.stop()
    app.processEvents()


def test_result_shows_for_current_offer_only(win):
    w, eng = win
    ids = list(eng.store.augments)[:3]
    eng.state.update(phase="ingame", offer={"slots": ids})
    eng.state["ai"] = {"status": "done", "key": _ai_key_str(None, ids), "error": None,
                       "result": {"pick": 1, "reason": "稳", "model": "m"}}
    w.refresh()
    name = eng.store.augments[ids[1]]["name"]
    assert f"第 2 张「{name}」" in w.ai_label.text() and "稳" in w.ai_label.text()
    assert w.btn_ai.isEnabled()
    eng.state["offer"] = {"slots": [ids[0], ids[1], list(eng.store.augments)[5]]}  # 卡换了
    w.refresh()
    assert "AI 推荐" not in w.ai_label.text()


def test_off_mode_disables_button_and_says_why(win):
    w, eng = win
    eng.settings.ai_mode = "off"
    w.refresh()
    assert "已关闭" in w.ai_label.text() and not w.btn_ai.isEnabled()


def test_unconfigured_explains_env(win, monkeypatch):
    w, eng = win
    monkeypatch.delenv("AI_API_KEY")
    w.refresh()
    assert ".env" in w.ai_label.text() and not w.btn_ai.isEnabled()
