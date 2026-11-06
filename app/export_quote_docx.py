# -*- coding: utf-8 -*-
"""可编辑的报价单（Word）。PDF 用来发，Word 用来改。"""
import io
import random
import time

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

from .export_quote import MAT_EN

NAVY = RGBColor(0x1F, 0x38, 0x64)
SUB = RGBColor(0x6E, 0x76, 0x82)
INK = RGBColor(0x21, 0x25, 0x2B)


def _run(p, text, size=10, bold=False, color=INK):
    r = p.add_run(text)
    r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
    r.font.name = "Microsoft YaHei"
    r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    return r


def build(profile: dict, listing: dict, o: dict = None) -> bytes:
    o = o or {}
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(1.8); sec.bottom_margin = Cm(1.6)

    co = (o.get("company") or "").strip() or (profile.get("company") or {}).get("name") or "Your Company Name"
    prod = profile.get("product") or {}
    specs = prod.get("specs") or {}
    certs = profile.get("certs") or []
    listing = listing or {}

    p = doc.add_paragraph(); _run(p, co, 15, True, NAVY)
    p = doc.add_paragraph(); _run(p, "Tianjin, China", 9, False, SUB)

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(p, "QUOTATION", 26, True, NAVY)

    no = "Q-%s-%04d" % (time.strftime("%Y%m%d"), random.randint(1, 9999))
    t = doc.add_table(rows=2, cols=4)
    t.autofit = True
    cells = [("Quotation No.", no), ("Date", time.strftime("%Y-%m-%d")),
             ("Valid Until", time.strftime("%Y-%m-%d", time.localtime(time.time() + 30 * 86400))),
             ("Trade Term", "FOB Tianjin")]
    for i, (k, v) in enumerate(cells):
        r, c = divmod(i, 2)
        _run(t.cell(r, c * 2).paragraphs[0], k, 9, False, SUB)
        _run(t.cell(r, c * 2 + 1).paragraphs[0], v, 10)

    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(12)
    _run(p, "To: ", 9, False, SUB)
    _run(p, (o.get("to") or "").strip() or "________________________________", 10)

    tb = doc.add_table(rows=1, cols=4)
    tb.style = "Table Grid"; tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(["Description", "MOQ", "Lead Time", "Unit Price (FOB)"]):
        _run(tb.rows[0].cells[i].paragraphs[0], h, 9, True, NAVY)

    row = tb.add_row().cells
    desc = listing.get("title") or prod.get("name_cn") or "Product"
    mat = MAT_EN.get(prod.get("material", ""), "")
    sub = " / ".join(filter(None, [
        ("Size " + specs["size"]) if specs.get("size") else "",
        ("Weight " + specs["weight"]) if specs.get("weight") else "",
        ("Material " + mat) if mat else ""]))
    _run(row[0].paragraphs[0], desc, 9)
    if sub:
        _run(row[0].add_paragraph(), sub, 8, False, SUB)
    _run(row[1].paragraphs[0], o.get("moq") or specs.get("moq", "—"), 9)
    _run(row[2].paragraphs[0], o.get("lead") or specs.get("lead_time", "—"), 9)
    price = (o.get("price") or listing.get("price_band") or "—").replace("/ pc", "").replace("/pc", "").strip()
    _run(row[3].paragraphs[0], price, 9)

    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(16)
    _run(p, "Terms & Conditions", 12, True, NAVY)

    try:
        days = max(1, int(str(o.get("valid") or 30)))
    except Exception:
        days = 30
    terms = [("Payment", (o.get("payment") or "30% T/T deposit, balance against copy of B/L").strip()),
             ("Packing", "Standard export carton, protective corner reinforced"),
             ("Port of Loading", (o.get("port") or "Tianjin").strip() + ", China"),
             ("Validity", "%d days from the date of this quotation" % days),
             ("Certificates held", "、".join(certs) if certs else "None declared"),
             ("Remarks", "Prices subject to final confirmation of specification and quantity.")]
    for k, v in terms:
        p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(2)
        _run(p, k + "：", 9, False, SUB); _run(p, v, 10)

    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(24)
    _run(p, "Prepared by %s  ·  可直接在 Word 中修改后再发送" % co, 8, False, RGBColor(0x96, 0x9E, 0xAA))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
