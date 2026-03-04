import fitz
from app.fix_pdf import build_fixed_pdf
from app.checks.geometry import infer_page_bleed, get_page_boxes

# create a simple PDF with 1 page, media 630x810 (8.75x11.25)
doc = fitz.open()
page = doc.new_page(width=630, height=810)
# draw a centered rect representing trim area 612x792
trim_w, trim_h = 612, 792
mx = (630 - trim_w) / 2
my = (810 - trim_h) / 2
rect = fitz.Rect(mx, my, mx + trim_w, my + trim_h)
page.draw_rect(rect, color=(0, 0, 0))
buf = doc.write()

# apply build_fixed_pdf with trim 612x792 and bleed 9pt
fixed_bytes, notes = build_fixed_pdf(buf, trim_w, trim_h, 9.0, convert_cmyk=False)
print("Notes:", notes)
# reopen and inspect
fixed_doc = fitz.open(stream=fixed_bytes, filetype="pdf")
print("Page count:", fixed_doc.page_count)
print("Page boxes:", get_page_boxes(fixed_doc))
bleed_info = infer_page_bleed(fixed_doc[0])
print("Infer bleed:", bleed_info)
