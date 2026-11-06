# -*- coding: utf-8 -*-
"""生成一份可以直接发给买家的英文报价单（A4，PIL 排版，无新依赖）。"""
import io
import os
import random
import time
from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 1754
M = 90
NAVY = (31, 56, 100)
INK = (33, 37, 43)
SUB = (110, 118, 130)
LINE = (222, 228, 238)

MAT_EN = {"碳纤维": "Carbon Fiber", "铝合金": "Aluminum Alloy", "不锈钢": "Stainless Steel",
          "钢": "Steel", "铁": "Iron", "铜": "Brass", "锌合金": "Zinc Alloy", "羊毛": "Wool",
          "尼龙": "Nylon", "涤纶": "Polyester", "丙纶": "Polypropylene", "塑料": "Plastic",
          "橡胶": "Rubber", "硅藻泥": "Diatomite", "硅藻": "Diatomite", "PVC": "PVC",
          "超细纤维": "Microfiber", "海绵": "Foam", "混纺": "Blend", "聚酯": "Polyester",
          "钛": "Titanium", "镁": "Magnesium", "木": "Wood", "纸": "Paper"}

FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]
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
    return ([env] if env else []) + (LINUX_BOLD if bold else LINUX_FONTS) + FONTS


def _font_paths_ok():
    for p in _candidates():
        if os.path.exists(p):
            return True
    return False


def _font(size, bold=False):
    paths = _candidates(bold)
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _tokens(text):
    """中文按字切，英文按词切——否则 "Racing" 会被拆成 "R / acing"。"""
    out, buf = [], ""
    for ch in str(text or ""):
        if ch == " ":
            out.append(buf + " ")
            buf = ""
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


def build(profile: dict, listing: dict, png_path: str = "", o: dict = None) -> bytes:
    o = o or {}
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    f_co = _font(26, True); f_t = _font(52, True); f_meta = _font(23)
    f_lbl = _font(21); f_sec = _font(28, True); f_row = _font(24); f_small = _font(20)

    co = (o.get("company") or "").strip() or (profile.get("company") or {}).get("name") or "Your Company Name"
    prod = profile.get("product") or {}
    specs = prod.get("specs") or {}
    listing = listing or {}
    now = time.time()

    d.rectangle([0, 0, W, 14], fill=NAVY)
    d.text((M, 70), co, font=f_co, fill=INK)
    d.text((M, 108), "Tianjin, China", font=f_small, fill=SUB)

    d.text((W - M - int(d.textlength("QUOTATION", font=f_t)), 78), "QUOTATION", font=f_t, fill=NAVY)

    no = "Q-%s-%04d" % (time.strftime("%Y%m%d"), random.randint(1, 9999))
    y = 210
    try:
        days = max(1, int(str(o.get("valid") or 30)))
    except Exception:
        days = 30
    meta = [("Quotation No.", no),
            ("Date", time.strftime("%Y-%m-%d")),
            ("Valid Until", time.strftime("%Y-%m-%d", time.localtime(now + days * 86400))),
            ("Trade Term", "FOB " + ((o.get("port") or "Tianjin").strip()))]
    for i, (k, v) in enumerate(meta):
        col = 0 if i % 2 == 0 else 1
        row = i // 2
        x = M + col * 570
        yy = y + row * 40
        d.text((x, yy), k, font=f_lbl, fill=SUB)
        d.text((x + 170, yy), v, font=f_meta, fill=INK)
    y += 100

    d.line([M, y, W - M, y], fill=LINE, width=2)
    y += 24
    d.text((M, y), "To:", font=f_lbl, fill=SUB)
    buyer = (o.get("to") or "").strip()
    if buyer:
        d.text((M + 60, y), buyer[:60], font=f_meta, fill=INK)
    else:
        d.text((M + 60, y), "_" * 46, font=f_meta, fill=(200, 206, 216))
    y += 56

    # 商品行
    d.rectangle([M, y, W - M, y + 46], fill=(242, 245, 250))
    cols = [M + 16, M + 470, M + 700, M + 880]
    for x, t in zip(cols, ["Description", "MOQ", "Lead Time", "Unit Price (FOB)"]):
        d.text((x, y + 10), t, font=f_lbl, fill=SUB)
    y += 46

    row_y = y                      # 三列数值与标题首行对齐，标题换行时不会跟着下沉
    title = listing.get("title") or (prod.get("name_cn") or "Product")
    for ln in _wrap(d, title, f_row, 430)[:2]:
        d.text((cols[0], y + 12), ln, font=f_row, fill=INK)
        y += 34
    mat_en = MAT_EN.get(prod.get("material", ""), "")
    if not mat_en and prod.get("material") and all(ord(c) < 128 for c in prod["material"]):
        mat_en = prod["material"]
    spec_txt = " / ".join(filter(None, [
        ("Size " + specs["size"]) if specs.get("size") else "",
        ("Weight " + specs["weight"]) if specs.get("weight") else "",
        ("Material " + mat_en) if mat_en else ""]))
    if spec_txt:
        # 换行而不截断：宁可两行，也别写成 "Material Carbon Fib…"
        room = cols[1] - cols[0] - 24
        for ln in _wrap(d, spec_txt, f_small, room)[:2]:
            d.text((cols[0], y + 6), ln, font=f_small, fill=SUB)
            y += 26
    y += 10

    d.text((cols[1], row_y + 12), (o.get("moq") or specs.get("moq", "—")), font=f_row, fill=INK)
    d.text((cols[2], row_y + 12), (o.get("lead") or specs.get("lead_time", "—")), font=f_row, fill=INK)
    price = (o.get("price") or listing.get("price_band") or "—").replace("/ pc", "").replace("/pc", "").strip()
    d.text((cols[3], row_y + 12), price[:24], font=f_row, fill=INK)

    y += 26
    d.line([M, y, W - M, y], fill=LINE, width=1)
    y += 40

    # Terms
    d.text((M, y), "Terms & Conditions", font=f_sec, fill=NAVY)
    y += 52
    certs = profile.get("certs") or []
    terms = [
        ("Payment", (o.get("payment") or "30% T/T deposit, balance against copy of B/L").strip()),
        ("Packing", "Standard export carton, protective corner reinforced"),
        ("Port of Loading", (o.get("port") or "Tianjin").strip() + ", China"),
        ("Validity", "%d days from the date of this quotation" % days),
        ("Certificates held", "、".join(certs) if certs else "None declared"),
        ("Remarks", "Prices subject to final confirmation of specification and quantity."),
    ]
    for k, v in terms:
        d.text((M, y), k, font=f_lbl, fill=SUB)
        for i, ln in enumerate(_wrap(d, v, f_row, W - 2 * M - 220)):
            d.text((M + 220, y + i * 34), ln, font=f_row, fill=INK)
        y += 34 * max(1, len(_wrap(d, v, f_row, W - 2 * M - 220))) + 16

    d.line([M, H - 150, W - M, H - 150], fill=LINE, width=1)
    d.text((M, H - 128), "Prepared by %s  ·  Generated with AI assistance, subject to written confirmation." % co,
           font=f_small, fill=(150, 158, 170))

    if png_path:
        img.save(png_path)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()
