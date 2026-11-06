# -*- coding: utf-8 -*-
"""零依赖 HTTP 服务。只用标准库，克隆下来就能跑，不需要 pip install。"""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import agent as agent_mod
from . import (config, export_pdf, export_quote, export_quote_docx, freshness, kb, llm,
               materials, redraft, secrets, store)

MAX_BODY = 8 * 1024 * 1024

# 公网部署要一把门锁：官方提交要求「智能体链接+账号密码」，
# 而且不设防的话，谁拿到链接都能烧部署方的模型额度。
AUTH_COOKIE = "cccm_auth"
AUTH_EXEMPT_GET = ("/login", "/favicon.ico", "/api/health")
_FAILS = {}          # ip -> [时间戳]；一分钟内错 6 次就歇一会儿
_FAIL_WINDOW = 600
_FAIL_MAX = 6


def _auth_on() -> bool:
    return bool(config.ACCESS_PASSWORD)


def _auth_token() -> str:
    key = ("%s:%s" % (config.ACCESS_USER, config.ACCESS_PASSWORD)).encode("utf-8")
    return hmac.new(key, b"cccm-v1", hashlib.sha256).hexdigest()[:40]


# 不设访问口令时，公网链接谁都能用——至少别让人把模型额度刷干。
# 按 IP 限速；拿不到真实 IP（网关没透传 X-Forwarded-For）时不拦，
# 否则所有评委共用一个桶，反而会误伤。
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "120") or 0)
_HITS = {}


def _client_ip(handler) -> str:
    xff = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if xff:
        return xff
    return handler.client_address[0] if handler.client_address else ""


def _is_private(ip: str) -> bool:
    if not ip:
        return True
    if ip.startswith(("10.", "192.168.", "127.", "::1", "0.", "169.254.")):
        return True
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except Exception:
            return False
    return False


def _rate_ok(ip: str) -> bool:
    if RATE_LIMIT <= 0 or _is_private(ip):
        return True
    now = time.time()
    hits = [t for t in _HITS.get(ip, []) if now - t < 3600]
    if len(hits) >= RATE_LIMIT:
        _HITS[ip] = hits
        return False
    hits.append(now)
    _HITS[ip] = hits
    if len(_HITS) > 4000:
        _HITS.clear()
    return True


def _too_many(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _FAILS.get(ip, []) if now - t < _FAIL_WINDOW]
    _FAILS[ip] = hits
    return len(hits) >= _FAIL_MAX


def _note_fail(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


class Handler(BaseHTTPRequestHandler):
    server_version = "ChangZhangCanMou/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- helpers ----------
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, code, msg):
        self._json({"ok": False, "error": msg}, code)

    # ---------- 口令 ----------
    def _cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie") or ""
        try:
            c = SimpleCookie()
            c.load(raw)
            return c[name].value if name in c else ""
        except Exception:
            return ""

    def _authed(self) -> bool:
        if not _auth_on():
            return True
        return hmac.compare_digest(self._cookie(AUTH_COOKIE), _auth_token())

    def _send_auth(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200"
                         % (AUTH_COOKIE, _auth_token()))
        self.end_headers()
        self.wfile.write(body)

    def _clear_auth(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % AUTH_COOKIE)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("图片太大了，换一张 5MB 以内的")
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")

    @staticmethod
    def _hydrate(art: dict, prof: dict = None) -> dict:
        """政策正文用最新数据，确认状态用「当前这位客户」的档案。
        两者分开，换个人来问就不会看到上一个人的痕迹。"""
        conf = (prof or {}).get("confirmations", {}) or {}

        def stamp(item, key):
            c = conf.get(key) or {}
            item["confirmed"] = bool(c)
            item["confirmed_at"] = c.get("at", "")
            item["confirmed_by"] = c.get("by", "")

        if art.get("policies"):
            ids = [p.get("id") for p in art["policies"]]
            fresh = {p["id"]: p for p in kb.policies()}
            rows = []
            for i in ids:
                if i in fresh:
                    row = dict(fresh[i])
                    stamp(row, i)
                    rows.append(row)
            art["policies"] = rows
        if art.get("compliance"):
            certs = (prof or {}).get("certs", []) or []
            rules_by_id = {r["id"]: r for r in kb.rules()}
            for c in art["compliance"]:
                stamp(c, c.get("rule_id"))
                rule = rules_by_id.get(c.get("rule_id"))
                if rule:
                    hit = agent_mod.agent._held(rule, certs)
                    c["have"] = bool(hit)
                    c["held_by"] = hit
        return art

    def _session(self, sid: str):
        s = store.load("session", sid) if sid else {}
        if not s:
            s = store.new_session()
            store.save("session", s["id"], s)
        return s

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/login":
            if not _auth_on():                 # 没设口令就别摆一个假的登录框
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._file(os.path.join(config.WEB, "login.html"), "text/html; charset=utf-8")
        if (path not in AUTH_EXEMPT_GET and not path.startswith("/static/")
                and not self._authed()):
            # 接口给 401，页面跳登录页——评委点开链接看到的是登录框，不是空白
            if path.startswith("/api/"):
                return self._err(401, "需要口令")
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/", "/index.html"):
            return self._file(os.path.join(config.WEB, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = os.path.normpath(os.path.join(config.WEB, rel))
            if not target.startswith(str(config.WEB)):
                return self._err(403, "forbidden")
            return self._file(target)
        if path == "/api/health":
            return self._json({"ok": True, "mock": config.MOCK,
                               "model": config.LLM_MODEL or "(未配置)",
                               "auth": _auth_on(), "vision": config.VISION_READY})
        if path == "/api/logout":
            return self._clear_auth()
        if path == "/api/usage":
            return self._json({"ok": True, "usage": llm.usage(), "mock": config.MOCK})
        if path == "/api/export/quote.docx":
            sid = (parse_qs(u.query).get("sid") or [""])[0]
            s = self._session(sid)
            prof = store.load("profile", s["profile_id"]) or store.empty_profile()
            art = self._hydrate(s.get("artifacts", {}) or {}, prof)
            listing = art.get("listing") or {}
            if not listing:
                return self._err(400, "还没有生成 listing，无法报价")
            q = parse_qs(u.query)
            opts = {k: (q.get(k) or [""])[0] for k in
                    ("company", "to", "price", "moq", "lead", "payment", "port", "valid")}
            data = export_quote_docx.build(prof, listing, o=opts)
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", 'attachment; filename="quotation.docx"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/export/quote":
            sid = (parse_qs(u.query).get("sid") or [""])[0]
            s = self._session(sid)
            prof = store.load("profile", s["profile_id"]) or store.empty_profile()
            art = self._hydrate(s.get("artifacts", {}) or {}, prof)
            listing = art.get("listing") or {}
            if not listing:
                return self._err(400, "还没有生成 listing，无法报价")
            q = parse_qs(u.query)
            opts = {k: (q.get(k) or [""])[0] for k in
                    ("company", "to", "price", "moq", "lead", "payment", "port", "valid")}
            pdf = export_quote.build(prof, listing, o=opts)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="quotation.pdf"')
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)
            return
        if path == "/api/export/compliance":
            sid = (parse_qs(u.query).get("sid") or [""])[0]
            s = self._session(sid)
            prof = store.load("profile", s["profile_id"]) or store.empty_profile()
            art = self._hydrate(s.get("artifacts", {}) or {}, prof)
            items = art.get("compliance") or []
            if not items:
                return self._err(400, "还没有生成合规清单")
            pdf = export_pdf.build(prof, art.get("listing") or {}, items)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="compliance-checklist.pdf"')
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)
            return
        if path == "/api/byok":
            return self._json({"ok": True, **secrets.masked(), "mock": config.MOCK})
        if path == "/api/freshness":
            return self._json({"ok": True, **freshness.status()})
        if path == "/api/progress":
            return self._json({"ok": True, "progress": kb.progress()})
        if path == "/api/kb":
            return self._json({"ok": True, "rules": len(kb.rules()), "policies": len(kb.policies())})
        if path == "/api/session":
            sid = (parse_qs(u.query).get("id") or [""])[0]
            s = self._session(sid)
            store.save("session", s["id"], s)
            prof = store.load("profile", s["profile_id"]) or store.empty_profile()
            return self._json({"ok": True, "session_id": s["id"], "state": s["state"],
                               "messages": s["messages"], "artifacts": self._hydrate(s.get("artifacts", {}) or {},
                                                      store.load("profile", s["profile_id"]) or {}),
                               "profile": agent_mod.agent._public_profile(prof),
                               "mock": config.MOCK})
        return self._err(404, "not found")

    def _file(self, target: str, ctype: str = ""):
        if not os.path.isfile(target):
            return self._err(404, "not found")
        if not ctype:
            ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
        with open(target, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._body()
        except ValueError as e:
            return self._err(400, str(e))

        if path == "/api/login":
            ip = self.client_address[0] if self.client_address else "?"
            if _too_many(ip):
                return self._err(429, "错太多次了，等十分钟再来")
            user = str(data.get("user") or config.ACCESS_USER).strip()
            pwd = str(data.get("password") or "")
            if not _auth_on():
                return self._json({"ok": True, "auth": False})
            good = (hmac.compare_digest(user, config.ACCESS_USER)
                    and hmac.compare_digest(pwd, config.ACCESS_PASSWORD))
            if not good:
                _note_fail(ip)
                return self._err(403, "账号或口令不对")
            return self._send_auth({"ok": True, "auth": True})

        if not self._authed():
            return self._err(401, "需要口令")

        if path in ("/api/chat", "/api/upload") and not _rate_ok(_client_ip(self)):
            return self._err(429, "这个链接被用得太频繁了，过一会儿再试。")

        sid = data.get("session_id") or ""
        try:
            if path == "/api/chat":
                sess = self._session(sid)
                out = agent_mod.agent.handle(sess, text=data.get("text", ""))
                return self._json({"ok": True, **out})
            if path == "/api/upload":
                sess = self._session(sid)
                b64 = data.get("data", "")
                if not b64:
                    return self._err(400, "没有收到图片")
                if b64.startswith("data:"):
                    b64 = b64.split(",", 1)[-1]
                out = agent_mod.agent.handle(sess, image_b64=b64, mime=data.get("mime", "image/jpeg"))
                return self._json({"ok": True, **out})
            if path == "/api/policy":
                sess = self._session(sid)
                prof = store.load("profile", sess["profile_id"]) or store.empty_profile()
                pol = kb.match_policies(prof)
                sess.setdefault("artifacts", {})["policies"] = pol
                store.save("session", sess["id"], sess)
                return self._json({"ok": True, "policies": pol})
            if path == "/api/verify":
                kind = data.get("kind") or "rule"
                item_id = data.get("id") or ""
                if kind not in ("rule", "policy") or not item_id:
                    return self._err(400, "kind 或 id 不合法")
                # 确认是「这个客户」的动作，写进他自己的档案，不写政策库
                sess = self._session(sid)
                prof = store.load("profile", sess["profile_id"]) or store.empty_profile()
                prof["id"] = sess["profile_id"]
                actor = prof.get("company", {}).get("name") or "本企业"
                conf = prof.setdefault("confirmations", {})
                # 记下确认那一刻的正文指纹，将来原文变了能对上是对着哪一版确认的
                src_hash = next((r.get("source_hash", "") for r in kb.policies()
                                 if r.get("id") == item_id), "")
                conf[item_id] = {
                    "kind": kind,
                    "at": time.strftime("%Y-%m-%d %H:%M"),
                    "by": actor,
                    "hash": src_hash,
                }
                store.save("profile", prof["id"], prof)
                return self._json({"ok": True, "changed": True, "actor": actor,
                                   "at": conf[item_id]["at"],
                                   "confirmed": len(conf)})
            if path == "/api/claim":
                rid = data.get("rule_id") or ""
                rule = kb.find_rule(rid)
                if not rule:
                    return self._err(404, "没有这条规则")
                token = agent_mod.agent._cert_of(rule)
                if not token:
                    return self._err(400, "这条不是可持有的资质，无法登记")
                sess = self._session(sid)
                prof = store.load("profile", sess["profile_id"]) or store.empty_profile()
                prof["id"] = sess["profile_id"]
                certs = [c for c in prof.get("certs", []) if str(c).upper() != token.upper()]
                certs.append(token)
                prof["certs"] = certs[:8]
                # 标准不是认证：16 CFR 1630 是标准代号，CE 才是资质。
                # 分开记，界面上才敢如实写「已确认满足」，而不是「已有认证」。
                # CE / UKCA / UL 是「持有证书」；CPSIA、RoHS、REACH、GPSR 是「符合法规」，
                # 后者没有证书可发，归到「已确认满足」，否则档案里会写成「已有认证：GPSR」
                std = re.match(r"(?:\d{2}\s?CFR|EN[\s-]|ISO[\s-]|AS/?NZS|GB/?T?\s?\d|JIS|TB\s?117"
                               r"|CPSIA|RoHS|REACH|GPSR|Prop\s?65|LFGB|FDA)",
                               token, re.I)
                prof.setdefault("certs_meta", {})[token] = "standard" if std else "cert"
                prof.setdefault("confirmations", {})[rid] = {
                    "kind": "rule",
                    "at": time.strftime("%Y-%m-%d %H:%M"),
                    "by": prof.get("company", {}).get("name") or "本企业",
                    "hash": "",
                }
                store.save("profile", prof["id"], prof)
                return self._json({"ok": True, "certs": prof["certs"], "cert": token})
            if path == "/api/byok":
                if data.get("clear"):
                    secrets.clear()
                    return self._json({"ok": True, "configured": False})
                out = secrets.save(data.get("base_url", ""), data.get("api_key", ""),
                                   data.get("model", ""), data.get("vision_model", ""))
                return self._json({"ok": True, **out, "mock": config.MOCK})
            if path == "/api/materials":
                pid = data.get("id") or ""
                pol = kb.find_policy(pid)
                if not pol:
                    return self._err(404, "没有这条政策")
                sess = self._session(sid)
                prof = store.load("profile", sess["profile_id"]) or store.empty_profile()
                out = materials.build(pol, prof)
                kb.save_materials(pid, out)
                return self._json({"ok": True, "materials": out})
            if path == "/api/redraft":
                pid = data.get("id") or ""
                pol = kb.find_policy(pid)
                if not pol:
                    return self._err(404, "没有这条政策")
                text = freshness.fetch_text(pol.get("source_url", ""))
                d = redraft.draft(pol, text)
                d["diff"] = redraft.diff(pol, d)
                d["fetched_chars"] = len(text)
                kb.save_draft(pid, d)
                return self._json({"ok": True, "draft": d})
            if path == "/api/adopt":
                pol = kb.adopt_draft(data.get("id") or "")
                if not pol:
                    return self._err(404, "没有可采纳的草稿")
                return self._json({"ok": True, "policy": pol})
            if path == "/api/discard":
                ok = kb.discard_draft(data.get("id") or "")
                return self._json({"ok": ok})
            if path == "/api/reset":
                sess = store.new_session()
                store.save("session", sess["id"], sess)
                prof = store.empty_profile()
                prof["id"] = sess["profile_id"]
                store.save("profile", prof["id"], prof)
                return self._json({"ok": True, "session_id": sess["id"], "state": sess["state"],
                                   "messages": [], "artifacts": {},
                                   "profile": agent_mod.agent._public_profile(prof),
                                   "mock": config.MOCK})
        except Exception as e:
            sys.stderr.write("ERR %s\n" % e)
            return self._err(500, "服务端出错：%s" % e)
        return self._err(404, "not found")


def serve(host: str = None, port: int = None):
    host = host or config.HOST
    port = port or config.PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    mode = "MOCK（无需密钥，全流程可跑）" if config.MOCK else "LIVE（%s）" % config.LLM_MODEL
    print("=" * 56)
    print("  厂长参谋  ·  产业带工厂的 AI 出海参谋")
    print("  模式：%s" % mode)
    print("  地址：http://%s:%d" % (host, port))
    print("=" * 56)
    if secrets.apply():
        print("  已加载客户自带密钥（BYOK）")
    if config.AUTO_REFRESH:
        freshness.start_background()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
