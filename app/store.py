# -*- coding: utf-8 -*-
"""会话与企业档案的落盘存储。一个文件一个会话，方便演示时直接翻看。"""
import json
import time
import uuid

from . import config


def _path(kind: str, sid: str):
    base = config.SESSIONS if kind == "session" else config.PROFILES
    return base / (sid + ".json")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def load(kind: str, sid: str) -> dict:
    p = _path(kind, sid)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(kind: str, sid: str, obj: dict) -> None:
    obj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p = _path(kind, sid)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def empty_profile() -> dict:
    return {
        "id": new_id(),
        "company": {"name": "", "city": "天津", "staff": None, "years": None},
        "product": {"category": "", "material": "", "powered": None, "size_cm": "",
                    "name_cn": "", "specs": {}},
        "certs": [],
        "capacity": {"monthly": "", "moq": "", "lead_time": ""},
        "market": {"region": "", "channel": "amazon"},
        "history": [],
        # 客户确认记录：只属于这个客户，不写进政策库
        "confirmations": {},
    }


def new_session() -> dict:
    s = {
        "id": new_id(),
        "state": "new",
        "profile_id": "",
        "messages": [],
        "pending": [],
        "artifacts": {},
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    s["profile_id"] = empty_profile()["id"]
    return s
