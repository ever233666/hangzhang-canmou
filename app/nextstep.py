# -*- coding: utf-8 -*-
"""根据档案与产出物的当前状态，算出「下一步该做什么」。
全部由状态推导，不经过模型——这类问题答错比不答更糟。
"""

import json

from . import config

DONE, DOING, TODO = "done", "doing", "todo"
MARK = {DONE: "✅", DOING: "🔄", TODO: "⬜"}


_guides = None


def guides() -> dict:
    global _guides
    if _guides is None:
        _guides = json.loads((config.DATA / "guides.json").read_text(encoding="utf-8"))
    return _guides


def render_guide(key: str) -> str:
    g = guides().get(key)
    if not g:
        return "这部分我还没有整理，先按下一步清单走。"
    lines = [g["title"]]
    for i, p in enumerate(g["points"], 1):
        lines.append("%d. %s" % (i, p))
    lines.append("注：" + g["caution"])
    return "\n".join(lines)


def build(profile: dict, artifacts: dict) -> dict:
    prof = profile or {}
    art = artifacts or {}
    prod = prof.get("product") or {}
    comp = art.get("compliance") or []
    listing = art.get("listing") or {}
    pol = art.get("policies") or []
    certs = prof.get("certs") or []

    steps = []

    # 1 合规确认
    pending = [c for c in comp if not (c.get("have") or c.get("confirmed"))]
    if not comp:
        steps.append((TODO, "生成合规清单", "先描述产品，拿到这份货要过的合规项"))
    elif pending:
        steps.append((DOING, "逐条确认合规清单", "还有 %d 条没确认或没登记资质，点开原文看完再标注" % len(pending)))
    else:
        steps.append((DONE, "合规清单已确认", "全部条目已有结论"))

    # 2 缺口资质
    if comp:
        gap = [c for c in comp if not c.get("have") and c.get("severity") == "must"]
        if gap:
            steps.append((TODO, "补办 %d 项强制资质" % len(gap),
                          "先办：" + "、".join(g["title"][:12] for g in gap[:3])))
        elif certs:
            steps.append((DONE, "资质齐备", "档案已登记：" + "、".join(certs)))
        else:
            steps.append((DONE, "无需额外资质", "当前清单没有强制认证项"))

    # 3 上架准备
    if listing:
        steps.append((DOING, "把 listing 上架", "复制标题与五点，补齐主图、A+ 页面、GTIN"))
    else:
        steps.append((TODO, "生成 listing", "还没有可上架的商品页文案"))

    # 4 平台与品牌
    steps.append((TODO, "平台资质与品牌保护", "开店铺、品牌备案、注册目标国商标，防跟卖"))

    # 5 物流报关
    steps.append((TODO, "物流与报关", "确认 HS 编码（以海关归类为准）、订舱、原产地证、头程"))
    steps.append((TODO, "收汇与出口退税", "开外币账户、办理退税备案，确认单据链完整"))

    # 7 政策申报
    if pol:
        got = [p for p in pol if p.get("confirmed")]
        if got and any(p.get("materials") for p in got):
            steps.append((DOING, "申报补贴", "材料清单已生成，按清单逐项准备后递交"))
        else:
            steps.append((TODO, "申领可申报补贴", "挑一条政策确认原文，生成材料清单"))

    done = sum(1 for s, _, _ in steps if s == DONE)
    return {
        "steps": [{"status": s, "title": t, "hint": h} for s, t, h in steps],
        "progress": [done, len(steps)],
    }


def render(result: dict) -> str:
    lines = ["按你的档案，出海还差这几步（%d/%d 已完成）：" % tuple(result["progress"])]
    for i, s in enumerate(result["steps"], 1):
        lines.append("%d. %s %s" % (i, MARK[s["status"]], s["title"]))
        if s["hint"]:
            lines.append("　　" + s["hint"])
    lines.append("想细看哪一步，直接问我。")
    return "\n".join(lines)
