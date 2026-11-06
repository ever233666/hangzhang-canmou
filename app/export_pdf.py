# -*- coding: utf-8 -*-
"""把合规清单导成一张可打印的 PDF（用 PIL 排版后存为 PDF，不引入新依赖）。"""
import io
import os
import time
from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 1754          # A4 @150dpi
M = 90
NAVY = (31, 56, 100)
INK = (33, 37, 43)
SUB = (110, 118, 130)
LINE = (222, 228, 238)
SEV = {"must": ("必须先做", (192, 57, 43), (253, 236, 234)),
       "should": ("建议做", (185, 119, 14), (253, 243, 227)),
       "info": ("了解即可", (91, 100, 114), (238, 241, 245))}

FONT_PATHS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]
# 容器 / macOS 上的中文字体：Linux 系统装 fonts-noto-cjk 或 wqy 即可
# 也可以用环境变量 PDF_FONT 直接指定一个 ttf/ttc 路径
LINUX_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-SC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
LINUX_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def _candidates(bold=False):
    env = os.getenv("PDF_FONT", "").strip()
    return ([env] if env else []) + (LINUX_BOLD if bold else []) + FONT_PATHS


def _font_paths_ok():
    for p in _candidates():
        if os.path.exists(p):
            return True
    return False


def _font(size, bold=False):
    for p in _candidates(bold):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _tokens(text):
    """中文按字切，英文按词切，避免把英文单词拆成两半。"""
    out, buf = [], ""
    for ch in str(text or ""):
        if ch == "\n":
            if buf:
                out.append(buf); buf = ""
            out.append("\n")
        elif ch == " ":
            out.append(buf + " "); buf = ""
        elif ord(ch) < 128:
            buf += ch
        else:
            if buf:
                out.append(buf); buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out


def _wrap(draw, text, font, maxw):
    lines, cur = [], ""
    for tok in _tokens(text):
        if tok == "\n":
            lines.append(cur); cur = ""
            continue
        if draw.textlength(cur + tok, font=font) <= maxw:
            cur += tok
            continue
        if cur.strip():
            lines.append(cur.rstrip())
        cur = tok.lstrip(" ")
        while cur and draw.textlength(cur, font=font) > maxw and len(cur) > 1:
            cut = len(cur) - 1
            while cut > 1 and draw.textlength(cur[:cut], font=font) > maxw:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def build(profile: dict, listing: dict, items: list, png_path: str = "") -> bytes:
    f_title = _font(46, True); f_meta = _font(24); f_h = _font(30, True)
    f_body = _font(25); f_small = _font(21); f_badge = _font(21, True)

    pages, page, draw = [], None, None

    def new_page():
        nonlocal page, draw
        page = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(page)
        pages.append(page)
        return draw

    def header(y):
        draw.rectangle([0, 0, W, 12], fill=NAVY)
        draw.text((M, y), "出口合规清单", font=f_title, fill=NAVY)
        y += 66
        prod = (profile.get("product") or {})
        mk = {"eu": "欧盟", "us": "美国", "uk": "英国"}.get((profile.get("market") or {}).get("region"), "未填")
        meta = "企业：%s　产品：%s　目标市场：%s　生成：%s" % (
            (profile.get("company") or {}).get("name") or "未填写",
            prod.get("name_cn") or "未填写", mk, time.strftime("%Y-%m-%d %H:%M"))
        for ln in _wrap(draw, meta, f_meta, W - 2 * M):
            draw.text((M, y), ln, font=f_meta, fill=SUB); y += 32
        y += 8
        draw.line([M, y, W - M, y], fill=LINE, width=2)
        return y + 26

    new_page()
    y = header(M)

    order = {"must": 0, "should": 1, "info": 2}
    for it in sorted(items, key=lambda x: order.get(x.get("severity"), 3)):
        sev = it.get("severity") or "should"
        label, fg, bg = SEV.get(sev, SEV["should"])
        if it.get("have"):
            label, fg, bg = "已具备", (45, 122, 79), (234, 250, 239)
        w = M + int(draw.textlength(label, font=f_badge)) + 28

        title_lines = _wrap(draw, it.get("title"), f_h, W - 2 * M - 10)
        req_lines = _wrap(draw, it.get("requirement"), f_body, W - 2 * M)
        why = it.get("why") or ""
        why_lines = _wrap(draw, "为什么适用：" + why, f_small, W - 2 * M - 10) if why else []

        block = 44 + len(title_lines) * 40 + len(req_lines) * 36 + len(why_lines) * 30 + 110
        if y + block > H - 130:
            new_page(); y = header(M)

        draw.rounded_rectangle([M, y, w, y + 34], radius=8, fill=bg)
        draw.text((M + 12, y + 5), label, font=f_badge, fill=fg)
        y += 46

        for ln in title_lines:
            draw.text((M, y), ln, font=f_h, fill=INK); y += 40
        y += 6
        for ln in req_lines:
            draw.text((M, y), ln, font=f_body, fill=INK); y += 36
        if why_lines:
            y += 2
            for ln in why_lines:
                draw.text((M, y), ln, font=f_small, fill=SUB); y += 30
        y += 12

        # 来源一行：先截到能放下的长度，再画勾选框，避免两者相撞
        room = W - 2 * M - 250
        src = (it.get("source") or "") + "  " + (it.get("source_url") or "")
        while src and draw.textlength(src, font=f_small) > room:
            src = src[:-2]
        draw.text((M, y), src, font=f_small, fill=(120, 130, 145))
        box = "■ 已具备    □ 办理中" if it.get("have") else "□ 已具备    □ 办理中"
        draw.text((W - M - 205, y), box, font=f_small, fill=(45, 122, 79) if it.get("have") else INK)
        y += 40
        draw.line([M, y, W - M, y], fill=LINE, width=1)
        y += 30

    footer = ("本清单由 AI 辅助生成，条款以来源原文为准；是否适用于贵司产品请逐条核对。"
              "本文件不构成法律意见，也不代表已完成检测或认证。")
    for pg in pages:
        d = ImageDraw.Draw(pg)
        d.line([M, H - 100, W - M, H - 100], fill=LINE, width=1)
        for i, ln in enumerate(_wrap(d, footer, f_small, W - 2 * M)[:2]):
            d.text((M, H - 86 + i * 26), ln, font=f_small, fill=(150, 158, 170))

    if png_path:
        pages[0].save(png_path)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buf.getvalue()
