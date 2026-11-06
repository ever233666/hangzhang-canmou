# -*- coding: utf-8 -*-
"""来源新鲜度检查：不重新生成内容，只判断原文有没有变。

策略是三层的：
  日检  链接是否可达（便宜）
  周检  正文指纹是否变化（本模块）
  人工  条款要点是否仍准确（永远需要人）
"""
import hashlib
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request

from . import config

_lock = threading.Lock()
_last = {"at": "", "stats": {}}
_thread = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
_WS = re.compile(r"\s+")


def _normalize(raw: bytes, ctype: str) -> str:
    if "pdf" in ctype or raw[:4] == b"%PDF":
        return hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8", "ignore")
    except Exception:
        text = ""
    text = _SCRIPT.sub(" ", text)
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


def probe(url: str, timeout: int = 15) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(400_000)
            body = _normalize(raw, (r.headers.get("Content-Type") or "").lower())
            return {"ok": True, "status": r.status,
                    "hash": hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()[:16]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "hash": ""}
    except Exception as e:
        return {"ok": False, "status": type(e).__name__, "hash": ""}


def fetch_text(url: str, limit: int = 8000, timeout: int = 20) -> str:
    """抓取并抽正文，供起草修订使用。PDF 不解析，返回空串。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(600_000)
            if raw[:4] == b"%PDF":
                return ""
            text = raw.decode("utf-8", "ignore")
            text = _SCRIPT.sub(" ", text)
            text = _TAG.sub(" ", text)
            return _WS.sub(" ", text).strip()[:limit]
    except Exception:
        return ""


def _scan_file(name: str, stats: dict, log=print) -> None:
    path = config.DATA / name
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data:
        url = item.get("source_url") or ""
        if not url:
            continue
        res = probe(url)
        stats["checked"] += 1
        old = item.get("source_hash", "")
        item["source_checked_at"] = time.strftime("%Y-%m-%d %H:%M")
        if not res["ok"]:
            item["source_status"] = "dead"
            stats["dead"] += 1
            log("  [死链] %-16s %s" % (item["id"], res["status"]))
            continue
        if old and old != res["hash"]:
            item["source_status"] = "changed"
            item["source_changed_at"] = time.strftime("%Y-%m-%d %H:%M")
            stats["changed"] += 1
            log("  [变化] %-16s 正文指纹 %s -> %s" % (item["id"], old, res["hash"]))
        else:
            item["source_status"] = "ok"
            stats["same"] += 1
        item["source_hash"] = res["hash"]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)          # 原子替换，避免读到半截文件


def refresh_all(log=print) -> dict:
    """扫描政策与规则的全部来源。只标记『疑似变化』，不自动改条款描述。"""
    stats = {"checked": 0, "changed": 0, "dead": 0, "same": 0}
    _scan_file("policies.json", stats, log)
    _scan_file("rules.json", stats, log)
    log("扫描 %(checked)d 条：%(same)d 未变，%(changed)d 疑似更新，%(dead)d 不可达" % stats)
    return stats


def refresh_safe(log=print) -> dict:
    """带锁的后台刷新：失败只记日志，绝不影响服务。"""
    with _lock:
        try:
            stats = refresh_all(log=log)
            _last["at"] = time.strftime("%Y-%m-%d %H:%M")
            _last["stats"] = stats
            try:
                from . import kb
                kb.policies.cache_clear()
            except Exception:
                pass
        except Exception as e:
            log("[新鲜度] 扫描失败：%s" % e)
            _last["error"] = str(e)[:120]
    return dict(_last)


def status() -> dict:
    return dict(_last)


def start_background(hours: float = None, log=print) -> None:
    """启动一个守护线程，先扫一次，之后按间隔重扫。"""
    global _thread
    if _thread is not None:
        return
    hours = config.REFRESH_HOURS if hours is None else hours

    def loop():
        while True:
            refresh_safe(log=log)
            time.sleep(max(1.0, hours) * 3600)

    _thread = threading.Thread(target=loop, name="freshness", daemon=True)
    _thread.start()
    log("[新鲜度] 后台检查已启动，间隔 %.0f 小时" % hours)
