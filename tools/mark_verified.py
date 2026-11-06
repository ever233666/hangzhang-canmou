# -*- coding: utf-8 -*-
"""人工核对完原文后，把条目标记为已验证。

用法：
    python tools/mark_verified.py --list
    python tools/mark_verified.py eu-gpsr us-cpsc-1512
"""
import json
import os
import sys

ROOT = r"C:\deeepseck\factory-advisor\data"
FILES = ("rules.json", "policies.json")


def load_all():
    out = []
    for name in FILES:
        p = os.path.join(ROOT, name)
        out.append((name, p, json.load(open(p, encoding="utf-8"))))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data = load_all()

    if "--list" in sys.argv or not args:
        print("%-18s %-8s %s" % ("ID", "已核对", "标题"))
        print("-" * 78)
        for name, _, items in data:
            for it in items:
                mark = "✓" if it.get("verified") else "·"
                print("%-18s %-8s %s" % (it.get("id"), mark, str(it.get("title") or it.get("name"))[:44]))
        total = sum(len(i) for _, _, i in data)
        done = sum(1 for _, _, items in data for it in items if it.get("verified"))
        print("-" * 78)
        print("已核对 %d / %d" % (done, total))
        return 0

    hit = 0
    for name, path, items in data:
        changed = False
        for it in items:
            if it.get("id") in args and not it.get("verified"):
                it["verified"] = True
                hit += 1
                changed = True
        if changed:
            json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    missing = [a for a in args if a not in {i.get("id") for _, _, items in data for i in items}]
    print("已标记 %d 条" % hit)
    if missing:
        print("未找到：%s" % "、".join(missing))
    total = sum(len(i) for _, _, i in data)
    done = sum(1 for _, _, items in data for it in items if it.get("verified"))
    print("进度：%d / %d" % (done, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
