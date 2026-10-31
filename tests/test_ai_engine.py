"""引擎里的第三方 AI：自动/手动/关闭三种模式，同一组卡只问一次，换卡不显示旧结果。"""
import time

import pytest

from lolhex import advisor
from lolhex.config import Settings
from lolhex.engine import Engine


@pytest.fixture
def eng(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://ai.test/v1")
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setenv("AI_MODEL", "m")
    e = Engine(Settings(), home=tmp_path, store=store)
    e.state.update(phase="ingame", hero_id="17")
    yield e
    e.stop()


def put_offer(eng, slots):
    eng.state["offer"] = {"slots": list(slots)}


def wait_status(eng, status, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if eng.snapshot()["ai"]["status"] == status:
            return eng.snapshot()["ai"]
        time.sleep(0.01)
    raise AssertionError(f"没有等到 {status}：{eng.snapshot()['ai']}")


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(cfg, hero, augs):
        seen.append((cfg.model, hero, [a["name"] for a in augs]))
        return {"pick": 2, "reason": f"第{len(seen)}次", "model": cfg.model}

    monkeypatch.setattr(advisor, "analyze", fake)
    return seen


def test_auto_analyzes_once_per_offer(eng, calls):
    ids = list(eng.store.augments)[:3]
    put_offer(eng, ids)
    eng._ai_auto()
    done = wait_status(eng, "done")
    assert done["result"]["pick"] == 2 and done["configured"] is True
    assert len(calls) == 1 and calls[0][0] == "m"
    eng._ai_auto()  # 同一组卡：缓存命中，不再问
    assert wait_status(eng, "done")["result"]["reason"] == "第1次"
    assert len(calls) == 1


def test_manual_refresh_overrides_cache(eng, calls):
    put_offer(eng, list(eng.store.augments)[:3])
    eng._ai_auto()
    wait_status(eng, "done")
    eng.ai_refresh()
    assert wait_status(eng, "done")["result"]["reason"] == "第2次"
    assert len(calls) == 2


def test_manual_mode_does_not_auto_run(eng, calls):
    eng.settings.ai_mode = "manual"
    put_offer(eng, list(eng.store.augments)[:3])
    eng._ai_auto()
    assert eng.snapshot()["ai"]["status"] == "idle" and calls == []
    eng.ai_refresh()
    wait_status(eng, "done")
    assert len(calls) == 1


def test_off_mode_never_runs(eng, calls):
    eng.settings.ai_mode = "off"
    put_offer(eng, list(eng.store.augments)[:3])
    eng._ai_auto()
    eng.ai_refresh()
    assert calls == [] and eng.snapshot()["ai"]["status"] == "idle"


def test_incomplete_offer_is_skipped(eng, calls):
    ids = list(eng.store.augments)[:3]
    put_offer(eng, [ids[0], None, ids[2]])
    eng._ai_auto()
    assert calls == [] and eng.snapshot()["ai"]["status"] == "idle"


def test_unconfigured_reports_status_without_network(eng, calls, monkeypatch):
    monkeypatch.delenv("AI_API_KEY")
    put_offer(eng, list(eng.store.augments)[:3])
    eng._ai_auto()
    assert eng.snapshot()["ai"]["status"] == "unconfigured" and calls == []


def test_result_for_old_offer_is_not_shown(eng, monkeypatch):
    """旧一组卡的 AI 慢慢才回来：只进缓存，界面仍显示新一组卡的结果。"""
    import threading
    ids = list(eng.store.augments)[:4]
    old, new = ids[:3], ids[1:4]
    old_name = eng.store.augments[old[0]]["name"]
    release_old = threading.Event()

    def fake(cfg, hero, augs):
        if augs[0]["name"] == old_name:
            release_old.wait(5)
            return {"pick": 0, "reason": "旧", "model": "m"}
        return {"pick": 1, "reason": "新", "model": "m"}

    monkeypatch.setattr(advisor, "analyze", fake)
    put_offer(eng, old)
    eng._ai_auto()
    put_offer(eng, new)  # 卡换了
    eng._ai_auto()
    assert wait_status(eng, "done")["result"]["reason"] == "新"
    release_old.set()
    time.sleep(0.3)
    ai = eng.snapshot()["ai"]
    assert ai["result"]["reason"] == "新" and ai["key"] == eng._ai_key
    assert any(v.get("reason") == "旧" for v in eng._ai_cache.values())  # 旧结果仍然缓存


def test_error_is_short_and_retryable(eng, monkeypatch):
    def boom(cfg, hero, augs):
        raise advisor.AdvisorError("AI 服务返回 500")

    monkeypatch.setattr(advisor, "analyze", boom)
    put_offer(eng, list(eng.store.augments)[:3])
    eng._ai_auto()
    assert wait_status(eng, "error")["error"] == "AI 服务返回 500"
