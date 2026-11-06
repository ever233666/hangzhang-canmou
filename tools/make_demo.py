# -*- coding: utf-8 -*-
"""造一个完整演示会话，用于截图或录屏。用法：python tools/make_demo.py http://127.0.0.1:8000 [--specs]"""
import json, sys, urllib.request

BASE = sys.argv[1]
SPECS = "--specs" in sys.argv


def post(p, b):
    r = urllib.request.Request(BASE + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=120).read().decode())


s = post("/api/reset", {})["session_id"]
post("/api/chat", {"session_id": s, "text": "我做碳纤维自行车车架，想卖到欧盟"})
post("/api/chat", {"session_id": s, "text": "不带电"})
if SPECS:
    post("/api/chat", {"session_id": s, "text": "重量1.1kg，尺寸54cm，起订50件，交期30天"})
post("/api/policy", {"session_id": s})
print(s)
