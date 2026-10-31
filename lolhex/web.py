"""局域网网页：手机或另一台电脑用浏览器看同一份状态，触发 AI 分析，和 AI 聊天。

- 默认只监听 127.0.0.1；设置里 web_lan=true 才监听所有网卡。
- 令牌 web_token：第一次打开 http://<本机 IP>:<端口>/?t=<令牌>，之后靠 Cookie。
- 改动类请求（POST）必须带 X-Token 请求头：浏览器跨站不能随便加这个头，所以别的网页没法替你点按钮。
- 只有 HTTP，没有 HTTPS：令牌在局域网里是明文，只适合自己家里的 Wi-Fi。
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import advisor
from .webpage import PAGE

log = logging.getLogger(__name__)
COOKIE = "aramhex_token"
MODES = ("auto", "manual", "off")
MAX_BODY = 8192


def bind_host(settings) -> str:
    return "0.0.0.0" if getattr(settings, "web_lan", False) else "127.0.0.1"


def lan_ip() -> str:
    """本机在局域网里的地址。connect 到一个不会真正发包的地址，只让系统选出出口网卡。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _state(engine) -> dict:
    s = engine.snapshot()
    augs = []
    for sid in (s["offer"] or {}).get("slots") or []:
        a = engine.store.augments.get(str(sid)) if sid else None
        augs.append({"id": sid, "name": (a or {}).get("name") or ("未识别" if sid is None else sid)})
    return {"phase": s["phase"], "hero": (s.get("hero") or {}).get("name"),
            "augments": augs, "ai": s["ai"]}


class _Handler(BaseHTTPRequestHandler):
    server_version = "AramHex"

    def log_message(self, *args):  # 不把每次访问都写进日志
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict, extra: dict | None = None) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def _same(self, given: str) -> bool:
        return bool(given) and hmac.compare_digest(given.encode(), self.server.token.encode())

    def do_GET(self):
        url = urlsplit(self.path)
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        given = (parse_qs(url.query).get("t") or [""])[0] or (cookie[COOKIE].value if COOKIE in cookie else "")
        if not self._same(given):
            return self._send(401, "需要令牌：请用电脑设置里显示的地址打开".encode(), "text/plain; charset=utf-8")
        if url.path == "/":
            page = PAGE.replace("__TOKEN__", self.server.token).encode()
            cookie_hdr = f"{COOKIE}={self.server.token}; Path=/; HttpOnly; SameSite=Strict"
            return self._send(200, page, "text/html; charset=utf-8", {"Set-Cookie": cookie_hdr})
        if url.path == "/api/state":
            return self._json(200, _state(self.server.engine))
        self._json(404, {"error": "没有这个页面"})

    def do_POST(self):
        if not self._same(self.headers.get("X-Token", "")):
            return self._json(403, {"error": "令牌不对"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, MAX_BODY)) or b"{}")
        except (ValueError, TypeError):
            return self._json(400, {"error": "请求内容不是 JSON"})
        engine = self.server.engine
        if self.path == "/api/ai/refresh":
            engine.ai_refresh()
            return self._json(200, {"ok": True})
        if self.path == "/api/ai/mode":
            mode = body.get("mode") if isinstance(body, dict) else None
            if mode not in MODES:
                return self._json(400, {"error": "模式只能是 auto、manual、off"})
            engine.settings.ai_mode = mode
            engine.settings.save()
            return self._json(200, {"ok": True})
        if self.path == "/api/chat":
            return self._chat(body)
        self._json(404, {"error": "没有这个接口"})

    def _chat(self, body) -> None:
        message = str(body.get("message") or "").strip() if isinstance(body, dict) else ""
        if not message:
            return self._json(400, {"error": "消息不能为空"})
        cfg = advisor.configured()
        if cfg is None:
            return self._json(400, {"error": "第三方 AI 未配置：请在 .env 填写 AI_BASE_URL、AI_API_KEY、AI_MODEL"})
        st = _state(self.server.engine)
        names = "、".join(a["name"] for a in st["augments"] if a["name"] != "未识别") if st["augments"] else ""
        context = "、".join(x for x in (f"英雄 {st['hero']}" if st["hero"] else "", f"三选一 {names}" if names else "") if x)
        with self.server.chat_lock:
            history = self.server.history
            try:
                reply = advisor.chat(cfg, history, message, context)
            except advisor.AdvisorError as e:
                return self._json(502, {"error": str(e)})
            history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
            del history[:-20]  # 最多留 10 轮
        self._json(200, {"reply": reply})


class WebServer:
    def __init__(self, engine, host: str, port: int, token: str):
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.engine = engine
        self.httpd.token = token
        self.httpd.history = []
        self.httpd.chat_lock = threading.Lock()
        self.host = host
        threading.Thread(target=self.httpd.serve_forever, name="web", daemon=True).start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def urls(self) -> list[str]:
        hosts = [lan_ip()] if self.host == "0.0.0.0" else ["127.0.0.1"]
        return [f"http://{h}:{self.port}/?t={self.httpd.token}" for h in hosts]

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def start_from_settings(engine, settings) -> WebServer | None:
    """设置里打开了网页才启动；第一次启动时生成令牌并写回设置。"""
    if not getattr(settings, "web_enabled", False):
        return None
    if not settings.web_token:
        settings.web_token = secrets.token_urlsafe(16)
        settings.save()
    try:
        srv = WebServer(engine, bind_host(settings), int(settings.web_port), settings.web_token)
    except OSError as e:
        log.warning("网页没能启动（端口 %s）：%s", settings.web_port, e)
        return None
    log.info("网页已启动：%s", "；".join(srv.urls()))
    return srv
