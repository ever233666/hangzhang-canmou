# -*- coding: utf-8 -*-
"""全局配置。所有密钥走环境变量或项目根目录的 .env，不写进代码。"""
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB = ROOT / "web"
PROFILES = DATA / "profiles"
SESSIONS = DATA / "sessions"


def _load_env() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

# 容器默认 UTC，报价单和 PDF 上的日期会差一天（晚上生成的显示成前一天）。
# 只在 POSIX 上设：Windows 的 C 运行时不认「Asia/Shanghai」这种 IANA 名字，
# 设了反而会被当成无效值退回 UTC——本地演示时会凭空少八小时。
if os.name == "posix" and not os.getenv("TZ"):
    os.environ["TZ"] = "Asia/Shanghai"
    try:
        time.tzset()
    except Exception:
        pass

# ---- 文本模型（必需）----
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()

# ---- 视觉模型（可选，留空则不启用识图，自动降级为文字描述）----
# 允许与文本模型分开：文本用 DeepSeek，视觉用智谱/阿里的视觉模型。
VISION_MODEL = os.getenv("VISION_MODEL", "").strip()
VISION_BASE_URL = (os.getenv("VISION_BASE_URL", "").strip() or LLM_BASE_URL).rstrip("/")
VISION_API_KEY = os.getenv("VISION_API_KEY", "").strip() or LLM_API_KEY

# 本地跑绑回环地址就够了；容器里（Sealos 会注入 PORT、带 .dockerenv）
# 必须绑 0.0.0.0，否则网关连不进来，表现是「部署成功但打不开」。
_IN_CONTAINER = bool(os.getenv("PORT")) or os.path.exists("/.dockerenv")
HOST = os.getenv("HOST") or ("0.0.0.0" if _IN_CONTAINER else "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# ---- 访问口令（默认关闭）----
# 多数评审链接不需要口令：打开就用，最省事。
# 想加锁时，除了 ACCESS_PASSWORD 还要显式写 REQUIRE_PASSWORD=1——
# 这样平台上残留一个 ACCESS_PASSWORD 也不会把评委挡在门外。
REQUIRE_PASSWORD = os.getenv("REQUIRE_PASSWORD", "").lower() in ("1", "true", "yes", "on")
ACCESS_USER = os.getenv("ACCESS_USER", "judge").strip() or "judge"
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "").strip() if REQUIRE_PASSWORD else ""

# 没有配置文本模型端点时自动进入 MOCK：全流程可跑，输出为预置样例。
MOCK = os.getenv("MOCK", "").lower() in ("1", "true", "yes") or not (LLM_BASE_URL and LLM_API_KEY)

# 识图是否可用：三件套齐全且不在 MOCK 模式
VISION_READY = bool(VISION_MODEL and VISION_BASE_URL and VISION_API_KEY) and not MOCK

PROFILES.mkdir(parents=True, exist_ok=True)
SESSIONS.mkdir(parents=True, exist_ok=True)

DEFAULT_MARKET = "eu"

# 启动时是否在后台扫一遍政策来源（不阻塞服务）。设为 0 可关闭。
AUTO_REFRESH = os.getenv("AUTO_REFRESH", "1").lower() not in ("0", "false", "no")
REFRESH_HOURS = float(os.getenv("REFRESH_HOURS", "24"))
