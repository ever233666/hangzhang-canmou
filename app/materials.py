# -*- coding: utf-8 -*-
"""客户确认政策后，生成一份可直接照着准备的材料清单。
不承诺能批，只把"要准备什么"摊开。
"""
import json

from . import config, llm

SYSTEM = """你是企业申报顾问。只根据这条政策的内容，列出申报需要准备的材料。
输入里不含任何企业信息——这份清单是「这条政策要什么」，不是「这家企业缺什么」，因此可以跨企业复用。
规则：
1. 只列这条政策真正会要求的材料，不写通用套话。
2. 每项写清是什么、由谁出、大概要多久能拿到。
3. 材料数量 5—8 项，按准备顺序排列。
4. 不确定的，写"向主管部门确认"，不要编。
5. days 字段只写耗时，例如 "1—3 天" 或 "1—2 周"，不要写状态描述。
只返回 JSON：
{"items": [{"name": "", "owner": "", "days": "", "note": ""}],
 "first_step": "一句话说明第一步该做什么",
 "caution": "一句话提醒最容易卡住的地方"}"""


def build(policy: dict, profile: dict) -> dict:
    fallback = {
        "items": [
            {"name": "营业执照副本", "owner": "企业", "days": "1", "note": "经营范围需覆盖申报口径"},
            {"name": "上年度审计报告", "owner": "会计师事务所", "days": "5—10", "note": "需盖章原件"},
            {"name": "申报表", "owner": "企业", "days": "1", "note": "按当年模板填写"},
            {"name": "相关佐证材料", "owner": "企业", "days": "2", "note": "合同、发票、出口数据"},
        ],
        "first_step": "先打电话给主管部门确认今年是否受理、截止到哪天",
        "caution": "材料格式与盖章要求每年会变，以当年通知为准",
    }
    if config.MOCK:
        return fallback

    # 刻意不带企业信息：清单只随政策变，才能安全地跨客户缓存
    payload = {
        "政策名称": policy.get("name"),
        "发文机构": policy.get("source"),
        "申报条件": policy.get("condition"),
        "支持方式": policy.get("support"),
        "截止时间": policy.get("deadline"),
    }
    got = llm.chat_json(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        fallback=fallback, max_tokens=900)
    out = dict(fallback)
    items = got.get("items")
    if isinstance(items, list) and items:
        cleaned = []
        for it in items[:8]:
            if isinstance(it, dict) and it.get("name"):
                cleaned.append({
                    "name": str(it.get("name"))[:40],
                    "owner": str(it.get("owner") or "企业")[:20],
                    "days": str(it.get("days") or "—")[:10],
                    "note": str(it.get("note") or "")[:60],
                })
        if cleaned:
            out["items"] = cleaned
    for k in ("first_step", "caution"):
        if isinstance(got.get(k), str) and got[k].strip():
            out[k] = got[k][:120]
    return out
