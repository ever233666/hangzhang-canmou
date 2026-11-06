# -*- coding: utf-8 -*-
"""检查政策来源是否有更新。用法：python tools/refresh_policies.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import freshness  # noqa: E402

if __name__ == "__main__":
    print("开始检查来源（每条 1 次请求，约 20 秒）…\n")
    freshness.refresh_all()
    print("\n提示：变化只代表原文动了，条款描述需要人工复核后再改 verified。")
