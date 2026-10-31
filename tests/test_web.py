"""局域网网页：令牌、Cookie、X-Token、模式切换、聊天。用假引擎和本机临时端口。"""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from lolhex import web
from lolhex.config import Settings

TOKEN = "tok-123"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走系统代理


class FakeEngine:
    def __init__(self, settings):
        self.settings = settings
        self.store = SimpleNamespace(augments={"1001": {"name": "泰坦的坚决"}, "1002": {"name": "尖端发明家"}})
        self.refreshed = 0

    def snapshot(self):
        return {"phase": "ingame", "hero": {"name": "提莫"},
                "offer": {"slots": ["1001", "1002", None]},
                "ai": {"status": "idle", "key": None, "result": None, "error": None,
                       "mode": self.settings.ai_mode, "configured": False}}

    def ai_refresh(self):
        self.refreshed += 1


def call(port, method, path, headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data, headers=headers or {})
    try:
        with OPENER.open(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAMHEX_HOME", str(tmp_path))
    monkeypatch.setattr(Settings, "save", lambda self, path=None: True)  # 测试不写用户目录
    for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    eng = FakeEngine(Settings(web_token=TOKEN))
    s = web.WebServer(eng, "127.0.0.1", 0, TOKEN)
    s.engine = eng
    yield s
    s.stop()


def test_bind_host_follows_lan_setting():
    assert web.bind_host(Settings()) == "127.0.0.1"
    assert web.bind_host(Settings(web_lan=True)) == "0.0.0.0"


def test_page_needs_token(srv):
    assert call(srv.port, "GET", "/")[0] == 401
    assert call(srv.port, "GET", "/?t=wrong")[0] == 401
    assert call(srv.port, "GET", "/api/state")[0] == 401


def test_token_in_url_sets_cookie_and_page(srv):
    code, headers, body = call(srv.port, "GET", f"/?t={TOKEN}")
    assert code == 200 and TOKEN.encode() in body and "__TOKEN__" not in body.decode()
    cookie = headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and f"aramhex_token={TOKEN}" in cookie


def test_state_with_cookie(srv):
    code, _, body = call(srv.port, "GET", "/api/state", headers={"Cookie": f"aramhex_token={TOKEN}"})
    st = json.loads(body)
    assert code == 200 and st["hero"] == "提莫" and st["phase"] == "ingame"
    assert [a["name"] for a in st["augments"]] == ["泰坦的坚决", "尖端发明家", "未识别"]


def test_post_needs_header_not_cookie(srv):
    cookie = {"Cookie": f"aramhex_token={TOKEN}"}
    assert call(srv.port, "POST", "/api/ai/refresh", headers=cookie, body={})[0] == 403
    assert srv.httpd.engine.refreshed == 0
    assert call(srv.port, "POST", "/api/ai/refresh", headers={"X-Token": TOKEN}, body={})[0] == 200
    assert srv.httpd.engine.refreshed == 1


def test_mode_switch_validates(srv):
    h = {"X-Token": TOKEN}
    assert call(srv.port, "POST", "/api/ai/mode", headers=h, body={"mode": "bogus"})[0] == 400
    assert srv.httpd.engine.settings.ai_mode == "auto"
    assert call(srv.port, "POST", "/api/ai/mode", headers=h, body={"mode": "manual"})[0] == 200
    assert srv.httpd.engine.settings.ai_mode == "manual"


def test_chat_unconfigured_says_where_to_set(srv):
    code, _, body = call(srv.port, "POST", "/api/chat", headers={"X-Token": TOKEN}, body={"message": "你好"})
    assert code == 400 and ".env" in json.loads(body)["error"]


def test_chat_roundtrip_keeps_history(srv, monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["messages"])
            if not body.get("stream"):  # 网关拒绝非流式请求
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            line = {"choices": [{"delta": {"content": f"回复{len(seen)}"}}]}
            self.wfile.write(b"data: " + json.dumps(line, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass

    ai = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=ai.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("AI_BASE_URL", f"http://127.0.0.1:{ai.server_address[1]}/v1")
        monkeypatch.setenv("AI_API_KEY", "k")
        monkeypatch.setenv("AI_MODEL", "m")
        h = {"X-Token": TOKEN}
        assert json.loads(call(srv.port, "POST", "/api/chat", headers=h, body={"message": "第一句"})[2])["reply"] == "回复1"
        assert json.loads(call(srv.port, "POST", "/api/chat", headers=h, body={"message": "第二句"})[2])["reply"] == "回复2"
        second = seen[1]
        assert [m["content"] for m in second[1:]] == ["第一句", "回复1", "第二句"]
        assert "提莫" in second[0]["content"] and "泰坦的坚决" in second[0]["content"]  # 当前对局信息给了 AI
        assert "胜率" not in json.dumps(second, ensure_ascii=False).replace("不要提及胜率或排名", "")
    finally:
        ai.shutdown()
