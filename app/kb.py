# -*- coding: utf-8 -*-
"""知识库：合规规则卡与政策库。检索用轻量关键词打分，不引入向量库依赖。"""
import json
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def rules() -> list:
    return json.loads((config.DATA / "rules.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def policies() -> list:
    return json.loads((config.DATA / "policies.json").read_text(encoding="utf-8"))


def search_rules(category: str, market: str, text: str = "", limit: int = 6, powered=None,
                 form: str = "complete") -> list:
    text = (text or "").lower()
    scored = []
    for r in rules():
        if r.get("category") not in (category, "any"):
            continue
        if r.get("market") not in (market, "any"):
            continue
        # 带电类规则对非带电产品直接排除，不能靠打分往下压
        if r.get("powered_only") and not powered:
            continue
        # 整车规则与部件规则互斥：卖夹器不能给整车标准
        if r.get("applies_to") and r["applies_to"] != form:
            continue
        score = 1
        if r.get("category") == category:
            score += 3
        if r.get("market") == market:
            score += 3
        for kw in r.get("keywords", []):
            if kw and kw.lower() in text:
                score += 1
        scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    return [r for _, r in scored[:limit]]


def rules_for_market(market: str) -> list:
    return [r for r in rules() if r.get("market") in (market, "any")]


def match_policies(profile: dict, limit: int = 5) -> list:
    city = (profile.get("company", {}).get("city") or "天津")
    cat = profile.get("product", {}).get("category", "")
    scored = []
    for p in policies():
        score = 1
        if city in p.get("region", ""):
            score += 3
        if cat and cat in p.get("categories", []):
            score += 2
        if not p.get("categories"):
            score += 1
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


def _save_policies(data: list) -> None:
    import json as _json
    import os
    path = config.DATA / "policies.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    policies.cache_clear()


def find_policy(pid: str):
    for p in policies():
        if p.get("id") == pid:
            return p
    return None


def save_draft(pid: str, draft: dict) -> bool:
    import json as _json
    path = config.DATA / "policies.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    hit = False
    for it in data:
        if it.get("id") == pid:
            it["draft"] = draft
            it["draft_at"] = __import__("time").strftime("%Y-%m-%d %H:%M")
            hit = True
    if hit:
        _save_policies(data)
    return hit


def save_materials(pid: str, data: dict) -> bool:
    import json as _json
    path = config.DATA / "policies.json"
    rows = _json.loads(path.read_text(encoding="utf-8"))
    hit = False
    for it in rows:
        if it.get("id") == pid:
            it["materials"] = data
            hit = True
    if hit:
        _save_policies(rows)
    return hit


def adopt_draft(pid: str) -> dict:
    """采纳草稿：写入正式字段并标记已核对——人已经比过，这一步就是签字。"""
    import json as _json
    import time
    path = config.DATA / "policies.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for it in data:
        if it.get("id") != pid:
            continue
        d = it.pop("draft", None) or {}
        for k in ("condition", "support", "deadline"):
            if d.get(k):
                it[k] = d[k]
        it["verified"] = True
        it["verified_at"] = time.strftime("%Y-%m-%d %H:%M")
        it["verified_by"] = it.get("verified_by") or "访客"
        it["reviewed_at"] = it["verified_at"]
        it["source_status"] = "ok"
        it.pop("draft_at", None)
        out = it
    if out:
        _save_policies(data)
    return out


def discard_draft(pid: str) -> bool:
    import json as _json
    import time
    path = config.DATA / "policies.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    hit = False
    for it in data:
        if it.get("id") == pid and it.get("draft"):
            it.pop("draft", None)
            it.pop("draft_at", None)
            it["source_status"] = "ignored"
            it["ignored_at"] = time.strftime("%Y-%m-%d %H:%M")
            hit = True
    if hit:
        _save_policies(data)
    return hit


def mark_verified(kind: str, item_id: str, actor: str = "") -> bool:
    """把某个条目标记为已核对，并写回 JSON。kind: rule | policy
    actor 记录是谁确认的——这是客户侧的动作，不只是内部标记。
    """
    import json as _json
    import time as _time
    name = "rules.json" if kind == "rule" else "policies.json"
    path = config.DATA / name
    data = _json.loads(path.read_text(encoding="utf-8"))
    hit = False
    for it in data:
        if it.get("id") == item_id and not it.get("verified"):
            it["verified"] = True
            it["verified_by"] = actor or "本企业"
            it["verified_at"] = _time.strftime("%Y-%m-%d %H:%M")
            it["verified_hash"] = it.get("source_hash", "")
            hit = True
    if hit:
        path.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        (rules if kind == "rule" else policies).cache_clear()
    return hit


def progress() -> dict:
    r, p = rules(), policies()
    return {
        "rules": [sum(1 for x in r if x.get("verified")), len(r)],
        "policies": [sum(1 for x in p if x.get("verified")), len(p)],
    }


def find_rule(rule_id: str):
    for r in rules():
        if r.get("id") == rule_id:
            return r
    return None
