# -*- coding: utf-8 -*-
"""模型配置自检。用法：python tools/check_llm.py"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402

# 1x1 白色 PNG，只用来验证视觉端点通不通
PIXEL_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
             "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def mask(k: str) -> str:
    if not k:
        return "(未填)"
    return (k[:6] + "…" + k[-4:]) if len(k) > 14 else "(长度可疑，可能没复制全)"


def call(base: str, key: str, payload: dict, timeout: int = 45):
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def explain(code: int) -> str:
    return {
        400: "多半是 model 名字不对，或请求体格式不被接受。",
        401: "密钥无效：检查是否复制全、有没有空格、是否被控制台禁用。",
        402: "余额不足，去控制台充值。",
        403: "有 key 但没权限，可能需要在控制台授权该模型。",
        404: "路径不对，base_url 一般要以 /v1 结尾。",
        429: "限流或额度用尽。",
    }.get(code, "对照官方文档看返回里的 error 字段。")


def probe(label: str, base: str, key: str, model: str, with_image: bool) -> bool:
    content = "只回复两个字：可用"
    msg = {"role": "user", "content": content}
    if with_image:
        msg = {"role": "user", "content": [
            {"type": "text", "text": "这是什么颜色？只回一个字。"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + PIXEL_PNG}},
        ]}
    payload = {"model": model, "messages": [msg], "max_tokens": 16, "temperature": 0}
    t0 = time.time()
    try:
        data = call(base, key, payload)
        dt = (time.time() - t0) * 1000
        text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        print("  [OK]   %-6s %5.0f ms  model=%s  返回：%s" % (label, dt, model, text[:40] or "(空)"))
        return True
    except urllib.error.HTTPError as e:
        print("  [FAIL] %-6s HTTP %s" % (label, e.code))
        print("         %s" % explain(e.code))
        print("         %s" % e.read().decode("utf-8", "ignore")[:200])
        return False
    except urllib.error.URLError as e:
        print("  [FAIL] %-6s 连不上：%s" % (label, e.reason))
        return False
    except Exception as e:
        print("  [FAIL] %-6s %s: %s" % (label, type(e).__name__, e))
        return False


def main() -> int:
    print("=" * 62)
    print("文本  base_url :", config.LLM_BASE_URL or "(未填)")
    print("文本  model    :", config.LLM_MODEL or "(未填)")
    print("文本  api_key  :", mask(config.LLM_API_KEY))
    print("视觉  base_url :", config.VISION_BASE_URL or "(未填)")
    print("视觉  model    :", config.VISION_MODEL or "(未填，识图将降级为文字描述)")
    print("=" * 62)

    if config.MOCK:
        print("\n[样例模式] 不会真正调用模型。")
        print("原因：LLM_BASE_URL 或 LLM_API_KEY 为空。")
        print("\n下一步：复制 .env.example 为 .env，填三个值，再跑本脚本。")
        print("现在也可以 python run.py --mock 直接做 Demo。")
        return 0

    print("\n连通性测试：")
    ok = probe("文本", config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL, False)
    if config.VISION_MODEL:
        if config.VISION_READY:
            probe("视觉", config.VISION_BASE_URL, config.VISION_API_KEY, config.VISION_MODEL, True)
        else:
            print("  [SKIP] 视觉   缺 VISION_API_KEY 或 VISION_BASE_URL")
    else:
        print("  [SKIP] 视觉   未配置，上传照片时会提示「没有接视觉模型」并降级")

    print("\n结论：%s" % ("文本链路可用，python run.py 即可" if ok else "文本链路不通，先修上面的报错"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
