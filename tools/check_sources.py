# -*- coding: utf-8 -*-
"""扫描知识库里所有来源链接的可用性。改完数据跑一遍，别再交死链。

用法：python tools/check_sources.py [--fix]
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 已知的正确域名映射：错 -> 对
FIXES = {
    "https://shangwu.tj.gov.cn": "https://swj.tj.gov.cn",
    "https://gxj.tj.gov.cn": "https://gyxxh.tj.gov.cn",
}


def fix_url(u: str) -> str:
    for bad, good in FIXES.items():
        if u.startswith(bad):
            return good + u[len(bad):]
    return u


def check(url: str, timeout: int = 12):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return type(e).__name__


def main():
    do_fix = "--fix" in sys.argv
    rows = []
    for name in ("rules.json", "policies.json"):
        path = os.path.join(ROOT, "data", name)
        data = json.load(open(path, encoding="utf-8"))
        for item in data:
            u = item.get("source_url", "")
            if not u:
                continue
            if do_fix and fix_url(u) != u:
                item["source_url"] = fix_url(u)
                u = item["source_url"]
            rows.append((name, item.get("id"), item.get("source"), u))
        if do_fix:
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if do_fix:
        print("已修正域名，重新扫描：\n")

    cache = {}
    bad = 0
    print("%-3s %-12s %-22s %-8s %s" % ("#", "条目", "来源", "状态", "URL"))
    print("-" * 110)
    for i, (name, rid, src, u) in enumerate(rows, 1):
        if u not in cache:
            cache[u] = check(u)
        st = cache[u]
        # 202 = 正常受理；3xx = 跳转；403/405 = 反爬，浏览器可开
        ok = st in (200, 202, 203, 301, 302, 403, 405)
        if not ok:
            bad += 1
        tag = str(st) if ok else ("死链:" + str(st))
        print("%-3d %-12s %-22s %-10s %s" % (i, str(rid)[:12], str(src)[:22], tag, u))

    print("-" * 110)
    print("共 %d 个来源，%d 个死链。" % (len(rows), bad))
    print("说明：202 是 EUR-Lex 的正常受理；403 是反爬，浏览器能打开；3xx 是跳转。")
    if bad:
        print("建议：先跑 python tools/check_sources.py --fix 修域名，再人工替换具体文件页。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
