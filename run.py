# -*- coding: utf-8 -*-
"""启动入口：python run.py  [--port 8000] [--mock]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import config, server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--mock", action="store_true", help="强制使用离线样例模式")
    a = ap.parse_args()
    if a.mock:
        config.MOCK = True
    server.serve(a.host, a.port)


if __name__ == "__main__":
    main()
