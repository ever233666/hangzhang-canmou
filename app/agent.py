# -*- coding: utf-8 -*-
"""编排层：一个显式状态机，而不是把一切丢给模型。
状态：new -> clarify -> ready -> done
每一步都能在 mock 模式下走通，方便没有密钥时演示和录屏。
"""
import re
import time

from . import config, extract, guard, kb, llm, nextstep, prompts, store

MARKETS = {"eu": "欧盟", "us": "美国", "uk": "英国", "jp": "日本",
           "asean": "东盟", "me": "中东", "af": "非洲"}

MARKET_WORDS = [
    ("eu", ("欧盟", "欧洲", "eu", "德国", "法国", "意大利", "荷兰", "西班牙")),
    ("us", ("美国", "us", "usa", "america", "加州")),
    ("uk", ("英国", "uk", "britain")),
    ("jp", ("日本", "jp", "japan", "东京")),
    ("asean", ("东盟", "东南亚", "asean", "泰国", "印尼", "越南", "马来", "菲律宾", "新加坡")),
    ("me", ("中东", "沙特", "阿联酋", "迪拜", "海湾", "gcc", "saber", "卡塔尔")),
    ("af", ("非洲", "尼日利亚", "肯尼亚", "埃及", "南非", "soncap", "pvoc")),
]
CATEGORIES = {"bike": "自行车及配件", "carpet": "地毯及铺地材料", "hardware": "五金件",
              "appliance": "家电与电器", "apparel": "服装与家纺", "toy": "玩具与婴童用品",
              "lighting": "灯具与照明", "furniture": "家具", "foodware": "食品接触与厨具",
              "cosmetics": "化妆品", "auto": "汽车配件", "medical": "医疗器械", "other": "其他"}

QUESTIONS = {
    "market.region": {
        "field": "market.region",
        "label": "目标市场",
        "text": "这件货主要卖到哪个市场？",
        "options": [{"value": "eu", "label": "欧盟"}, {"value": "us", "label": "美国"}, {"value": "uk", "label": "英国"}],
    },
    "product.powered": {
        "field": "product.powered",
        "label": "是否带电",
        "text": "产品是否带电，或者含电池？",
        "options": [{"value": "yes", "label": "带电"}, {"value": "no", "label": "不带电"}],
    },
    "product.material": {
        "field": "product.material",
        "label": "主要材质",
        "text": "主要材质是什么？说个大概就行，也可以直接打字。",
        "options": [{"value": "铝合金", "label": "铝合金"},
                    {"value": "不锈钢", "label": "不锈钢"},
                    {"value": "塑料", "label": "塑料"},
                    {"value": "其他", "label": "其他（打字说）"}],
    },
    "product.specs": {
        "field": "product.specs",
        "label": "规格",
        "text": "尺寸、重量、起订量、交期，知道几个说几个，不知道就跳过。",
        "options": [{"value": "skip", "label": "暂时没有"}],
    },
    "product.category": {
        "field": "product.category",
        "label": "产品品类",
        "text": "这张图我不敢认死，它属于哪一类？",
        "options": [{"value": "bike", "label": "自行车及配件"},
                    {"value": "carpet", "label": "地毯及地垫"},
                    {"value": "hardware", "label": "五金件"},
                    {"value": "appliance", "label": "家电与电器"},
                    {"value": "apparel", "label": "服装与家纺"},
                    {"value": "toy", "label": "玩具与婴童"},
                    {"value": "lighting", "label": "灯具与照明"},
                    {"value": "furniture", "label": "家具"},
                    {"value": "foodware", "label": "食品接触/厨具"},
                    {"value": "cosmetics", "label": "化妆品"},
                    {"value": "auto", "label": "汽车配件"},
                    {"value": "medical", "label": "医疗器械"},
                    {"value": "other", "label": "都不是"}],
    },
}


class Agent:
    def __init__(self):
        self.questions_per_turn = 3

    # ---------- 对外入口 ----------
    def handle(self, sess: dict, text: str = "", image_b64: str = "", mime: str = "image/jpeg") -> dict:
        profile = store.load("profile", sess["profile_id"]) or store.empty_profile()
        profile["id"] = sess["profile_id"]
        store.save("profile", profile["id"], profile)

        if image_b64:
            self._identify(profile, image_b64, mime)
            sess["messages"].append({"role": "user", "text": "[已上传产品照片]"})
            return self._after_intake(sess, profile, from_image=True)

        text = (text or "").strip()
        if not text:
            return self._render(sess, profile, "上传一张产品照片，或者直接告诉我你做什么产品。")

        sess["messages"].append({"role": "user", "text": text})

        if "打字说" in text:
            return self._render(sess, profile,
                                "直接打一行告诉我就行，比如「涤纶」「不锈钢」「实木」，或者「说不好」跳过。")

        # 不论处于哪个状态，先尝试把这句话理解成档案补丁
        got = extract.patch(text, profile)
        changed = extract.apply(profile, got) if (got["patch"] or got["clear"]) else []
        if got.get("clear"):
            profile["_cat_confirmed"] = False
            profile["_vision_ok"] = False

        if sess["state"] == "new":
            self._intake_text(profile, text)
            return self._after_intake(sess, profile)

        if changed and sess["state"] == "done":
            labels = "、".join(self._label(c) for c in changed[:4])
            return self._generate(sess, profile, note="已更新：%s。重出一版。" % labels)

        if got.get("clear"):
            return self._render(
                sess, profile,
                "好，那它是什么？一句话就行，比如「浴室吸水地垫，硅藻泥，60x40cm」。")

        if changed:
            return self._after_intake(sess, profile)

        # 抽不出结构化信息时，退回关键词兜底（样例模式必须能跑）
        if self._is_correction(text):
            return self._correct(sess, profile, text)

        if sess["state"] == "clarify":
            self._absorb_answers(profile, text)
            return self._after_intake(sess, profile)

        return self._route(sess, profile, text)

    LABELS = {"product.name_cn": "品名", "product.category": "品类", "product.material": "材质",
              "product.powered": "是否带电", "market.region": "目标市场", "company.name": "企业名",
              "specs.size": "尺寸", "specs.weight": "重量", "specs.moq": "起订量",
              "specs.lead_time": "交期"}

    def _label(self, key: str) -> str:
        return self.LABELS.get(key, key)

    # ---------- 入口阶段 ----------
    def _intake_text(self, profile: dict, text: str):
        p = profile["product"]
        name = re.split(r"[，,。；;！!？?]", text)[0].strip()
        for pre in ("我们主要做", "我们做", "我们生产", "我做", "我们是", "我是", "生产"):
            if name.startswith(pre):
                name = name[len(pre):]
                break
        p["name_cn"] = (name or text)[:40]
        p["category"] = self._guess_category(text)
        profile["_fresh_intake"] = True
        for kw, mat in (("碳", "碳纤维"), ("铝", "铝合金"), ("钢", "钢"), ("不锈钢", "不锈钢"),
                        ("羊毛", "羊毛"), ("尼龙", "尼龙"), ("塑料", "塑料")):
            if kw in text:
                p["material"] = mat
                break
        # 先判否定：「不带电」里也含「带电」，先判肯定就会把机械件当电器
        if any(k in text for k in ("不带电", "不带电池", "非电动", "不用电", "无电池", "不含电池",
                                   "没有电池", "没电池", "纯机械", "手动")):
            p["powered"] = False
        elif any(k in text for k in ("电动", "锂电", "电池", "带电", "电机")):
            p["powered"] = True
        for code, words in MARKET_WORDS:
            if any(w in text.lower() for w in words):
                profile["market"]["region"] = code
                break

    def _identify(self, profile: dict, image_b64: str, mime: str):
        """把图片真的发给视觉模型；没接视觉模型时优雅降级，不猜。"""
        fallback = {"name_cn": "自行车车架", "category": "bike", "material": "", "powered": None,
                    "visible_features": []}
        data = None
        err = ""
        if config.MOCK:
            # 样例模式：模拟一次成功的识别，保证 Demo 的「拍照」链路完整
            data = dict(fallback)
            profile["_vision_ok"] = True
            profile["_vision_error"] = ""
            profile["_vision_simulated"] = True
        elif config.VISION_READY:
            try:
                raw = llm.vision(image_b64, mime, prompts.VISION_SYSTEM)
                data = {k: v for k, v in raw.items() if v not in (None, "", [])} if isinstance(raw, dict) else None
            except Exception as e:
                err = str(e)[:120]
        else:
            err = "未配置视觉模型"
        if not config.MOCK:
            profile["_vision_ok"] = bool(data)
            profile["_vision_error"] = err
        data = {**fallback, **(data or {})}
        p = profile["product"]
        p["name_cn"] = data.get("name_cn") or p["name_cn"]
        p["category"] = data.get("category") or p["category"] or "other"
        if data.get("material"):
            p["material"] = data["material"]
        if data.get("powered") is not None:
            p["powered"] = bool(data["powered"])
        profile["_vision_features"] = data.get("visible_features", [])

    # ---------- 纠正 ----------
    CORRECTIVE = ("不是", "不对", "错了", "认错", "你看错", "其实是", "应该是", "这不是")

    def _is_correction(self, text: str) -> bool:
        # 「都不是」「其他」是选项按钮，不是纠错，别拿去重判
        if any(k in text for k in ("都不是", "其他", "都没有", "不确定")):
            return False
        return any(k in text for k in self.CORRECTIVE)

    def _correct(self, sess: dict, profile: dict, text: str) -> dict:
        """用户说「这不是 X」时，重判品类，并把之前的误判字段清掉。
        不清掉的话，模型会拿「金属 + 装饰板」继续往下写。
        """
        # 「这不是A，这是B」要取 B，不能把整句当成品名
        segs = [x.strip() for x in re.split(r"[，,。；;！!？?]", text) if x.strip()]
        name = segs[-1] if segs else text
        for pre in ("这不是", "不是", "其实是", "应该是", "这是", "就是", "那是我",
                    "我们做的是", "我们做", "我做的是", "我做"):
            if name.startswith(pre):
                name = name[len(pre):]
                break
        name = name.strip("，。！? 的方面产品")
        if not name:
            name = profile["product"].get("name_cn", "")

        profile["product"]["name_cn"] = name[:40]
        profile["product"]["category"] = self._guess_category(name)
        profile["product"]["material"] = ""          # 旧材质来自误判，必须清
        profile["product"]["powered"] = None
        profile["_cat_confirmed"] = False
        profile["_vision_ok"] = False
        profile["_corrected"] = True
        sess["state"] = "clarify"
        return self._after_intake(sess, profile)

    # ---------- 追问 ----------
    def _missing(self, profile: dict) -> list:
        out = []
        cat = profile["product"].get("category")
        if (not cat or cat == "other") and not profile.get("_cat_confirmed"):
            out.append("product.category")
        if not profile["market"].get("region"):
            out.append("market.region")
        if profile["product"].get("powered") is None:
            out.append("product.powered")
        if not profile["product"].get("material") and profile.get("_mat_asked", 0) < 2:
            out.append("product.material")
        return out

    def _after_intake(self, sess: dict, profile: dict, from_image: bool = False) -> dict:
        missing = self._missing(profile)
        if missing:
            sess["state"] = "clarify"
            sess["pending"] = missing[: self.questions_per_turn]
            if "product.material" in sess["pending"]:
                profile["_mat_asked"] = profile.get("_mat_asked", 0) + 1
            qs = [QUESTIONS[f] for f in sess["pending"]]
            name = profile["product"]["name_cn"]
            # 没有按钮的问题，必须把题目写进正文，否则界面看起来像卡死
            plain = [QUESTIONS[f]["text"] for f in sess["pending"] if not QUESTIONS[f]["options"]]
            if profile.pop("_corrected", False):
                prefix = "好，我按「%s」重新判断。" % name
            elif from_image and profile.get("_vision_ok"):
                prefix = "我看出来这是%s。" % name
            elif from_image:
                prefix = ("这边没有接视觉模型（%s），我先按「%s」往下走，"
                          "你直接打字纠正就行。" % (profile.get("_vision_error", "原因未知"), name))
            elif profile.pop("_fresh_intake", False):
                prefix = "我记下了：%s。" % name
            else:
                prefix = ""
            head = "还需要确认一下：" if len(sess["pending"]) <= 2 else "在给你出方案之前，我需要确认几件事："
            extra = "　".join("%d）%s" % (i + 1, t) for i, t in enumerate(plain))
            return self._render(sess, profile, prefix + head + (("　" + extra) if extra else ""), questions=qs)
        # 材质空着时，先按品类推一个；标明推测，用户一句话就能改
        if (not profile["product"].get("material")
                and not profile.get("_mat_guessed")
                and profile["product"].get("name_cn")):
            profile["_mat_guessed"] = True
            g = extract.guess_material(profile["product"]["name_cn"],
                                       CATEGORIES.get(profile["product"].get("category"), ""))
            if g["material"] and g["confidence"] in ("high", "medium"):
                profile["product"]["material"] = g["material"]
                profile["product"]["material_guessed"] = True

        # 关键信息齐了，规格单独问一次，不和别的挤在一起
        if not profile["product"].get("specs") and not profile.get("_specs_asked"):
            profile["_specs_asked"] = True
            store.save("profile", profile["id"], profile)
            sess["state"] = "clarify"
            sess["pending"] = ["product.specs"]
            reply = ("最后确认一下规格，知道几个说几个，都没有就点下面：\n"
                     "· 尺寸（如 54cm、60x40cm）\n"
                     "· 重量（如 1.1kg、220g）\n"
                     "· 起订量（如 50 件、200 套）\n"
                     "· 交期（如 30 天）\n"
                     "直接一行打给我就行，比如「54cm，1.1kg，起订50件，30天」。")
            return self._render(sess, profile, reply, questions=[QUESTIONS["product.specs"]])
        return self._generate(sess, profile)

    def _absorb_answers(self, profile: dict, text: str):
        low = text.lower()
        for code, words in MARKET_WORDS:
            if any(w in low for w in words):
                profile["market"]["region"] = code
                break
        if any(k in text for k in ("说不好", "不清楚材质", "不确定材质")):
            profile["_mat_asked"] = 9

        if any(k in text for k in ("暂时没有", "没有规格", "跳过", "不知道")):
            profile["_specs_asked"] = True
        else:
            self._absorb_specs(profile, text)   # 规格那轮的回答，关键词也要收一份

        # 品类回答（选项按钮传回来的也是中文标签）
        if any(k in text for k in ("食品接触", "厨具", "餐具")):
            profile["product"]["category"] = "foodware"
            profile["_cat_confirmed"] = True
        elif "化妆品" in text:
            profile["product"]["category"] = "cosmetics"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("汽车配件", "汽配")):
            profile["product"]["category"] = "auto"
            profile["_cat_confirmed"] = True
        elif "医疗器械" in text:
            profile["product"]["category"] = "medical"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("玩具", "婴童", "积木")):
            profile["product"]["category"] = "toy"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("灯具", "照明")):
            profile["product"]["category"] = "lighting"
            profile["_cat_confirmed"] = True
        elif "家具" in text:
            profile["product"]["category"] = "furniture"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("家电", "电器", "电热毯", "取暖")):
            profile["product"]["category"] = "appliance"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("服装", "家纺", "毛巾", "床品")):
            profile["product"]["category"] = "apparel"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("自行车", "车架", "配件")):
            profile["product"]["category"] = "bike"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("地毯", "地垫", "脚垫", "门垫", "铺地")):
            profile["product"]["category"] = "carpet"
            profile["_cat_confirmed"] = True
        elif "五金" in text or "合页" in text:
            profile["product"]["category"] = "hardware"
            profile["_cat_confirmed"] = True
        elif any(k in text for k in ("都不是", "其他", "说不清")):
            profile["product"]["category"] = "other"
            profile["_cat_confirmed"] = True

        # 先判否定，再判肯定——「不带电」里也含「带电」
        neg = any(k in low for k in ("不带电", "不带", "不含电池", "没有电池", "没电池", "纯机械", "否", "no"))
        pos = any(k in low for k in ("带电", "电池", "锂电", "电动", "yes"))
        if neg:
            profile["product"]["powered"] = False
        elif pos:
            profile["product"]["powered"] = True
        for kw, mat in (("碳纤维", "碳纤维"), ("碳", "碳纤维"), ("铝合金", "铝合金"), ("铝", "铝合金"),
                        ("不锈钢", "不锈钢"), ("钢", "钢"), ("羊毛", "羊毛"), ("尼龙", "尼龙"),
                        ("涤纶", "涤纶"), ("聚酯", "聚酯"), ("腈纶", "腈纶"), ("棉", "棉"),
                        ("橡胶", "橡胶"), ("硅胶", "硅胶"), ("塑料", "塑料"), ("木", "木"),
                        ("纸", "纸"), ("玻璃", "玻璃"), ("陶瓷", "陶瓷"), ("皮革", "皮革"),
                        ("无纺布", "无纺布"), ("亚克力", "亚克力"), ("竹", "竹"),
                        ("液体", "液体"), ("膏体", "膏体"), ("粉末", "粉末")):
            if kw in text:
                profile["product"]["material"] = mat
                break
        profile["product"]["size_cm"] = profile["product"].get("size_cm") or ""
        # 没答到的就不填——默认成「欧盟」会让客户拿到错市场的合规结论

    # ---------- 生成 ----------
    def _generate(self, sess: dict, profile: dict, note: str = "") -> dict:
        sess["state"] = "done"
        cat = profile["product"].get("category") or "other"
        market = profile["market"].get("region") or config.DEFAULT_MARKET
        text = " ".join(filter(None, [profile["product"].get("name_cn", ""), profile["product"].get("material", "")]))
        powered = bool(profile["product"].get("powered"))
        form = self._product_form(profile)
        rule_cards = kb.search_rules(cat, market, text, limit=6, powered=powered, form=form)

        certs = profile.get("certs", [])
        data_warnings = []
        mat = profile["product"].get("material", "")
        if mat and not self._plausible(cat, mat):
            data_warnings.append(
                "材质「%s」与品类「%s」不符，已忽略，改按未说明处理" % (mat, CATEGORIES.get(cat, cat)))
            profile["product"]["material"] = ""
        listing = self._make_listing(profile, rule_cards)
        listing, guard_warnings = guard.scrub(listing, certs)
        listing, spec_warns = guard.scrub_specs(listing, profile["product"].get("specs", {}))
        guard_warnings += spec_warns
        listing, claim_warns = guard.scrub_claims(listing, profile)
        guard_warnings += claim_warns
        # 被护栏拦下就带着反馈重写一次，取警告更少的版本
        if guard_warnings and not config.MOCK:
            retry = self._make_listing(profile, rule_cards, feedback=guard_warnings)
            retry, retry_warns = guard.scrub(retry, certs)
            retry, rw2 = guard.scrub_specs(retry, profile["product"].get("specs", {}))
            retry, rw3 = guard.scrub_claims(retry, profile)
            retry_warns += rw2 + rw3
            if len(retry_warns) <= len(guard_warnings):
                listing, guard_warnings = retry, retry_warns
        compliance = self._make_compliance(profile, rule_cards)

        sess["artifacts"] = {
            "listing": listing,
            "compliance": compliance,
            "guard_warnings": guard_warnings + data_warnings,
            "rules_used": [r["id"] for r in rule_cards],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        profile.setdefault("history", []).append({"market": market, "category": cat, "at": time.strftime("%Y-%m-%d %H:%M")})
        store.save("profile", profile["id"], profile)
        cover = len(kb.rules_for_market(market))
        reply = note or "方案出来了。左边是 listing，右边是这份产品真正要过的合规清单。"
        if profile["product"].get("material_guessed"):
            reply = "材质我先按「%s」算的（推测，不对你直接说一声）。\n" % profile["product"]["material"] + reply
        if cover < 4:
            reply += ("\n\n注意：%s市场的知识库还在补充，目前只有 %d 条，"
                      "结论不完整，务必让货代或检测机构复核。" % (MARKETS.get(market, market), cover))
        return self._render(sess, profile, reply)

    def _make_listing(self, profile: dict, rule_cards: list, feedback: list = None) -> dict:
        fallback = self._mock_listing(profile)
        if config.MOCK:
            return fallback
        payload = {
            "profile": {
                "product": profile["product"],
                "specs": profile["product"].get("specs", {}),
                "market": profile["market"],
                "certs": profile.get("certs", []),
                "capacity": profile.get("capacity", {}),
            },
            "rules": [{"id": r["id"], "title": r["title"], "requirement": r["requirement"]} for r in rule_cards],
        }
        import json
        msgs = [{"role": "system", "content": prompts.LISTING_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        if feedback:
            msgs.append({"role": "assistant", "content": "（上一版已生成）"})
            reason = "\n- ".join(feedback[:5])
            msgs.append({"role": "user", "content":
                         "上一版被合规护栏拦下了，原因：\n- " + reason +
                         "\n请重写。凡是涉及认证、标准、法规合规的表述一律不要出现，"
                         "改用具体的结构、尺寸、材质或工艺描述。只返回 JSON。"})
        got = llm.chat_json(msgs, fallback=fallback, max_tokens=1200)
        out = dict(fallback)
        for k in ("title", "bullets", "description", "keywords", "price_band", "price_basis", "claims_to_avoid"):
            if got.get(k):
                out[k] = got[k]
        # 「$300-500」在跨境场景里是歧义价，统一写成 USD
        band = str(out.get("price_band") or "").strip()
        if band.startswith("$"):
            out["price_band"] = "USD " + band[1:].strip()
        elif band and band[0].isdigit():
            out["price_band"] = "USD " + band
        return out

    CERT_TOKEN = re.compile(
        r"(EN\s?ISO\s?\d{4,5}(?:-\d+)?|EN\s?\d{4,5}(?:-\d+)?|ISO\s?\d{4,5}(?:-\d+)?"
        r"|UL\s?\d{4}|\d{2}\s?CFR\s?\d{3,4}|TB\s?117(?:-\d{4})?|\bCPSIA\b"
        r"|\bRoHS\b|\bREACH\b|\bGPSR\b|\bUKCA\b|\bCE\b)")

    def _cert_of(self, rule: dict) -> str:
        """这条规则对应的、客户可能已持有的资格代号；没有就返回空。"""
        m = self.CERT_TOKEN.search(rule.get("title", "") or "")
        return m.group(1).strip() if m else ""

    @staticmethod
    def _held(rule: dict, certs: list) -> str:
        """档案里的认证是否覆盖了这条规则；返回命中的认证名或空串。"""
        hay = (rule.get("title", "") + " " + rule.get("requirement", "")).upper()
        for c in certs or []:
            token = str(c).strip().upper()
            if not token:
                continue
            if re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", hay):
                return c
        return ""

    def _make_compliance(self, profile: dict, rule_cards: list) -> list:
        certs = profile.get("certs", [])
        meta = profile.get("certs_meta", {}) or {}
        items = []
        for r in rule_cards:
            hit = self._held(r, certs)
            items.append({
                "rule_id": r["id"],
                "title": r["title"],
                "requirement": r["requirement"],
                "severity": r.get("severity", "should"),
                "why": r.get("why_template", ""),
                "source": r.get("source", ""),
                "source_url": r.get("source_url", ""),
                "needs_human": True,
                "verified": r.get("verified", False),
                "have": bool(hit),
                "held_by": hit,
                "held_kind": meta.get(hit, "cert") if hit else "",
                "cert": self._cert_of(r),
                "source_status": r.get("source_status", ""),
            })
        order = {"must": 0, "should": 1, "info": 2}
        items.sort(key=lambda x: order.get(x["severity"], 3))
        return items

    def _mock_listing(self, profile: dict) -> dict:
        p = profile["product"]
        mat = p.get("material") or "Aluminum"
        powered = bool(p.get("powered"))
        if p.get("category") == "carpet":
            return {
                "title": "Hand-Tufted Wool Area Rug 160x230cm - Low Pile, Non-Shedding, Living Room",
                "bullets": [
                    "Dense 12mm low pile resists crushing in high-traffic living rooms",
                    "Hand-tufted 100% New Zealand wool, no recycled fiber blended in",
                    "Anti-slip cotton backing, safe on wood floors and tile without an underlay",
                    "Batch-dyed in 50kg lots, so color stays consistent within one order",
                    "Custom sizes and 8 colorways available from 50 pcs",
                ],
                "description": "Woven on 40-year-old looms in Tianjin, this rug pairs a dense low pile with a cotton backing that stays flat without an underlay. The wool is batch-dyed, so color holds after the third wash. Ships rolled, not folded, to avoid crease marks.",
                "keywords": ["wool area rug 160x230", "low pile living room rug", "hand tufted rug", "non slip rug", "oeko tex rug"],
                "price_band": "USD 68–95 / pc (FOB Tianjin, 100 pcs)",
                "price_basis": "同类手工簇绒羊毛地毯在亚马逊中位价 120–160 美元，按 45% 渠道加价反推 FOB。",
                "claims_to_avoid": ["OEKO-TEX 证书需实际持有后才能写进 listing"],
            }
        return {
            "title": "700C %s Road Bike Frame - Disc Brake, 142x12 Thru Axle, 1.15kg" % ("Carbon" if "碳" in mat else "Alloy"),
            "bullets": [
                "Fits 700x32c tires, so it doubles as a gravel frame without swapping forks",
                "142x12 thru-axle rear and flat-mount disc standard, compatible with Shimano and SRAM groupsets",
                "Internal cable routing with full-length liners, no rattle on rough pavement",
                "1.15kg unpainted in size 54, weighed in-house, not a catalog number",
                "T47 threaded bottom bracket shell, avoids press-fit creak",
            ],
            "description": "Built in a Tianjin workshop that has welded frames for European brands since 2003. This frame uses a T47 threaded BB and full-length internal liners, the two details that most often cause creaks and cable rattle on cheaper frames. Supplied unpainted with decals separate.",
            "keywords": ["700c road bike frame", "disc brake frame", "carbon road frame", "thru axle frame", "gravel bike frame"],
            "price_band": "USD 320–420 / pc (FOB Tianjin, 50 pcs)",
            "price_basis": "同规格车架在亚马逊零售 699–899 美元，按渠道加价 55% 反推 FOB 区间。",
            "claims_to_avoid": ["EN 14781 疲劳测试报告未提供前，不要写 “race proven” 或 “UCI approved”"],
        }

    # 品类与材质的合理性映射：用户说错时，代码要拦，不能顺着往下写
    PLAUSIBLE = {
        "appliance": ("塑料", "金属", "钢", "铝", "涤纶", "棉", "羊毛", "尼龙", "硅胶", "橡胶", "玻璃"),
        "toy": ("塑料", "木", "毛绒", "棉", "布", "硅胶", "橡胶", "金属"),
        "lighting": ("铝", "钢", "塑料", "玻璃", "亚克力", "铜"),
        "furniture": ("木", "钢", "铝", "板材", "布", "皮革", "藤", "塑料"),
        "foodware": ("不锈钢", "钢", "塑料", "玻璃", "陶瓷", "硅胶", "纸", "竹", "木", "铝"),
        "auto": ("钢", "铝", "塑料", "橡胶", "铜", "陶瓷", "复合材料"),
        "medical": ("塑料", "不锈钢", "无纺布", "硅胶", "玻璃", "橡胶"),
        "cosmetics": (),
        "apparel": ("棉", "涤纶", "羊毛", "尼龙", "真丝", "亚麻", "粘胶", "氨纶", "腈纶", "混纺", "皮革"),
        "carpet": ("羊毛", "尼龙", "涤纶", "丙纶", "棉", "塑料", "混纺", "聚酯", "黏胶",
                   "硅藻", "橡胶", "PVC", "pvc", "TPR", "超细纤维", "记忆棉", "海绵",
                   "EVA", "腈纶", "丙纶", "剑麻"),
        "bike": ("碳纤维", "铝合金", "钢", "钛", "镁", "铬钼"),
        "hardware": ("钢", "不锈钢", "锌合金", "铝", "铁", "铜", "塑料"),
    }

    COMPONENT_WORDS = ("夹器", "刹车", "变速", "飞轮", "链条", "把立", "座管", "脚踏",
                       "花鼓", "轮组", "线管", "牙盘", "配件", "部件")

    def _product_form(self, profile: dict) -> str:
        """整车还是部件。卖夹器不能给整车标准，这是硬伤。"""
        name = profile["product"].get("name_cn", "") or ""
        return "component" if any(w in name for w in self.COMPONENT_WORDS) else "complete"

    def _plausible(self, cat: str, material: str) -> bool:
        allowed = self.PLAUSIBLE.get(cat)
        if not allowed or not material:
            return True
        return any(a in material for a in allowed)

    # ---------- 补充规格 ----------
    SPEC_PATTERNS = [
        ("weight", r"(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)"),
        # 先匹配「160x230cm」这种组合，再退回单值，否则 160 会被丢掉
        ("size", r"(\d{2,3}(?:\.\d+)?\s*[x×X*]\s*\d{2,3}(?:\.\d+)?|\d{2,3}(?:\.\d+)?)\s*(?:cm|厘米)"),
        ("moq", r"(?:起订|MOQ|最少)\D{0,4}(\d{1,6})"),
        ("lead_time", r"(\d{1,3})\s*(?:天)\s*(?:交货|交期)?"),
    ]

    SPEC_LABELS = {"weight": "重量", "size": "尺寸", "moq": "起订量", "lead_time": "交期"}

    def _absorb_specs(self, profile: dict, text: str) -> list:
        got = []
        specs = profile["product"].setdefault("specs", {})
        for key, pat in self.SPEC_PATTERNS:
            m = re.search(pat, text, re.I)
            if m:
                specs[key] = m.group(1)
                got.append(key)
        return got

    # ---------- 意图路由 ----------
    def _route(self, sess: dict, profile: dict, text: str) -> dict:
        low = text.lower()
        if re.search(r"kg|公斤|厘米|起订|moq", text, re.I) and re.search(r"\d", text):
            got = self._absorb_specs(profile, text)
            if got:
                store.save("profile", profile["id"], profile)
                labels = "、".join(self.SPEC_LABELS.get(g, g) for g in got)
                return self._generate(sess, profile, note="补了%s，重写一版。" % labels)
        if any(k in text for k in ("物流", "报关", "头程", "订舱", "hs编码", "HS编码")):
            return self._render(sess, profile, nextstep.render_guide("logistics"))
        if any(k in text for k in ("退税", "收汇", "外汇", "结汇")):
            return self._render(sess, profile, nextstep.render_guide("payment"))

        if any(k in text for k in ("下一步", "还差什么", "还要做什么", "怎么出海", "流程", "接下来")):
            res = nextstep.build(profile, sess.get("artifacts", {}))
            return self._render(sess, profile, nextstep.render(res))

        if any(k in text for k in ("补贴", "政策", "申报", "奖励")):
            pol = kb.match_policies(profile)
            sess["artifacts"]["policies"] = pol
            return self._render(sess, profile, "按你的档案筛了一遍，这几条是可以去申的：")
        if any(k in text for k in ("重新生成", "再写一版", "换个", "重做")):
            return self._generate(sess, profile)
        if any(k in text for k in ("没有更新", "没更新", "为什么没变", "没刷新")):
            pr = profile.get("product", {})
            certs = profile.get("certs", [])
            return self._render(sess, profile, "档案当前是：材质 %s，目标市场 %s，已有认证 %s。"
                                "如果你刚点过「我已具备」，点一下右上角「刷新」，这里会立刻出现。"
                                % (pr.get("material") or "未填",
                                   {"eu": "欧盟", "us": "美国", "uk": "英国"}.get(
                                       profile["market"].get("region"), "未填"),
                                   "、".join(certs) if certs else "暂未录入"))
        if any(k in text for k in ("档案", "信息", "我填的")):
            return self._render(sess, profile, "右边就是你的企业档案，所有产物都是基于它生成的。")
        reply = self._answer_question(sess, profile, text)
        return self._render(sess, profile, reply)

    QA_SYSTEM = """你是中小工厂的出海参谋，替一个不懂外贸的厂老板回答问题。
要求：
1. 先用一句话给结论，再给两三条理由或做法。总长不超过 200 字，最多 3 条。
2. 只讲你确定的内容。拿不准就直说「这点我不确定」并指出该问谁（海关、税务、平台客服、公告机构）。
3. 不要套话：不要「根据您的需求」「希望对您有帮助」「建议咨询专业人士」这种空转句子。
4. 涉及法规、税率、编码、认证时，结尾必须带一句以官方口径为准。
5. 中文回答，除非用户用英文提问。
6. 不许下结论说产品「已合规」「符合要求」「可以放心出口」——你没看过检测报告。只说要求、缺口、该找谁做。
7. 「对话上文」里已经讲过的点不要重复。确实没有新内容时，直接说「前面能讲的就这些」，
   然后给出一个具体的下一步动作（做哪项检测、找哪个机构、补哪份材料）。
8. 不许把标准代号说成认证：CPSC/FDA 不发证书，16 CFR、EN、ISO 是标准不是资质。
9. 追问时优先讲「还没讲到的条目」；全都讲过，就给可执行细节（找谁测、准备什么材料），
   不要再把标准编号和上一轮的话复述一遍。引用得到规则卡就引用，引不到就说明这是通行做法。
10. 不给具体金额、天数、年限这些数字，除非规则卡里写了。需要时说「以实验室报价为准」「以官方文本为准」。
11. 拿不准的条款细节宁可不写，也不要猜年份和百分比。"""

    @staticmethod
    def _shingles(s: str, n: int = 6) -> set:
        s = re.sub(r"[\s，。、；：（）()\[\]【】·\-—…\"'“”‘’!?！？,.;:%/]+", "", s or "")
        return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}

    @classmethod
    def _dup(cls, part: str, prev: set, th: float = 0.6) -> bool:
        if len(part) < 8 or not prev:
            return False
        sh = cls._shingles(part)
        if not sh:
            return False
        return len(sh & prev) / float(len(sh)) >= th

    def _dedupe_answer(self, sess: dict, reply: str) -> str:
        """追问时模型爱把上一轮原样重说一遍。这里按句去重，剩下太少就换一段新内容。"""
        hist = [m["text"] for m in (sess.get("messages") or [])
                if m.get("role") == "assistant" and m.get("text")][-6:]
        if not hist:
            return reply
        prev = self._shingles(" ".join(hist), 6)
        # 按行、按句删；换行要留住，否则 1. 2. 3. 会挤成一坨
        lines = []
        for ln in reply.split("\n"):
            sents = re.findall(r"[^。！？]*[。！？]?", ln)
            lines.append("".join(s for s in sents if s.strip() and not self._dup(s, prev)))
        out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        if len(re.sub(r"\s", "", out)) >= 24:
            return out

        # 真没新东西了：从合规清单里挑还没讲过的，比复读有用
        comp = (sess.get("artifacts") or {}).get("compliance") or []
        said = self._shingles(" ".join(hist), 6)
        fresh = [c for c in comp if c.get("title") and not self._dup(c["title"], said, 0.5)][:3]
        if fresh:
            lines = ["前面能讲的都讲了。清单里这几项还没展开："]
            for c in fresh:
                req = (c.get("requirement") or "").strip()
                lines.append("· %s：%s" % (c.get("title"), req[:70]))
            src = next((c.get("source") for c in fresh if c.get("source")), "")
            if src:
                lines.append("依据：%s。以官方口径为准。" % src)
            return "\n".join(lines)
        return ("这块讲完了，再往下就是重复。接下来能做的三件事："
                "把规格补一句（尺寸、重量、起订量），我重写一版 listing；"
                "点右边「生成报价单」把这些落到文件上；或者换个品类再试一遍。")

    def _answer_question(self, sess: dict, profile: dict, text: str) -> str:
        """兜底问答：带档案、带相关规则卡，而不是一句通用回复。"""
        if config.MOCK:
            return ("这个问题先记下了。当前版本我能做四件事：写 listing、查合规、匹配政策、"
                    "算下一步——你可以直接问其中一件。")

        low = text.lower()
        hits = []
        for r in kb.rules():
            if any(k and str(k).lower() in low for k in r.get("keywords", [])):
                hits.append(r)
        comp = (sess.get("artifacts") or {}).get("compliance") or []

        # 追问类（还有呢/继续/详细点）必须带上文，否则模型每轮都从同一批规则里重炒一遍，
        # 用户看到的就是三遍一模一样的话——这正是之前死循环的来源。
        hist = [m for m in (sess.get("messages") or [])[-8:] if m.get("text")]
        followup = bool(re.search(r"还有|继续|接着说|然后呢|详细|具体|多说|别的|其他", text))
        said = [m["text"][:120] for m in hist if m.get("role") == "assistant"][-3:]

        ctx = {
            "对话上文": [{"角色": m.get("role"), "内容": m["text"][:160]} for m in hist],
            "已经讲过的要点": said,
            "本轮是追问": followup,
            "企业档案": {
                "产品": profile["product"].get("name_cn"),
                "品类": profile["product"].get("category"),
                "材质": profile["product"].get("material"),
                "是否带电": profile["product"].get("powered"),
                "目标市场": profile["market"].get("region"),
                "已有认证": profile.get("certs", []),
            },
            "当前合规清单": [{"标题": c.get("title"), "要求": c.get("requirement"),
                               "为什么适用": c.get("why"), "来源": c.get("source"),
                               "链接": c.get("source_url")} for c in comp[:6]],
            "还没讲到的条目": [c.get("title") for c in comp
                               if c.get("title") and not any(c.get("title") in s for s in said)][:4],
            "相关规则卡": [{"标题": h.get("title"), "要求": h.get("requirement"),
                            "来源": h.get("source")} for h in hits[:2]],
            "问题": text,
        }
        import json
        try:
            reply = llm.chat(
                [{"role": "system", "content": self.QA_SYSTEM},
                 {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
                max_tokens=700, temperature=0.3).strip()
        except Exception:
            reply = ""
        reply = reply or "这条我暂时答不好。你可以换个问法，或者直接说产品，我按合规和 listing 帮你过一遍。"
        # 兜底：就算模型还是写「已基本合规」，代码也要在出门前改掉。
        reply, fix_warns = guard.scrub_verdict(reply)
        reply = self._dedupe_answer(sess, reply)
        if fix_warns:
            sess.setdefault("guard_log", []).append({"at": time.strftime("%H:%M:%S"),
                                                    "kind": "qa", "warns": fix_warns})
            sess["guard_log"] = sess["guard_log"][-20:]
        return reply

    # ---------- 渲染 ----------
    def _render(self, sess: dict, profile: dict, reply: str, questions=None) -> dict:
        sess["messages"].append({"role": "assistant", "text": reply})
        sess["messages"] = sess["messages"][-40:]
        store.save("session", sess["id"], sess)
        store.save("profile", profile["id"], profile)
        return {
            "session_id": sess["id"],
            "state": sess["state"],
            "reply": reply,
            "questions": questions or [],
            "profile": self._public_profile(profile),
            "artifacts": sess.get("artifacts", {}),
            "mock": config.MOCK,
        }

    @staticmethod
    def _public_profile(profile: dict) -> dict:
        return {
            "id": profile.get("id"),
            "name": profile["company"].get("name") or "未填写",
            "product": profile["product"],
            "market": profile["market"],
            "certs": profile.get("certs", []),
            "certs_meta": profile.get("certs_meta", {}),
            "capacity": profile.get("capacity", {}),
        }

    @staticmethod
    def _guess_category(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("化妆品", "护肤", "面膜", "口红", "香水", "洗面奶", "cosmetic")):
            return "cosmetics"
        if any(k in t for k in ("医疗器械", "口罩", "体温计", "血压计", "康复", "medical")):
            return "medical"
        if any(k in t for k in ("汽车配件", "刹车片", "车灯", "后视镜", "滤清器", "汽配", "轮毂")):
            return "auto"
        if any(k in t for k in ("餐具", "厨具", "保鲜盒", "水杯", "餐盒", "食品接触", "杯")):
            return "foodware"
        if any(k in t for k in ("玩具", "积木", "毛绒", "婴童", "奶嘴", "推车", "toy")):
            return "toy"
        if any(k in t for k in ("灯", "照明", "灯泡", "灯带", "lighting", "lamp")):
            return "lighting"
        if any(k in t for k in ("家具", "椅", "桌", "柜", "沙发", "床架", "床垫", "书架", "furniture")):
            return "furniture"
        if any(k in t for k in ("电热毯", "家电", "电器", "电水壶", "吹风", "取暖器",
                                 "加湿器", "电饭", "appliance")):
            return "appliance"
        if any(k in t for k in ("服装", "家纺", "毛巾", "床品", "四件套", "衣服", "衬衫",
                                 "apparel", "textile")):
            return "apparel"
        if any(k in t for k in ("自行车", "车架", "bike", "bicycle", "骑行")):
            return "bike"
        if any(k in t for k in ("地毯", "地垫", "脚垫", "门垫", "浴室垫", "防滑垫",
                                 "rug", "carpet", "mat")):
            return "carpet"
        if any(k in t for k in ("五金", "铰链", "螺丝", "hardware", "bracket")):
            return "hardware"
        return "other"


agent = Agent()
