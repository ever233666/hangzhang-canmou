# -*- coding: utf-8 -*-
"""极简 OpenAI 兼容客户端。只用标准库，避免任何安装步骤。
文本与视觉可以走两个不同的端点（比如文本 DeepSeek、视觉智谱）。
"""
import json
import time
import urllib.error
import urllib.request

from . import config

_usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "failures": 0}


def usage() -> dict:
    return dict(_usage)


def loads(text: str, fallback: dict) -> dict:
    """尽最大努力从模型输出里抠出 JSON，失败返回 fallback。"""
    if not text:
        return fallback
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 3:
            t = parts[1]
            if t.lower().startswith("json"):
                t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                return fallback
        return fallback


def _post(base: str, path: str, payload: dict, key: str, timeout: int = 45) -> dict:
    url = base + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            last = RuntimeError("HTTP %s: %s" % (e.code, detail))
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:
            last = e
        time.sleep(0.8 * (attempt + 1))
    _usage["failures"] += 1
    raise last  # type: ignore[misc]


def _count(data: dict) -> None:
    _usage["calls"] += 1
    u = data.get("usage") or {}
    _usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
    _usage["completion_tokens"] += int(u.get("completion_tokens") or 0)


def chat(messages: list, json_mode: bool = False, temperature: float = 0.4, max_tokens: int = 1200) -> str:
    if config.MOCK:
        raise RuntimeError("MOCK")
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post(config.LLM_BASE_URL, "/chat/completions", payload, config.LLM_API_KEY)
    _count(data)
    return (data["choices"][0]["message"].get("content") or "").strip()


def chat_json(messages: list, fallback: dict, temperature: float = 0.3, max_tokens: int = 1200) -> dict:
    """要求模型返回 JSON；任何异常都退化成 fallback，绝不把错误抛给界面。"""
    if config.MOCK:
        return fallback
    try:
        raw = chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        return loads(raw, fallback)
    except Exception:
        return fallback


def vision(image_b64: str, mime: str, prompt: str) -> dict:
    """识图。调用方需先确认 config.VISION_READY。"""
    if config.MOCK or not config.VISION_READY:
        raise RuntimeError("vision not configured")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, image_b64)}},
    ]
    payload = {
        "model": config.VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    data = _post(config.VISION_BASE_URL, "/chat/completions", payload, config.VISION_API_KEY)
    _count(data)
    return loads((data["choices"][0]["message"].get("content") or "").strip(), {})
