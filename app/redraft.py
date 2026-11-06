# -*- coding: utf-8 -*-
"""检测到来源变化后，让模型起草一版修订。
注意：这里只产出『草稿』，绝不直接覆盖正式字段——拍板权在人。
"""
import re

from . import config, llm

SYSTEM = """你是政策文本编辑。输入是一条政策在知识库里的现有摘要，以及来源网页的正文。
你要用正文里的信息，更新三个字段的表述。

硬性规则：
1. 只能使用正文中出现的信息。正文没有提到的字段，返回空字符串 ""，绝对不要写「未提及」「无」「不详」之类的话——空字符串表示保留原值。
2. 不得改变政策名称、发文机构、政策层级。
3. 每个字段不超过 80 字，写具体条件与标准，不写「大力支持」「积极推动」这类空话。
4. 若正文与现有摘要实质一致，fields_changed 返回空数组，change_note 写「未发现实质变化」。

只返回 JSON：
{"condition": "", "support": "", "deadline": "",
 "change_note": "一句话说明改了什么",
 "fields_changed": ["condition", "support", "deadline"]}"""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def draft(policy: dict, text: str) -> dict:
    fallback = {
        "condition": policy.get("condition", ""),
        "support": policy.get("support", ""),
        "deadline": policy.get("deadline", ""),
        "change_note": "模型不可用，未生成草稿",
        "fields_changed": [],
    }
    if not text.strip():
        fallback["change_note"] = "抓不到正文，无法起草"
        return fallback
    if config.MOCK:
        fallback["change_note"] = "样例模式：未调用模型"
        return fallback

    payload = {
        "政策名称": policy.get("name"),
        "发文机构": policy.get("source"),
        "现有摘要": {
            "condition": policy.get("condition", ""),
            "support": policy.get("support", ""),
            "deadline": policy.get("deadline", ""),
        },
        "来源正文": text[:6000],
    }
    import json
    got = llm.chat_json(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        fallback=fallback, max_tokens=900)

    out = dict(fallback)
    # 兜底：模型爱把「原文未提及」当成值写进来，那会把真实条款冲成一句废话
    PLACEHOLDER = ("未提及", "原文未提及", "未找到", "文中未", "未明确", "不详", "无相关")

    for k in ("condition", "support", "deadline"):
        v = got.get(k)
        if not isinstance(v, str) or not v.strip():
            out[k] = policy.get(k, "")          # 空 -> 保留原值
            continue
        v = _clean(v)[:200]
        if len(v) < 24 and any(w in v for w in PLACEHOLDER):
            out[k] = policy.get(k, "")          # 占位词 -> 保留原值
            continue
        out[k] = v

    if isinstance(got.get("change_note"), str) and got["change_note"].strip():
        out["change_note"] = _clean(got["change_note"])[:200]

    ch = got.get("fields_changed")
    ch = [x for x in ch if x in ("condition", "support", "deadline")] if isinstance(ch, list) else []
    # 实际没变的字段不算 changed
    ch = [x for x in ch if out[x] != policy.get(x, "")]
    out["fields_changed"] = ch
    if not ch:
        out["change_note"] = out["change_note"] or "未发现实质变化"
    return out


def diff(old: dict, new: dict) -> list:
    """给界面用的逐字段对比。"""
    rows = []
    for k, label in (("condition", "申报条件"), ("support", "支持方式"), ("deadline", "截止时间")):
        a, b = (old.get(k) or "").strip(), (new.get(k) or "").strip()
        if a != b:
            rows.append({"field": k, "label": label, "before": a, "after": b})
    return rows
