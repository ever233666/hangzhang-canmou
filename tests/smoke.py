# -*- coding: utf-8 -*-
"""端到端冒烟测试：不需要密钥，直接跑。python tests/smoke.py"""
import json
import os
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import config  # noqa: E402
config.MOCK = True

from app import server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

PORT = 8123
BASE = "http://127.0.0.1:%d" % PORT


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def ok(cond, label):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    return bool(cond)


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.4)
    fails = 0

    print("[1] 健康检查")
    h = get("/api/health")
    fails += not ok(h.get("ok") and h.get("mock"), "health ok / mock=%s" % h.get("mock"))

    print("[2] 新建会话")
    r = post("/api/reset", {})
    sid = r["session_id"]
    fails += not ok(bool(sid) and r["state"] == "new", "session %s state=%s" % (sid, r["state"]))

    print("[3] 描述产品（已含市场与材质，缺是否带电）")
    r = post("/api/chat", {"session_id": sid, "text": "我做碳纤维自行车车架，想卖到欧盟"})
    qs = [q["field"] for q in r.get("questions", [])]
    fails += not ok(r["state"] == "clarify" and "product.powered" in qs,
                    "state=%s questions=%s" % (r["state"], qs))

    print("[4] 回答追问，进入规格一问")
    r = post("/api/chat", {"session_id": sid, "text": "不带电"})
    qs = [q["field"] for q in r.get("questions", [])]
    fails += not ok(r["state"] == "clarify" and "product.specs" in qs,
                    "规格单独一问：state=%s questions=%s" % (r["state"], qs))

    print("[4b] 跳过规格，生成方案")
    r = post("/api/chat", {"session_id": sid, "text": "暂时没有"})
    arts = r.get("artifacts", {})
    fails += not ok(r["state"] == "done", "state=%s" % r["state"])
    fails += not ok(bool(arts.get("listing", {}).get("title")), "listing title: %s" % str(arts.get("listing", {}).get("title"))[:60])
    comp = arts.get("compliance", [])
    fails += not ok(len(comp) >= 3, "compliance items=%d" % len(comp))
    fails += not ok(all(c["source_url"].startswith("http") for c in comp), "每条合规都有原文链接")

    print("[5] 政策技能复用同一份档案")
    r = post("/api/policy", {"session_id": sid})
    pol = r.get("policies", [])
    fails += not ok(len(pol) >= 5, "policies=%d" % len(pol))

    print("[6] 档案已落盘")
    from app import store
    prof = store.load("profile", json.loads(open(os.path.join(config.SESSIONS, sid + ".json"), encoding="utf-8").read())["profile_id"])
    fails += not ok(prof["product"]["category"] == "bike", "profile.category=%s" % prof["product"]["category"])
    fails += not ok(prof["product"]["powered"] is False, "profile.powered=%s" % prof["product"]["powered"])

    print("[7] 上传照片（样例模式模拟识别）")
    r = post("/api/reset", {})
    sid2 = r["session_id"]
    r = post("/api/upload", {"session_id": sid2, "data": "iVBORw0KGgo=", "mime": "image/png"})
    fails += not ok(r["state"] == "clarify", "upload -> state=%s" % r["state"])
    fails += not ok(r["reply"].startswith("我看出来这是"), "reply=%s" % r["reply"][:40])

    print("[8] 合规结论必须被拦下")
    from app import guard
    bad, warns = guard.scrub_verdict("您的手工羊毛地毯出口美国已基本合规，只需注意纤维成分标注。")
    fails += not ok("已基本合规" not in bad and "不能判定" in bad, "verdict scrubbed: %s" % bad[:30])
    same, none_warns = guard.scrub_verdict("16 CFR 1630 要求地毯通过燃烧测试。")
    fails += not ok(same == "16 CFR 1630 要求地毯通过燃烧测试。" and not none_warns,
                    "标准陈述不被误改")

    print("[9] 标准代号不得记成认证")
    r = post("/api/claim", {"session_id": sid, "rule_id": "us-carpet-1630"})
    if r.get("ok"):
        prof = store.load("profile", json.loads(open(os.path.join(config.SESSIONS, sid + ".json"), encoding="utf-8").read())["profile_id"])
        meta = prof.get("certs_meta") or {}
        fails += not ok(all(v in ("standard", "cert") for v in meta.values()),
                        "certs_meta=%s" % meta)

    print("[10] 追问不复读")
    from app.agent import agent
    agent._dedupe_answer.__name__
    sess = {"messages": [{"role": "assistant", "text": "地毯要做 16 CFR 1630 燃烧测试。"}], "artifacts": {}}
    dup = agent._dedupe_answer(sess, "地毯要做 16 CFR 1630 燃烧测试。")
    fails += not ok("16 CFR 1630" not in dup, "重复句被剔除，改为：%s" % dup[:40])

    httpd.shutdown()
    print("\n结果：%s" % ("全部通过" if fails == 0 else "%d 项失败" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
