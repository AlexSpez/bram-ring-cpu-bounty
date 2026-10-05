#!/usr/bin/env python3
"""BRAM-ring bounty poster (docs/bounty-poster.png), 1600x900, for the announcement tweet.

Regenerate when a headline number changes:
    python3 -m venv /tmp/poster && /tmp/poster/bin/pip install pillow segno
    /tmp/poster/bin/python docs/bounty-poster.py
Fonts: Lato and Ubuntu Mono as packaged on Ubuntu 24.04 (fonts-lato, fonts-ubuntu).
"""
import os
from PIL import Image, ImageDraw, ImageFont
import segno, io, math

W, H = 1600, 900
BG, BG2 = (10, 15, 30), (18, 26, 52)
WHITE, MUTED, GOLD, DARK = (255, 255, 255), (150, 160, 182), (245, 183, 0), (10, 15, 30)
F = "/usr/share/fonts/truetype/"
def font(name, size): return ImageFont.truetype(F + name, size)
BLACK = lambda s: font("lato/Lato-Black.ttf", s)
BOLD  = lambda s: font("lato/Lato-Bold.ttf", s)
REG   = lambda s: font("lato/Lato-Regular.ttf", s)
MONO  = lambda s: font("ubuntu/UbuntuMono-B.ttf", s)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
# vertical gradient + faint dot grid
for y in range(H):
    t = y / H
    d.line([(0, y), (W, y)], fill=tuple(int(BG[i] + (BG2[i] - BG[i]) * t) for i in range(3)))
for x in range(40, W, 40):
    for y in range(40, H, 40):
        d.point((x, y), fill=(30, 40, 70))

def text(xy, s, f, fill=WHITE, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)

def rich_center(y, parts, f):
    """parts = [(text, color), ...] centered as one line."""
    total = sum(d.textlength(t, font=f) for t, _ in parts)
    x = (W - total) / 2
    for t, c in parts:
        d.text((x, y), t, font=f, fill=c, anchor="la")
        x += d.textlength(t, font=f)

# ---------- headline ----------
text((W // 2, 22), "BRAM-RING PROOF-OF-WORK BOUNTY", BOLD(18), fill=GOLD, anchor="ma")
h1 = BLACK(72)
rich_center(50, [("MY LITTLE ", WHITE), ("$40 FPGA", GOLD)], h1)
rich_center(128, [("CAN BEAT YOUR BIG BAD GPU.", WHITE)], h1)

# ---------- contenders ----------
# left: tiny chip
cx, cy, s = 300, 385, 56          # chip body half-size
body = [cx - s, cy - s, cx + s, cy + s]
# pins
for i in range(7):
    o = -s + 10 + i * 16
    d.rectangle([cx + o - 4, cy - s - 14, cx + o + 4, cy - s], fill=GOLD)
    d.rectangle([cx + o - 4, cy + s, cx + o + 4, cy + s + 14], fill=GOLD)
    d.rectangle([cx - s - 14, cy + o - 4, cx - s, cy + o + 4], fill=GOLD)
    d.rectangle([cx + s, cy + o - 4, cx + s + 14, cy + o + 4], fill=GOLD)
d.rounded_rectangle(body, radius=8, fill=(28, 30, 40), outline=(90, 96, 115), width=3)
d.ellipse([cx - s + 8, cy - s + 8, cx - s + 16, cy - s + 16], fill=(90, 96, 115))
# tiny crown on the little chip
ct = cy - s - 14 - 8
d.polygon([(cx - 34, ct), (cx - 34, ct - 30), (cx - 17, ct - 14), (cx, ct - 40), (cx + 17, ct - 14), (cx + 34, ct - 30), (cx + 34, ct)], fill=GOLD)
for px in (cx - 34, cx, cx + 34):
    py = ct - 30 if px != cx else ct - 40
    d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=GOLD)
d.rectangle([cx - 34, ct - 6, cx + 34, ct], fill=(210, 150, 0))
text((cx, cy - 6), "Tz170", BOLD(22), fill=WHITE, anchor="mm")
text((cx, cy + 18), "FPGA", REG(14), fill=MUTED, anchor="mm")
text((cx, 490), "Efinix Tz170", BOLD(28), anchor="ma")
text((cx, 526), "$40 chip", REG(24), fill=MUTED, anchor="ma")
text((cx, 558), "37,100 H/s", BLACK(34), fill=GOLD, anchor="ma")

# middle: VS
text((W // 2 - 30, 385), "VS", BLACK(64), fill=GOLD, anchor="mm")

# right: big bad GPU
gx0, gy0, gx1, gy1 = 700, 268, 1440, 468
d.rounded_rectangle([gx0, gy0, gx1, gy1], radius=22, fill=(40, 43, 54), outline=(95, 100, 120), width=4)
d.rounded_rectangle([gx0 + 18, gy0 + 16, gx1 - 18, gy1 - 16], radius=16, outline=(60, 64, 78), width=2)
for fx in (gx0 + 140, gx0 + 370, gx0 + 600):
    fy, r = (gy0 + gy1) // 2, 82
    d.ellipse([fx - r, fy - r, fx + r, fy + r], fill=(22, 24, 32), outline=(110, 115, 135), width=4)
    for k in range(9):
        a = k * 2 * math.pi / 9
        d.line([(fx + 18 * math.cos(a), fy + 18 * math.sin(a)),
                (fx + (r - 8) * math.cos(a + 0.55), fy + (r - 8) * math.sin(a + 0.55))],
               fill=(70, 74, 90), width=7)
    d.ellipse([fx - 22, fy - 22, fx + 22, fy + 22], fill=(55, 58, 70), outline=(120, 125, 145), width=3)
# PCB + PCIe edge connector
d.rectangle([gx0 + 40, gy1, gx1 - 120, gy1 + 22], fill=(14, 60, 46))
for px in range(gx0 + 60, gx1 - 140, 12):
    d.rectangle([px, gy1 + 22, px + 7, gy1 + 36], fill=GOLD)
# 8-pin power plug
d.rectangle([gx1 - 110, gy0 - 14, gx1 - 40, gy0], fill=(22, 24, 32), outline=(95, 100, 120), width=2)
gcx = (gx0 + gx1) // 2
text((gcx, 516), "RTX 3070", BOLD(28), anchor="ma")
text((gcx, 552), "$499 card", REG(24), fill=MUTED, anchor="ma")
text((gcx, 586), "1,493 H/s", BLACK(34), fill=WHITE, anchor="ma")

# ---------- per-dollar bars ----------
by = 644
text((80, by), "HASHES PER SECOND PER DOLLAR", BOLD(18), fill=MUTED)
bar_x0, bar_w, bh = 80, 1000, 16
d.rounded_rectangle([bar_x0, by + 30, bar_x0 + bar_w, by + 30 + bh], radius=8, fill=GOLD)
text((bar_x0 + bar_w + 16, by + 30 + bh / 2), "FPGA  371", BOLD(22), fill=GOLD, anchor="lm")
gw = max(6, round(bar_w * 3 / 371))
d.rounded_rectangle([bar_x0, by + 58, bar_x0 + gw, by + 58 + bh], radius=4, fill=(160, 165, 185))
text((bar_x0 + gw + 16, by + 58 + bh / 2), "GPU  3     (a 100\u00d7 gap)", BOLD(22), fill=WHITE, anchor="lm")
text((80, by + 86), "FPGA priced at $100 per chip incl. board and margin; GPU at launch price. Full pricing rules in BOUNTY.md.",
     REG(15), fill=MUTED)

# ---------- call to action band ----------
cy0, cy1 = 768, 826
d.rectangle([0, cy0, W, cy1], fill=GOLD)
text((W // 2, (cy0 + cy1) // 2), "PROVE ME WRONG. WIN 0.1 BTC.", BLACK(40), fill=DARK, anchor="mm")

# ---------- footer ----------
text((W // 2, 846), "+0.01 BTC every time you beat my GPU or CPU kernel by 10%   \u00b7   Deadline 30 Nov 2026   \u00b7   @PeterRizun",
     BOLD(19), fill=WHITE, anchor="mm")
text((W // 2, 876), "Rules + code: git.nodelabs.ca/nexapow/bram-ring   \u00b7   Claim: reply to the tweet with your commit hash",
     MONO(21), fill=MUTED, anchor="mm")

# ---------- QR + links (right column, above the band) ----------
url = "https://git.nodelabs.ca/nexapow/bram-ring/-/blob/main/BOUNTY.md"
qr = segno.make(url, error="m")
buf = io.BytesIO(); qr.save(buf, kind="png", scale=4, border=1, dark="#ffffff", light=None); buf.seek(0)
qimg = Image.open(buf).convert("RGBA")
qs = 128
qimg = qimg.resize((qs, qs), Image.NEAREST)
img.paste(qimg, (W - 60 - qs, 34), qimg)
text((W - 60 - qs // 2, 34 + qs + 6), "scan for the rules", REG(15), fill=MUTED, anchor="ma")

img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bounty-poster.png"), optimize=True)
print("ok")
