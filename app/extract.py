# -*- coding: utf-8 -*-
"""把用户的任意一句话，抽成对企业档案的结构化补丁。
这是「像聊天一样改档案」的核心：不再按固定问题走，而是每句话都尝试理解。
"""
import json

from . import config, llm

SYSTEM = """你是企业档案抽取器。从用户这句话里，抽取能**确定**的字段，输出 JSON 补丁。
可用字段（只输出的你确定的，没提到的一律不出现）：
  product.name_cn      中文品名，如"浴室吸水地垫"
  product.category     只能是 bike / carpet / hardware / other
  product.material     材质，如"硅藻泥""铝合金"
  product.powered      是否带电，true / false
  product.specs.size   尺寸，如"60x40cm"
  product.specs.weight 重量，如"1.2kg"
  product.specs.moq    起订量，如"100片"
  product.specs.lead_time 交期，如"20天"
  market.region        eu / us / uk
  company.name         企业名称
  certs                已持有的认证或测试报告，数组，如 ["CE","EN 15194","UL 2849"]

规则：
1. 用户否认当前判断（"不是X""你认错了"）但没说是什么：输出 {"clear": ["product.name_cn","product.category"]}，patch 为空。
2. 用户否认并给出新答案（"不是X，是Y"）：patch 里给 Y 对应的字段，category 一并给出。
3. category 判断：地垫/脚垫/门垫/地毯/浴室垫 → carpet；车架/配件/整车 → bike；合页/铰链/货架/五金 → hardware；拿不准就别输出。
4. 数值保留单位，原样抄，不要换算。
5. 用户只是闲聊、提问、道谢：patch 为空，clear 为空。
6. 用户说"我们有 CE 认证""做过 EN 15194 测试"：抽到 certs，代号保持大写原样。
   若用户说"没有任何认证""还没做认证"：patch 为空，clear 里给 "certs"。

只返回 JSON：{"patch": {}, "clear": [], "note": "一句话说明你理解到了什么"}"""


def patch(text: str, profile: dict) -> dict:
    """返回 {"patch": {...}, "clear": [...], "note": ""}；MOCK 或失败时返回空。"""
    empty = {"patch": {}, "clear": [], "note": ""}
    if config.MOCK or not text.strip():
        return empty
    ctx = {
        "当前档案": {
            "name_cn": profile.get("product", {}).get("name_cn", ""),
            "category": profile.get("product", {}).get("category", ""),
            "material": profile.get("product", {}).get("material", ""),
            "specs": profile.get("product", {}).get("specs", {}),
            "market": profile.get("market", {}).get("region", ""),
        },
        "用户这句话": text,
    }
    got = llm.chat_json(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
        fallback=empty, max_tokens=500)
    if not isinstance(got, dict):
        return empty
    out = {"patch": got.get("patch") if isinstance(got.get("patch"), dict) else {},
           "clear": [c for c in got.get("clear", []) if isinstance(c, str)] if isinstance(got.get("clear"), list) else [],
           "note": got.get("note") if isinstance(got.get("note"), str) else ""}
    return out


GUESS_SYSTEM = """你熟悉中国出口商品。根据产品名称与品类，判断它的主要材质。
规则：
1. 只回答最常见的那种材质，用中文，2—6 个字，例如「涤纶」「不锈钢」「实木」「羊毛」。
2. 如果这个产品材质差异很大（如家具可能是实木也可能是板材），confidence 填 low。
3. 完全判断不了，material 返回空串。
只返回 JSON：{"material": "", "confidence": "high|medium|low", "reason": "一句话"}"""


def guess_material(name: str, category: str) -> dict:
    fallback = {"material": "", "confidence": "low", "reason": ""}
    if config.MOCK or not name:
        return fallback
    got = llm.chat_json(
        [{"role": "system", "content": GUESS_SYSTEM},
         {"role": "user", "content": json.dumps({"产品": name, "品类": category}, ensure_ascii=False)}],
        fallback=fallback, max_tokens=200)
    if not isinstance(got, dict):
        return fallback
    return {"material": str(got.get("material") or "")[:12],
            "confidence": str(got.get("confidence") or "low")[:8],
            "reason": str(got.get("reason") or "")[:60]}


def _flatten(obj: dict, prefix: str = "") -> dict:
    """模型常常返回 {"product.name_cn": ...} 这种扁平键，两种都收。"""
    flat = {}
    for k, v in (obj or {}).items():
        key = (prefix + "." + k) if prefix else k
        if isinstance(v, dict) and v:
            flat.update(_flatten(v, key))
        elif v not in (None, ""):
            flat[key] = v
    return flat


def apply(profile: dict, result: dict) -> list:
    """把补丁写进档案，返回被改动的字段名列表。"""
    changed = []
    prod = profile.setdefault("product", {})
    mk = profile.setdefault("market", {})
    co = profile.setdefault("company", {})

    for path in result.get("clear", []):
        if path == "certs":
            profile["certs"] = []
            changed.append("certs")
            continue
        if path.startswith("product.") and path.count(".") == 1:
            field = path.split(".", 1)[1]
            prod[field] = None if field == "powered" else ""
            changed.append(path)

    for key, val in _flatten(result.get("patch", {})).items():
        if key in ("product.name_cn", "product.category", "product.material"):
            field = key.split(".", 1)[1]
            text = str(val).strip()[:40]
            if text and text != prod.get(field):
                prod[field] = text
                changed.append(key)
        elif key == "product.powered":
            powered = val if isinstance(val, bool) else str(val).lower() in ("true", "yes", "是", "带电")
            prod["powered"] = powered
            changed.append(key)
        elif key.startswith("product.specs."):
            field = key.split(".")[-1]
            specs = prod.setdefault("specs", {})
            text = str(val).strip()[:30]
            if text and specs.get(field) != text:
                specs[field] = text
                changed.append(key)
        elif key == "market.region":
            reg = str(val).strip().lower()
            if reg in ("eu", "us", "uk"):
                mk["region"] = reg
                changed.append(key)
        elif key == "certs":
            vals = val if isinstance(val, list) else [x for x in str(val).replace("、", ",").split(",")]
            clean = []
            for v in vals:
                t = str(v).strip()[:20]
                if t and t.lower() not in [c.lower() for c in clean]:
                    clean.append(t)
            if clean:
                profile["certs"] = clean[:8]
                changed.append("certs")
        elif key == "company.name":
            text = str(val).strip()[:40]
            if text:
                co["name"] = text
                changed.append(key)
    return changed
