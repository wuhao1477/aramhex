"""设置页的「调试模式」开关：写/删数据目录里的 debug.txt，且不落进 config.json。

为什么是文件而不是设置项：debug_mode 是运行期标志，__main__ 按 --debug / 测试版 /
debug.txt 决定。写文件让界面开关和命令行、测试版共用同一套判断；
本机测试脚本（tools/afk_wiggle.py、tools/auto_pick.py）也认这个文件。
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def mw(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from PySide6.QtCore import QTimer
    from lolhex.config import Settings
    from lolhex.engine import Engine
    from lolhex.ui import mainwindow, overlay
    from lolhex import cloud
    from lolhex.vision import window

    # 全局遮罩登记表：不隔离的话，这里登记的 ControlPanel 区域会留到后面的用例里（test_display_transitions 会跟着挂）
    monkeypatch.setattr(window, "_drawn", {})
    # 保存设置会把匿名编号写进 cloud 模块的全局变量，不还原的话后面的日志上传会带上这里的编号（test_logupload 挂）
    monkeypatch.setattr(cloud, "_install_id", None)
    monkeypatch.setattr(mainwindow.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mainwindow.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    # 别去动真实系统的开机自启（macOS 上会写 ~/Library/LaunchAgents）
    monkeypatch.setattr(mainwindow.autostart, "set_enabled", lambda on: None)
    s = Settings.load()
    s.seen_welcome = True
    eng = Engine(s)
    ov = overlay.Overlay(eng)
    w = mainwindow.MainWindow(eng, ov)
    # 和 test_settings_footer 一样收干净：留着活的窗口/浮窗/引擎会污染后面的用例
    # （实测漏了这些清理，test_display_transitions 和 test_logupload 会跟着挂）
    ov.timer.stop()
    w.show()
    w.refresh()
    for timer in w.findChildren(QTimer):
        timer.stop()
    yield w, s, tmp_path
    w.hide()
    ov.set_visible(False)
    w.deleteLater()
    ov.panel.deleteLater()
    ov.badges.deleteLater()
    ov.champ.deleteLater()
    eng.stop()
    app.processEvents()


def test_checkbox_exists_and_follows_settings(mw):
    w, s, _ = mw
    assert hasattr(w, "set_debug"), "设置页应该有调试模式开关"
    assert w.set_debug.isChecked() == bool(getattr(s, "debug_mode", False))
    assert "调试模式" in w.set_debug.text()


def test_toggle_on_writes_marker_and_flips_flag(mw):
    w, s, home = mw
    w.set_debug.setChecked(True)
    w._save_settings()
    assert s.debug_mode is True
    assert (home / "debug.txt").is_file()
    # 不是设置项：不该出现在 config.json 里
    cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "debug_mode" not in cfg


def test_toggle_off_removes_marker(mw):
    w, s, home = mw
    (home / "debug.txt").write_text("x", encoding="utf-8")
    w.set_debug.setChecked(True)
    w._save_settings()
    assert (home / "debug.txt").is_file()
    w.set_debug.setChecked(False)
    w._save_settings()
    assert s.debug_mode is False
    assert not (home / "debug.txt").exists()


def test_marker_survives_existing_file(mw):
    """已经是调试模式（比如命令行 --debug 或测试版建的）：开关不重复写、关掉时删干净。"""
    w, s, home = mw
    (home / "debug.txt").write_text("原有内容", encoding="utf-8")
    w.set_debug.setChecked(True)
    w._save_settings()
    assert (home / "debug.txt").read_text(encoding="utf-8") == "原有内容"
    w.set_debug.setChecked(False)
    w._save_settings()
    assert not (home / "debug.txt").exists()
