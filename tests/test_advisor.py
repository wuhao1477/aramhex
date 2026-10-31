"""第三方 AI：配置缺项不可用；请求格式（OpenAI 兼容、不带胜率）；返回值校验。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lolhex import advisor

AUGS = [{"name": "A", "desc": "甲"}, {"name": "B"}, {"name": "C", "desc": "丙"}]


@pytest.fixture
def fake_ai(monkeypatch):
    """本机假服务：记录收到的请求，回复 reply（可改）。"""
    seen = {"reply": {"status": 200, "content": '{"pick": 1, "reason": "稳"}'}, "requests": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["requests"].append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            rep = seen["reply"]
            if not body.get("stream"):  # 网关拒绝非流式请求
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"non-stream rejected"}')
                return
            if rep["status"] != 200:
                self.send_response(rep["status"])
                self.end_headers()
                return
            c = rep["content"]
            chunks = [{"choices": [{"delta": {"content": c[: len(c) // 2]}}]},
                      {"choices": [{"delta": {"content": c[len(c) // 2:]}}]}]
            if seen.get("wrap"):
                chunks = [{"data": x, "success": True} for x in chunks]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for x in chunks:
                self.wfile.write(b"data: " + json.dumps(x, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1/"
    monkeypatch.setenv("AI_BASE_URL", base)
    monkeypatch.setenv("AI_API_KEY", "sk-test-123")
    monkeypatch.setenv("AI_MODEL", "deepseek-test")
    yield seen
    srv.shutdown()


def test_unconfigured_when_any_key_missing(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://x.test")
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setenv("AI_MODEL", "")
    assert advisor.configured() is None


def test_configured_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", " https://x.test/v1/ ")
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setenv("AI_MODEL", "m")
    assert advisor.configured() == advisor.Config("https://x.test/v1", "k", "m")


def test_request_is_openai_compatible_and_has_no_winrate(fake_ai):
    cfg = advisor.configured()
    out = advisor.analyze(cfg, "提莫", AUGS)
    assert out == {"pick": 1, "reason": "稳", "model": "deepseek-test"}
    req = fake_ai["requests"][0]
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer sk-test-123"
    assert req["body"]["model"] == "deepseek-test" and req["body"]["temperature"] == 0
    assert req["body"]["stream"] is True  # 网关只收流式请求
    text = json.dumps(req["body"], ensure_ascii=False)
    assert "胜率" not in text.replace("不要提及胜率或排名", "") and "winrate" not in text.lower()
    assert "0. A：甲" in text and "1. B" in text


@pytest.mark.parametrize("content", [
    '{"pick": 3, "reason": "越界"}',
    '{"pick": -1, "reason": "负数"}',
    '{"pick": "0", "reason": "字符串"}',
    '{"pick": true, "reason": "布尔"}',
    '{"reason": "缺序号"}',
    '["不是对象"]',
    "不是 JSON",
])
def test_bad_replies_are_rejected(fake_ai, content):
    fake_ai["reply"]["content"] = content
    with pytest.raises(advisor.AdvisorError):
        advisor.analyze(advisor.configured(), "提莫", AUGS)


def test_http_error_is_short_and_has_no_key(fake_ai):
    fake_ai["reply"] = {"status": 401, "content": ""}
    with pytest.raises(advisor.AdvisorError) as e:
        advisor.analyze(advisor.configured(), "提莫", AUGS)
    assert "401" in str(e.value) and "sk-test" not in str(e.value)


def test_wrapped_gateway_reply_is_unwrapped(fake_ai):
    """网关把结果包在 data 里（实测 deepseek 网关如此）：照样能读出序号。"""
    fake_ai["wrap"] = True
    assert advisor.analyze(advisor.configured(), "提莫", AUGS)["pick"] == 1


def test_reason_is_trimmed():
    assert advisor.parse('{"pick": 0, "reason": "' + "长" * 200 + '"}')["reason"] == "长" * advisor.MAX_REASON
