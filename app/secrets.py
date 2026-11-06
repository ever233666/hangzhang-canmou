# -*- coding: utf-8 -*-
"""BYOK：客户自带模型密钥。只存服务端，浏览器永远拿不到明文。"""
import json

from . import config

PATH = config.DATA / "byok.json"


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply() -> bool:
    """把已保存的 BYOK 配置写进运行时配置。返回是否生效。"""
    d = _load()
    if not (d.get("base_url") and d.get("api_key")):
        return False
    config.LLM_BASE_URL = d["base_url"].rstrip("/")
    config.LLM_API_KEY = d["api_key"].strip()
    config.LLM_MODEL = (d.get("model") or config.LLM_MODEL).strip()
    if d.get("vision_model"):
        config.VISION_MODEL = d["vision_model"].strip()
        config.VISION_BASE_URL = config.LLM_BASE_URL
        config.VISION_API_KEY = config.LLM_API_KEY
    config.MOCK = False
    return True


def save(base_url: str, api_key: str, model: str, vision_model: str = "") -> dict:
    d = {"base_url": (base_url or "").strip(), "api_key": (api_key or "").strip(),
         "model": (model or "").strip(), "vision_model": (vision_model or "").strip()}
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    apply()
    return masked()


def masked() -> dict:
    d = _load()
    if not d.get("api_key"):
        return {"configured": False}
    k = d["api_key"]
    return {"configured": True,
            "base_url": d.get("base_url", ""),
            "model": d.get("model", ""),
            "vision_model": d.get("vision_model", ""),
            "key": (k[:6] + "…" + k[-4:]) if len(k) > 12 else "已配置"}


def clear() -> None:
    if PATH.exists():
        PATH.unlink()
