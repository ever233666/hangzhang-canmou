# -*- coding: utf-8 -*-
"""合规护栏：用代码兜住模型最容易犯的错——编认证。
提示词是「请勿」，这里是「不许」。
"""
import re

# 认证与标准代号：出现即要求档案里有对应资质
CERT_PATTERNS = [
    (r"\bCE\b", "CE"),
    (r"\bUKCA\b", "UKCA"),
    (r"\bUL[\s-]?\d{3,5}\b", "UL"),
    (r"\bISO[\s-]?\d{4,5}\b", "ISO"),
    (r"\bEN[\s-]?\d{3,5}\b", "EN"),
    (r"\bFCC\b", "FCC"),
    (r"\bRoHS\b", "RoHS"),
    (r"\bREACH\b", "REACH"),
    (r"OEKO-?TEX", "OEKO-TEX"),
    (r"\bASTM[\s-]?[A-Z]?\d{2,5}\b", "ASTM"),
    (r"\bCPSC\b", "CPSC"),
    (r"\bGPSR\b", "GPSR"),
    (r"\bCPSIA\b", "CPSIA"),
    (r"\bProp(?:osition)?\s?65\b", "Prop 65"),
    (r"\bTB[\s-]?117\b", "TB 117"),
    (r"\b16\s?CFR\s?\d+", "16 CFR"),
    (r"\bLFGB\b", "LFGB"),
    (r"\bFDA\b", "FDA"),
]

# ---------- 合规结论：模型最爱下的判断，一句都不许留 ----------
# 「已基本合规」「可以放心出口」这类结论，是参赛作品最容易被评委抓住的硬伤：
# 工厂没做过检测，我们也没看过检测报告，凭什么说合规。
VERDICT_FIX = [
    (r"(?:已|已经)?(?:基本|完全|大致)?合规(?:了)?(?:[，,。]|$)",
     "是否满足仍需按检测报告逐项核对。"),
    (r"(?:基本|完全)?符合(?:美国|欧盟|英国|日本|东盟|当地)?(?:的)?(?:相关)?(?:法规|要求|标准)"
     r"(?:[，,]?(?:可以|即可)(?:放心)?(?:出口|销售|上架|发货))",
     "具体要求按官方口径逐项核对，能否放行由海关与平台判定"),
    (r"(?:可以|能够|即可)(?:放心)?(?:出口|销售|上架)(?:了)?(?:[，,。]|$)",
     "能否放行要由海关和平台判定。"),
    (r"没有(?:任何)?问题(?:[，,]?(?:可以|即可)(?:放心)?(?:出口|销售|上架))?[，,。]?",
     "可能仍有缺口，建议逐项核对。"),
    (r"只需注意", "除以下事项外，还可能有未列到的要求："),
]
VERDICT_NOTE = "先说明：我不能判定你的产品已经合规，只能列出要求和缺口。"

# 金额与周期：模型给的报价十有八九是编的，检测机构不同价差三倍
MONEY = re.compile(r"(?:约|大约|大概|预计|估计)?\s*\d[\d,\.]*\s*(?:[-–—~至到]\s*\d[\d,\.]*)?\s*"
                   r"(?:美元|美金|USD|元人民币|万元|元)")
WEEKS = re.compile(r"\d+(?:\.\d+)?\s*[-–—~]?\s*\d*\s*(?:个工作日|工作日|周)")
FACT_FIX = [
    (r"CPSC\s*认证", "CPSC 合规要求（CPSC 是监管机构，不发证书）"),
    (r"FDA\s*认证", "FDA 注册/列名（FDA 不发「认证」）"),
    (r"CE\s*认证", "CE 标识（企业自我声明，并留存技术文件备查）"),
]


def scrub_verdict(text: str) -> tuple:
    """把模型给出的合规结论改写成「要求清单 + 缺口」。返回 (文本, 提示)。"""
    if not text:
        return text, []
    warns = []
    for pat, repl in FACT_FIX:
        m = re.search(pat, text, re.I)
        if m:
            text = re.sub(pat, repl, text, flags=re.I)
            warns.append("已纠正错误说法「%s」" % m.group(0))
    if MONEY.search(text):
        text = MONEY.sub("以机构报价为准", text)
        warns.append("已隐去具体金额（模型无法核实报价）")
    if WEEKS.search(text):
        text = WEEKS.sub("数周", text)
        warns.append("已隐去具体周期")
    # 替换完会留下「以机构报价为准左右」「……为准，以机构报价为准」这种尾巴
    text = re.sub(r"以机构报价为准\s*(左右|上下|以内|以下)", "以机构报价为准", text)
    for _ in range(2):
        text = re.sub(r"以机构报价为准[，,、]?\s*(?:大致|大概|约)?\s*以机构报价为准",
                      "以机构报价为准", text)
    text = re.sub(r"以机构报价为准\s*[，,。]?\s*。", "以机构报价为准。", text)
    hit = False
    for pat, repl in VERDICT_FIX:
        if re.search(pat, text):
            text = re.sub(pat, repl, text)
            hit = True
    if hit:
        text = VERDICT_NOTE + "\n\n" + text
        warns.append("已拦下合规结论，改为要求清单")
    return text, warns


# ---------- 未证实的卖点：和编认证一样危险 ----------
# 「BPA-free」「non-toxic」「100+ pieces」这类话，没有检测报告和实际数量就不能写。
# 买家按 listing 下单，写错要退货，甚至被平台判虚假描述。
POWER_WORDS = re.compile(
    r"\b(e-?bikes?|electric|electrical|batter(?:y|ies)|cordless|rechargeable|"
    r"usb[\s-]?charg\w*|lithium[\s-]?ion|power bank)\b", re.I)

UNVERIFIED = [
    (re.compile(r"\bBPA[\s-]?free\b", re.I), "BPA-free"),
    (re.compile(r"\bnon[\s-]?toxic\b", re.I), "non-toxic"),
    (re.compile(r"\bfood[\s-]?grade\b", re.I), "food-grade"),
    (re.compile(r"\bmedical[\s-]?grade\b", re.I), "medical-grade"),
    (re.compile(r"\bFDA[\s-]+(approved|cleared|registered)\b", re.I), "FDA 批准"),
    (re.compile(r"\bCE[\s-]+(certified|marked|approved)\b", re.I), "CE 认证"),
    (re.compile(r"\bIP[X]?\d{1,2}\b", re.I), "防水等级"),
    (re.compile(r"\banti[\s-]?bacterial\b|\bantimicrobial\b", re.I), "抗菌"),
    (re.compile(r"\bsterile\b|\bsterilized\b", re.I), "无菌"),
]
QUANTITY = re.compile(r"\b\d{2,}\+?\s*(pieces?|pcs|blocks?|count|sets?)\b", re.I)

# 「100% 羊毛」有法定含义（FTC 羊毛法），客户只说了「羊毛」就不能替他把纯度写上
PURITY = re.compile(r"\b100(?:\.0)?\s*%\s*(?:natural\s+|pure\s+|genuine\s+)?"
                    r"(wool|cotton|leather|silk|linen|bamboo|polyester|nylon|down|feather|rubber|wood)",
                    re.I)


def scrub_claims(listing: dict, profile: dict) -> tuple:
    """档案里没有的，一条都不许写：电动件、检测类卖点、没给过的数量。"""
    if not isinstance(listing, dict):
        return listing, []
    warns = []
    caps = _allowed((profile or {}).get("certs") or [])
    prod = (profile or {}).get("product") or {}
    powered = prod.get("powered") is True
    known = " ".join([str(prod.get("name_cn") or "")] +
                     [str(v) for v in (prod.get("specs") or {}).values()])

    def hits_of(t: str) -> list:
        out = []
        if not powered and POWER_WORDS.search(t):
            out.append("带电/电动表述")
        for pat, label in UNVERIFIED:
            if not pat.search(t):
                continue
            if label == "CE 认证" and "ce" in caps:
                continue
            if label == "FDA 批准" and "fda" in caps:
                continue
            out.append(label)
        m = QUANTITY.search(t)
        if m:
            # 「50 pieces MOQ」是客户自己说的起订量，别当成编造——按数字比，不按整串比
            num = re.search(r"\d+", m.group(0))
            known_nums = set(re.findall(r"\d+", known))
            if not num or num.group(0) not in known_nums:
                out.append("没给过的数量（%s）" % m.group(0).strip())
        return out

    def soften(t: str) -> str:
        """把「100% 羊毛」降级成「羊毛」，保留卖点但不替客户下成分保证。"""
        if not PURITY.search(t):
            return t
        warns.append("已把「100%%」纯度声明改为不含纯度的写法：%s" % t[:36])
        return PURITY.sub(r"\1", t)

    listing["bullets"] = [soften(b) for b in (listing.get("bullets") or [])]
    if listing.get("description"):
        listing["description"] = soften(listing["description"])
    if listing.get("title"):
        listing["title"] = soften(listing["title"])

    kept = []
    for b in listing.get("bullets", []) or []:
        h = hits_of(b)
        if h:
            warns.append("已删除未经确认的「%s」：%s" % ("、".join(h), b[:46]))
            continue
        kept.append(b)
    listing["bullets"] = kept

    desc = listing.get("description") or ""
    if desc:
        sents = [s for s in SENT_SPLIT.split(desc) if not hits_of(s)]
        if len(sents) != len(SENT_SPLIT.split(desc)):
            warns.append("已从描述中删除含未证实卖点的句子")
        listing["description"] = " ".join(sents).strip()

    title = listing.get("title") or ""
    h = hits_of(title)
    if h:
        if not powered:
            title = POWER_WORDS.sub("", title)
        for pat, _label in UNVERIFIED:
            title = pat.sub("", title)
        listing["title"] = re.sub(r"\s{2,}", " ", title).strip(" -–|,")
        warns.append("已从标题中移除未证实的表述：%s" % "、".join(h))
    return listing, warns


# 无信息量形容词
FLUFF = ["durable", "safe", "high-quality", "high quality", "premium",
         "eco-friendly", "professional", "best-selling", "world-class"]

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _allowed(certs: list) -> str:
    return " | ".join((c or "").lower() for c in certs)


def _certs_in(text: str) -> list:
    hits = []
    for pat, name in CERT_PATTERNS:
        if re.search(pat, text, re.I):
            hits.append(name)
    return hits


DIM = re.compile(r"\d{2,4}\s*[x×X*]\s*\d{2,4}\s*(?:cm|mm|CM|MM)|\d{2,4}\s*(?:cm|mm)\b", re.I)


def scrub_specs(listing: dict, specs: dict) -> tuple:
    """档案里没有尺寸，就不许在 listing 里出现尺寸——编造规格和编造认证一样危险。"""
    warns = []
    if (specs or {}).get("size"):
        return listing, warns

    def bad(t: str) -> bool:
        return bool(DIM.search(t or ""))

    kept, dropped = [], []
    for b in listing.get("bullets", []) or []:
        if bad(b):
            dropped.append(b)
        else:
            kept.append(b)
    if dropped:
        listing["bullets"] = kept
        warns.append("档案未提供尺寸，已删除 %d 条含尺寸的表述（如「%s」）"
                     % (len(dropped), dropped[0][:40]))
    if bad(listing.get("title")):
        listing["title"] = DIM.sub("", listing.get("title")).strip(" -–|,")
        warns.append("已从标题中移除未提供的尺寸")
    desc = listing.get("description") or ""
    if desc:
        sents = [s for s in re.split(r"(?<=[.!?])\s+", desc) if not bad(s)]
        if len(sents) != len(re.split(r"(?<=[.!?])\s+", desc)):
            listing["description"] = " ".join(sents).strip()
            warns.append("已从描述中删除含尺寸的句子")
    return listing, warns


def scrub(listing: dict, certs: list) -> tuple:
    """返回 (清洗后的 listing, 警告列表)。只删认证类硬伤，形容词只提示。"""
    if not isinstance(listing, dict):
        return listing, []
    allow = _allowed(certs)
    warns = []

    def cert_ok(name: str) -> bool:
        return name.lower() in allow

    # 1. bullets
    kept = []
    for b in listing.get("bullets", []) or []:
        hits = _certs_in(b)
        bad = [h for h in hits if not cert_ok(h)]
        if bad:
            warns.append("已删除宣称「%s」的 bullet：%s" % ("、".join(bad), b[:50]))
            continue
        fluff = [w for w in FLUFF if w in b.lower()]
        if fluff:
            warns.append("措辞含无信息量形容词（%s），建议改写：%s" % ("、".join(fluff[:2]), b[:40]))
        kept.append(b)
    listing["bullets"] = kept

    # 2. description：按句删
    desc = listing.get("description") or ""
    if desc:
        keep_sents = []
        for s in SENT_SPLIT.split(desc):
            hits = _certs_in(s)
            bad = [h for h in hits if not cert_ok(h)]
            if bad:
                warns.append("已从描述中删除含「%s」的句子" % "、".join(bad))
                continue
            keep_sents.append(s)
        listing["description"] = " ".join(keep_sents).strip()

    # 3. 标题里出现未证实认证，直接剥离
    title = listing.get("title") or ""
    hits = [h for h in _certs_in(title) if not cert_ok(h)]
    if hits:
        for pat, name in CERT_PATTERNS:
            if name in hits:
                title = re.sub(pat, "", title, flags=re.I)
        title = re.sub(r"\s{2,}", " ", title).strip(" -–|,")
        listing["title"] = title
        warns.append("已从标题中移除未证实的认证：%s" % "、".join(hits))

    return listing, warns
