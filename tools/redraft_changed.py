# -*- coding: utf-8 -*-
"""对检测到变化的政策批量起草修订。用法：python tools/redraft_changed.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import freshness, kb, redraft  # noqa: E402


def main():
    todo = [p for p in kb.policies()
            if p.get("source_status") == "changed" and not p.get("draft")]
    if not todo:
        print("没有待起草的政策。")
        return 0
    print("发现 %d 条疑似变化，开始起草…\n" % len(todo))
    for p in todo:
        text = freshness.fetch_text(p.get("source_url", ""))
        d = redraft.draft(p, text)
        d["diff"] = redraft.diff(p, d)
        kb.save_draft(p["id"], d)
        print("%-16s %s" % (p["id"], d.get("change_note", "")))
        for row in d["diff"]:
            print("    %s：%s -> %s" % (row["label"], row["before"][:40], row["after"][:40]))
    print("\n草稿已存入 policies.json 的 draft 字段，需人工在界面上采纳或放弃。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
