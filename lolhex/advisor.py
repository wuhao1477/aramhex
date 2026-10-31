"""第三方 AI 推荐：走 OpenAI 兼容的 /chat/completions，只看当前三选一。

配置来自 .env 或环境变量：AI_BASE_URL、AI_API_KEY、AI_MODEL；缺一项就不可用（configured() 为 None）。
发给 AI 的只有英雄名和三个海克斯的名字与说明，不发胜率、排名、账号和游戏内其他信息。
不把助手自己的推荐发过去：AI 的结果要和默认推荐分开看。
输出强制为 {"pick": 0|1|2, "reason": "..."}，格式不对、序号越界直接报错，界面不显示。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

TIMEOUT_S = 30
MAX_REASON = 80


class AdvisorError(RuntimeError):
    """给界面看的短提示，不含密钥。"""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str


def configured() -> Config | None:
    env = {k: (os.environ.get(k) or "").strip() for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL")}
    if not all(env.values()):
        return None
    return Config(env["AI_BASE_URL"].rstrip("/"), env["AI_API_KEY"], env["AI_MODEL"])


def build_messages(hero: str, augments: list[dict]) -> list[dict]:
    """augments: [{"name": ..., "desc": ...}, ...] 按屏幕从左到右。"""
    options = "\n".join(f"{i}. {a.get('name') or '未知'}" + (f"：{a['desc'][:120]}" if a.get("desc") else "")
                        for i, a in enumerate(augments))
    return [
        {"role": "system", "content": "你是英雄联盟「海克斯大乱斗」的选择顾问。只能从给出的选项里选一个，"
                                      "不要编造数据，不要提及胜率或排名。只输出 JSON。"},
        {"role": "user", "content": f"英雄：{hero or '未知'}\n三选一：\n{options}\n"
                                    f"只输出 JSON：{{\"pick\": 选项序号 0、1 或 2, \"reason\": \"一句话理由，不超过 40 字\"}}"},
    ]


def parse(text: str, n: int = 3) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as e:
        raise AdvisorError("AI 返回的不是 JSON") from e
    pick = data.get("pick") if isinstance(data, dict) else None
    # bool 是 int 的子类，true 不能当成 1
    if type(pick) is not int or not 0 <= pick < n:
        raise AdvisorError("AI 返回的序号不在选项范围内")
    reason = str(data.get("reason") or "").strip()[:MAX_REASON]
    return {"pick": pick, "reason": reason}


def _unwrap(chunk: dict) -> dict:
    # 有的网关把结果包在 {"data": {...}, "success": true} 里，剥掉这一层
    if isinstance(chunk, dict) and "choices" not in chunk and isinstance(chunk.get("data"), dict):
        return chunk["data"]
    return chunk


def ask(cfg: Config, messages: list[dict], *, json_mode: bool = True, max_tokens: int = 1200) -> str:
    # 一律用流式：网关拒绝非流式请求。把 SSE 的增量拼成完整回复。
    body = {"model": cfg.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens, "stream": True}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(
            f"{cfg.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {cfg.api_key}", "Accept": "text/event-stream"},
            json=body,
            timeout=(10, TIMEOUT_S),
            stream=True,
        )
    except requests.RequestException as e:
        raise AdvisorError(f"连不上 AI 服务：{type(e).__name__}") from e
    if r.status_code != 200:
        r.close()
        raise AdvisorError(f"AI 服务返回 {r.status_code}")
    parts: list[str] = []
    r.encoding = "utf-8"  # 流式回复没写 charset 时 requests 会按 ISO-8859-1 解，中文会乱码
    try:
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            delta = _unwrap(json.loads(payload))["choices"][0].get("delta") or {}
            if delta.get("content"):
                parts.append(delta["content"])
    except requests.RequestException as e:
        raise AdvisorError(f"AI 回复中断：{type(e).__name__}") from e
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise AdvisorError("AI 返回格式不对") from e
    finally:
        r.close()
    if not parts:
        raise AdvisorError("AI 没有返回内容")
    return "".join(parts)


def analyze(cfg: Config, hero: str, augments: list[dict]) -> dict:
    result = parse(ask(cfg, build_messages(hero, augments)), n=len(augments))
    return {**result, "model": cfg.model}


def chat(cfg: Config, history: list[dict], message: str, context: str = "") -> str:
    """多轮对话。history 是之前的 user/assistant 消息，只取最近 10 条；context 是当前对局的文字说明。"""
    system = "你是英雄联盟「海克斯大乱斗」的助手。用中文简短回答。不要提及胜率或排名；不确定就直说。"
    if context:
        system += f"\n当前对局：{context}"
    messages = [{"role": "system", "content": system}, *history[-10:], {"role": "user", "content": message[:1000]}]
    return ask(cfg, messages, json_mode=False, max_tokens=1500).strip()
